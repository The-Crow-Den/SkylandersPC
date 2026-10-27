# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('workspace', Path(__file__).resolve().parents[1] / 'tools/workspace.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def sfo_fixture():
    keys = b'TITLE_ID\0APP_VER\0'
    values = b'CUSA00000\0' + b'01.00\0'
    start = 20 + 32
    return (struct.pack('<4s4I', b'\0PSF', 0x101, start, start + len(keys), 2)
            + struct.pack('<HHIII', 0, 0x204, 10, 10, 0)
            + struct.pack('<HHIII', 9, 0x204, 6, 6, 10) + keys + values)


def make_game(root):
    game = root / 'game'
    (game / 'sce_sys').mkdir(parents=True)
    (game / 'sce_sys/param.sfo').write_bytes(sfo_fixture())
    elf = bytearray(64)
    elf[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<H', elf, 18, 62)
    struct.pack_into('<I', elf, 20, 1)
    struct.pack_into('<HH', elf, 52, 64, 56)
    (game / 'eboot.bin').write_bytes(elf)
    return game


def fixture_profile(cases=None):
    return {'schema_version': 1, 'id': 'trap-team', 'title': 'Synthetic game',
            'validated_builds': [], 'patches': [], 'acceptance_cases': cases or []}


class MetadataTests(unittest.TestCase):
    def test_unsupported_payload_inventory_does_not_claim_zero_imports(self):
        from test_executable import sce_fixture, self_fixture
        with tempfile.TemporaryDirectory() as directory:
            game = make_game(Path(directory))
            data = self_fixture(sce_fixture())
            struct.pack_into('<Q', data, 32, 0x802)
            (game / 'eboot.bin').write_bytes(data)
            report = w.inventory(game)
            self.assertEqual(report['executable']['inspection_status'], 'unsupported')
            self.assertIsNone(report['imports']['count'])
            self.assertEqual((game / 'eboot.bin').read_bytes(), data)

    def test_inventory_refuses_external_metadata_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = make_game(root)
            original = game / 'sce_sys/param.sfo'
            outside = root / 'external.sfo'
            original.rename(outside)
            original.symlink_to(outside)
            with self.assertRaises(ValueError):
                w.inventory(game)

    def test_failed_json_publication_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            w.write_json(path, {'status': 'prepared'})
            with patch.object(w.os, 'replace', side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError):
                    w.write_json(path, {'status': 'launching'})
            self.assertEqual(w.read_json(path), {'status': 'prepared'})
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_sfo_reads_build_identity(self):
        self.assertEqual(w.read_sfo(sfo_fixture()), {'TITLE_ID': 'CUSA00000', 'APP_VER': '01.00'})

    def test_sfo_rejects_truncation_and_bad_ranges(self):
        data = sfo_fixture()
        for broken in (data[:19], data[:-1], data[:12] + struct.pack('<I', 1) + data[16:]):
            with self.subTest(length=len(broken)), self.assertRaises((ValueError, struct.error)):
                w.read_sfo(broken)

    def test_inventory_is_read_only_and_does_not_claim_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            game = make_game(Path(directory))
            before = {str(p): p.read_bytes() for p in game.rglob('*') if p.is_file()}
            report = w.inventory(game)
            self.assertEqual(report['metadata']['APP_VER'], '01.00')
            self.assertEqual(report['imports']['runtime_resolution'], 'not checked')
            self.assertEqual(report['imports']['status'], 'no import table present')
            self.assertEqual(before, {str(p): p.read_bytes() for p in game.rglob('*') if p.is_file()})
            (game / 'eboot.bin').write_bytes(b'not executable')
            with self.assertRaises(ValueError):
                w.inventory(game)

    def test_self_signature_does_not_claim_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'eboot.bin'
            p.write_bytes(b'O\x15=\x1d' + bytes(60))
            self.assertIn('unknown', w.executable_header(p)['validation'])


class RuntimeAndSessionTests(unittest.TestCase):
    def test_launch_checks_inventory_and_builds_explicit_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = make_game(root)
            (root / 'profiles').mkdir()
            w.write_json(root / 'profiles/trap-team.json', fixture_profile())
            binary = root / '.local/runtime/runtime.AppImage'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'synthetic-runtime')
            w.write_json(root / 'references.lock.json', {'runtime': {'member': binary.name, 'member_sha256': w.digest(binary)}})
            with patch.object(w, 'ROOT', root):
                first = w.prepare_session(game, 'trap-team')
                second = w.prepare_session(game, 'trap-team')
                third = w.prepare_session(game, 'trap-team')
                fake_result = {'returncode': 0, 'reason': 'exited', 'gameplay_verified': False}
                with patch.object(w, 'execute', return_value=fake_result) as executor:
                    result = w.launch_session(first, 5)
                    command, logs, timeout = executor.call_args.args
                    self.assertIn('--ignore-game-patch', command)
                    self.assertEqual(command[command.index('--game') + 1], str(game / 'eboot.bin'))
                    self.assertNotIn('--override-root', command)
                    self.assertFalse(result['gameplay_verified'])
                    with self.assertRaises(ValueError):
                        w.launch_session(first, 5)
                    original_eboot = (game / 'eboot.bin').read_bytes()
                    (game / 'eboot.bin').write_bytes(original_eboot + b'changed')
                    with self.assertRaises(ValueError):
                        w.launch_session(second, 5)
                    (game / 'eboot.bin').write_bytes(original_eboot)
                    changed_profile = fixture_profile()
                    changed_profile['title'] = 'Changed synthetic profile'
                    w.write_json(root / 'profiles/trap-team.json', changed_profile)
                    with self.assertRaisesRegex(ValueError, 'profile changed'):
                        w.launch_session(third, 5)
                    self.assertEqual(executor.call_count, 1)

    def test_execution_logs_failure_and_routes_xdg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = 'import os,sys; print(os.environ["XDG_DATA_HOME"], flush=True); sys.exit(7)'
            result = w.execute([sys.executable, '-c', code], root, 5)
            self.assertEqual(result['returncode'], 7)
            self.assertEqual(result['reason'], 'exited')
            self.assertFalse(result['gameplay_verified'])
            self.assertIn(str(root / 'data'), (root / 'runtime.log').read_text())

    def test_execution_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = w.execute([sys.executable, '-c', 'import time; time.sleep(30)'], Path(directory), 1)
            self.assertEqual(result['reason'], 'timeout')
            self.assertNotEqual(result['returncode'], 0)

    def test_staging_rejects_tampering_and_ignores_unlocked_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'runtime.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('runtime.AppImage', b'synthetic-runtime')
                bundle.writestr('../unexpected', b'never extracted')
            lock = {'runtime': {'archive_sha256': w.digest(archive), 'member': 'runtime.AppImage',
                                'member_sha256': hashlib.sha256(b'synthetic-runtime').hexdigest()}}
            target = w.stage_runtime(archive, lock, root / 'staged')
            self.assertEqual(target.read_bytes(), b'synthetic-runtime')
            self.assertFalse((root / 'unexpected').exists())
            lock['runtime']['member_sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                w.stage_runtime(archive, lock, root / 'staged')
            self.assertEqual(target.read_bytes(), b'synthetic-runtime')
            archive.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                w.stage_runtime(archive, lock, root / 'staged')

    def test_session_preserves_figure_and_marks_unverified_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = make_game(root)
            (root / 'profiles').mkdir()
            w.write_json(root / 'profiles/trap-team.json', fixture_profile(['movement']))
            binary = root / '.local/runtime/runtime.AppImage'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'synthetic-runtime')
            w.write_json(root / 'references.lock.json', {'runtime': {'member': binary.name, 'member_sha256': w.digest(binary)}})
            figure = root / 'original.sky'
            figure.write_bytes(bytes(range(256)) * 4)
            original = figure.read_bytes()
            with patch.object(w, 'ROOT', root):
                first = w.prepare_session(game, 'trap-team', figure)
                second = w.prepare_session(game, 'trap-team', figure)
                binary.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    w.prepare_session(game, 'trap-team', figure)
            self.assertNotEqual(first, second)
            manifest = json.loads((first / 'session.json').read_text())
            self.assertEqual(manifest['status'], 'prepared; not launched')
            self.assertIn('unverified', manifest['profile_build_match'])
            (first / 'figures/working.sky').write_bytes(b'changed by synthetic game')
            self.assertEqual(figure.read_bytes(), original)
            self.assertEqual((second / 'figures/working.sky').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib, io, json, subprocess, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import updater


class UpdaterTest(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(updater.newer('v0.10.0', '0.9.9'))
        self.assertFalse(updater.newer('v0.1.0', '0.1.0'))
        self.assertFalse(updater.newer('nightly', '0.1.0'))

    def test_install_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(updater.install_kind(tmp, windows=False), 'manual')
            (Path(tmp) / 'SkylandersPC.AppImage').write_text('')
            self.assertEqual(updater.install_kind(tmp, windows=False), 'linux')
            (Path(tmp) / 'SkylandersPC.exe').write_text('')
            self.assertEqual(updater.install_kind(tmp, windows=True, frozen=True), 'windows')
            self.assertEqual(updater.install_kind(tmp, windows=True, frozen=False), 'manual')
            (Path(tmp) / '.git').mkdir()
            self.assertEqual(updater.install_kind(tmp), 'git')

    @staticmethod
    def tarball(files, top='SkylandersPC-linux'):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as bundle:
            for name, text in files.items():
                raw = text.encode();info = tarfile.TarInfo(name if name.startswith('/') or '..' in name else f'{top}/{name}')
                info.size = len(raw);bundle.addfile(info, io.BytesIO(raw))
        return data.getvalue()

    @staticmethod
    def release(payload, name='SkylandersPC-v9.0.0-linux.tar.gz', digest=None):
        digest = digest or 'sha256:' + hashlib.sha256(payload).hexdigest()
        return {'version': '9.0.0', 'tag': 'v9.0.0', 'assets': {name: 'https://example.invalid/' + name}, 'digests': {name: digest}}

    @staticmethod
    def opener(payload):
        class Response(io.BytesIO):
            headers = {'Content-Length': str(len(payload))}
        return lambda request, timeout: Response(payload)

    def test_download_verifies_and_stages(self):
        payload = self.tarball({'tools/launcher.py': 'new', 'tools/added.py': 'x'})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);(root / '.local').mkdir()
            (root / updater.MANIFEST).write_text(json.dumps(['tools/launcher.py', 'tools/gone.py', '../escape']))
            seen = []
            top = updater.download(self.release(payload), 'linux', root, seen.append, self.opener(payload))
            self.assertEqual((top / 'tools/launcher.py').read_text(), 'new')
            self.assertEqual(seen[-1], 1.0)
            self.assertEqual((root / updater.STAGING / 'remove.txt').read_text(), 'tools/gone.py\n')
            self.assertEqual(updater.staged(root), '9.0.0')
            self.assertIn('tools/added.py', json.loads((top / updater.MANIFEST).read_text()))

    def test_download_rejects_bad_checksum_and_paths(self):
        payload = self.tarball({'tools/launcher.py': 'new'})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'checksum'):
                updater.download(self.release(payload, digest='sha256:' + '0' * 64), 'linux', root, opener=self.opener(payload))
            self.assertIsNone(updater.staged(root))
            with self.assertRaisesRegex(ValueError, 'checksum'):
                updater.download(self.release(payload, digest='md5:abc'), 'linux', root, opener=self.opener(payload))
            bad = self.tarball({'tools/launcher.py': 'new', '../evil.txt': 'x'})
            with self.assertRaisesRegex(ValueError, 'unpacked'):
                updater.download(self.release(bad), 'linux', root, opener=self.opener(bad))
            self.assertFalse((Path(tmp).parent / 'evil.txt').exists())

    def test_windows_zip(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as bundle:
            bundle.writestr('SkylandersPC.exe', 'exe');bundle.writestr('tools/launcher.py', 'new')
        payload = data.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            top = updater.download(self.release(payload, 'SkylandersPC-v9.0.0-windows.zip'), 'windows', tmp, opener=self.opener(payload))
            self.assertTrue((top / 'SkylandersPC.exe').is_file())
            script = []
            updater.apply_later('windows', tmp, pid=1234, popen=lambda *a, **k: script.append(a))
            text = (Path(tmp) / updater.STAGING / 'apply.cmd').read_bytes()
            self.assertIn(b'PID eq 1234', text);self.assertIn(b'\r\n', text);self.assertNotIn(b'\r\r', text)

    def test_linux_apply_replaces_release_files_only(self):
        payload = self.tarball({'tools/launcher.py': 'new', 'SkylandersPC.AppImage': ''})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);(root / 'tools').mkdir();(root / '.local/game-preparation').mkdir(parents=True)
            (root / 'tools/launcher.py').write_text('old');(root / 'tools/gone.py').write_text('old')
            (root / '.local/game-preparation/state.json').write_text('keep')
            (root / updater.MANIFEST).write_text(json.dumps(['tools/launcher.py', 'tools/gone.py']))
            updater.download(self.release(payload), 'linux', root, opener=self.opener(payload))
            updater.apply_later('linux', root, pid=2 ** 22 + 7, relaunch=False,
                                popen=lambda args, **k: subprocess.run(args, check=True, timeout=30))
            self.assertEqual((root / 'tools/launcher.py').read_text(), 'new')
            self.assertFalse((root / 'tools/gone.py').exists())
            self.assertEqual((root / '.local/game-preparation/state.json').read_text(), 'keep')
            self.assertFalse((root / updater.STAGING).exists())
            self.assertIn('SkylandersPC.AppImage', json.loads((root / updater.MANIFEST).read_text()))

    def test_git_refuses_dirty_tree(self):
        run = lambda args, **k: SimpleNamespace(returncode=0, stdout=' M tools/x.py\n', stderr='')
        with self.assertRaises(ValueError):updater.update_git('/repo', run)


if __name__ == '__main__':
    unittest.main()

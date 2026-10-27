# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('patches', Path(__file__).resolve().parents[1] / 'tools/patches.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PatchTests(unittest.TestCase):
    def test_malformed_manifest_is_rejected_cleanly(self):
        for malformed in (None, [], 'text', {'schema_version': True}):
            with self.subTest(manifest=malformed), self.assertRaises(ValueError):
                p.validate(b'anything', malformed)
        for entry in (None, [], 'patch', {'id': 'bad', 'kind': 'compatibility', 'reason': 'test',
                                        'file_offset': 0, 'expected_hex': None, 'replacement_hex': '00'}):
            manifest = copy.deepcopy(self.manifest)
            manifest['patches'] = [entry]
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                p.validate(self.data, manifest)

    def setUp(self):
        self.data = b'synthetic executable'
        self.manifest = {'schema_version': 1, 'title_id': 'TEST00000', 'app_version': '00.00',
                         'executable_sha256': hashlib.sha256(self.data).hexdigest(),
                         'patches': [{'id': 'synthetic', 'kind': 'compatibility', 'reason': 'test only',
                                      'file_offset': 0, 'expected_hex': '7379', 'replacement_hex': '5359'}]}

    def test_rejects_wrong_build_bytes_overlap_and_ranges(self):
        changes = [('executable_sha256', '0' * 64), ('expected_hex', '0000'),
                   ('file_offset', -1), ('file_offset', 100), ('file_offset', True),
                   ('replacement_hex', '00'), ('expected_hex', ''), ('kind', 'unknown')]
        for key, value in changes:
            manifest = copy.deepcopy(self.manifest)
            target = manifest if key == 'executable_sha256' else manifest['patches'][0]
            target[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                p.validate(self.data, manifest)
        manifest = copy.deepcopy(self.manifest)
        duplicate = dict(manifest['patches'][0], id='overlap')
        manifest['patches'].append(duplicate)
        with self.assertRaises(ValueError):
            p.validate(self.data, manifest)

    def test_dry_run_and_copy_never_modify_original(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'original'
            original.write_bytes(self.data)
            result = p.patch_copy(original, self.manifest)
            self.assertEqual(result['status'], 'validated; not applied')
            output = Path(directory) / 'working'
            p.patch_copy(original, self.manifest, output)
            self.assertEqual(output.read_bytes(), b'SYnthetic executable')
            self.assertEqual(original.read_bytes(), self.data)
            for target in (original, output):
                with self.assertRaises((ValueError, FileExistsError)):
                    p.patch_copy(original, self.manifest, target)
            self.assertEqual(original.read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()

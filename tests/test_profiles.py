# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('build_profiles', Path(__file__).resolve().parents[1] / 'tools/profiles.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.sha = hashlib.sha256(b'synthetic game').hexdigest()
        self.inventory = {'metadata': {'TITLE_ID': 'CUSA00000', 'APP_VER': '00.00'},
                          'executable': {'sha256': self.sha}}
        self.profile = {'schema_version': 1, 'id': 'test-game', 'title': 'Synthetic fixture',
                        'validated_builds': [{'id': 'fixture', 'title_id': 'CUSA00000',
                                              'app_version': '00.00', 'executable_sha256': self.sha}],
                        'patches': [], 'acceptance_cases': ['synthetic only']}

    def test_match_requires_metadata_and_exact_executable(self):
        report = p.identify_build(self.profile, self.inventory)
        self.assertEqual(report['status'], 'matched')
        self.assertEqual(report['build_id'], 'fixture')
        self.assertFalse(report['gameplay_verified'])
        for container, key, value in [('metadata', 'TITLE_ID', 'CUSA00001'),
                                      ('metadata', 'APP_VER', '00.01'),
                                      ('executable', 'sha256', '0' * 64)]:
            changed = copy.deepcopy(self.inventory)
            changed[container][key] = value
            result = p.identify_build(self.profile, changed)
            self.assertFalse(result['patches_allowed'])
            self.assertIsNone(result['build_id'])
        self.assertEqual(p.identify_build(self.profile, {})['status'], 'unverified')

    def test_empty_templates_remain_unverified_and_allow_unpatched_inventory(self):
        root = Path(__file__).resolve().parents[1] / 'profiles'
        for ident in ('trap-team', 'swap-force'):
            profile = p.load_profile(root, ident)
            report = p.identify_build(profile, self.inventory)
            self.assertEqual(report['status'], 'unverified')
            self.assertEqual(p.select_patches(profile, self.inventory), [])
            with self.assertRaises(ValueError):
                p.select_patches(profile, self.inventory, ['unknown'])

    def test_rejects_ambiguous_or_malformed_registry(self):
        for key, value in [('id', '../test'), ('schema_version', True), ('title', ''),
                           ('validated_builds', {}), ('acceptance_cases', [False])]:
            profile = copy.deepcopy(self.profile)
            profile[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                p.validate_profile(profile)
        profile = copy.deepcopy(self.profile)
        profile['validated_builds'].append(dict(profile['validated_builds'][0], id='duplicate'))
        with self.assertRaises(ValueError):
            p.validate_profile(profile)
        profile['validated_builds'][1]['executable_sha256'] = '0' * 64
        p.validate_profile(profile)
        profile['validated_builds'][1]['id'] = 'fixture'
        with self.assertRaises(ValueError):
            p.validate_profile(profile)

    def test_profile_filename_identity_and_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.json'
            path.write_text(json.dumps(self.profile))
            with self.assertRaises(ValueError):
                p.load_profile(directory, 'wrong')
            with self.assertRaises(ValueError):
                p.load_profile(directory, '../test-game')
            outside = Path(directory).parent / (Path(directory).name + '-outside.json')
            outside.write_text(json.dumps(self.profile))
            try:
                (Path(directory) / 'test-game.json').symlink_to(outside)
                with self.assertRaises(ValueError):
                    p.load_profile(directory, 'test-game')
            finally:
                outside.unlink()

    def manifest_fixture(self):
        manifest = {'schema_version': 1, 'title_id': 'CUSA00000', 'app_version': '00.00',
                    'executable_sha256': self.sha,
                    'patches': [{'id': 'byte', 'kind': 'compatibility', 'reason': 'synthetic only',
                                 'file_offset': 0, 'expected_hex': '00', 'replacement_hex': '01'}]}
        raw = (json.dumps(manifest) + '\n').encode()
        reference = {'id': 'fixture-patch', 'build_id': 'fixture', 'kind': 'compatibility',
                     'manifest': 'patches/fixture.json', 'manifest_sha256': hashlib.sha256(raw).hexdigest()}
        self.profile['patches'] = [reference]
        return manifest, raw, reference

    def test_patch_selection_is_explicit_and_build_scoped(self):
        self.manifest_fixture()
        self.assertEqual(p.select_patches(self.profile, self.inventory), [])
        selected = p.select_patches(self.profile, self.inventory, ['fixture-patch'])
        self.assertEqual(selected[0]['id'], 'fixture-patch')
        selected[0]['id'] = 'mutated'
        self.assertEqual(self.profile['patches'][0]['id'], 'fixture-patch')
        for request in (['unknown'], ['fixture-patch', 'fixture-patch'], '../fixture-patch'):
            with self.assertRaises(ValueError):
                p.select_patches(self.profile, self.inventory, request)
        inventory = copy.deepcopy(self.inventory)
        inventory['executable']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            p.select_patches(self.profile, inventory, ['fixture-patch'])

    def test_selected_manifest_hash_and_identity_are_checked(self):
        manifest, raw, reference = self.manifest_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / reference['manifest']
            path.parent.mkdir()
            path.write_bytes(raw)
            loaded = p.load_selected_patches(self.profile, self.inventory, ['fixture-patch'], root)
            self.assertEqual(loaded[0]['manifest'], manifest)
            path.write_bytes(raw + b' ')
            with self.assertRaises(ValueError):
                p.load_selected_patches(self.profile, self.inventory, ['fixture-patch'], root)
            manifest['title_id'] = 'CUSA00001'
            raw = json.dumps(manifest).encode()
            reference['manifest_sha256'] = hashlib.sha256(raw).hexdigest()
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                p.load_selected_patches(self.profile, self.inventory, ['fixture-patch'], root)

    def test_manifest_paths_cannot_escape_root(self):
        manifest, raw, reference = self.manifest_fixture()
        for invalid in ('../patch.json', '/tmp/patch.json', 'C:/patch.json', r'patches\patch.json'):
            reference['manifest'] = invalid
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                p.validate_profile(self.profile)
        reference['manifest'] = 'patches/fixture.json'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / (root.name + '-outside.json')
            outside.write_bytes(raw)
            try:
                (root / 'patches').mkdir()
                (root / reference['manifest']).symlink_to(outside)
                with self.assertRaises(ValueError):
                    p.load_selected_patches(self.profile, self.inventory, ['fixture-patch'], root)
            finally:
                outside.unlink()


if __name__ == '__main__':
    unittest.main()

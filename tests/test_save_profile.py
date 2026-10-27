# SPDX-License-Identifier: GPL-3.0-or-later
import json
import hashlib
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest
from tools import save_profile


class SaveProfileTests(unittest.TestCase):
    def test_default_and_title_specific_selection_leave_saves_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.assertEqual(save_profile.select(root, 'CUSA00626', environment={}), (save_profile.home_root({}), 'home-default'))
            save = root/'out/working-saves'
            (save/'CUSA00626').mkdir(parents=True)
            payload = save/'CUSA00626/Save_Header'
            payload.write_bytes(b'existing progress')
            profiles = root/'out/play-profiles';profiles.mkdir()
            (profiles/'CUSA00626.json').write_text(json.dumps(dict(
                schema_version=1, title_id='CUSA00626', save_root=str(save))))
            self.assertEqual(save_profile.select(root, 'CUSA00626', environment={}), (save, 'saved-profile'))
            self.assertEqual(save_profile.select(root, 'CUSA00016', environment={}), (save_profile.home_root({}), 'home-default'))
            self.assertEqual(payload.read_bytes(), b'existing progress')

    def test_large_save_verification_does_not_load_whole_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            payload=b'save-block'*300000
            (root/'large-save').write_bytes(payload)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('whole-file read')):
                manifest=save_profile._manifest(root)
            self.assertEqual(manifest,{'large-save':hashlib.sha256(payload).hexdigest()})

    def test_home_save_migration_preserves_progress_and_refuses_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root/'source'
            title = source/'CUSA00626'; title.mkdir(parents=True)
            (title/'Save_Header').write_bytes(b'discovery flags')
            (title/'Save_Slot1').write_bytes(b'progress')
            destination = save_profile.home_root({'HOME': str(root)})
            manifest = save_profile.migrate(source, destination, 'CUSA00626')
            self.assertEqual(save_profile._manifest(title), manifest)
            self.assertEqual(save_profile._manifest(destination/'CUSA00626'), manifest)
            self.assertEqual(save_profile.migrate(source, destination, 'CUSA00626'), manifest)
            (destination/'CUSA00626/Save_Slot1').write_bytes(b'newer progress')
            with self.assertRaises(ValueError):
                save_profile.migrate(source, destination, 'CUSA00626')
            self.assertEqual((destination/'CUSA00626/Save_Slot1').read_bytes(), b'newer progress')
            self.assertEqual(save_profile.home_root({'HOME':str(root), 'XDG_DATA_HOME':'relative'}), destination)
            self.assertEqual(save_profile.home_root({'XDG_DATA_HOME':str(root)}), root/'skylanders-pc/saves')

    def test_saved_home_profile_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            env={'XDG_DATA_HOME':str(root/'data')}
            destination=save_profile.home_root(env)
            (destination/'CUSA00626').mkdir(parents=True)
            profiles=root/'out/play-profiles';profiles.mkdir(parents=True)
            (profiles/'CUSA00626.json').write_text(json.dumps(dict(
                schema_version=1,title_id='CUSA00626',save_root=str(destination))))
            self.assertEqual(save_profile.select(root,'CUSA00626',environment=env),(destination,'saved-profile'))
            source=root/'source';(source/'CUSA00626').mkdir(parents=True)
            (source/'CUSA00626/link').symlink_to(root/'unrelated')
            with self.assertRaises(ValueError):
                save_profile.migrate(source,destination,'CUSA00626')

    def test_explicit_and_environment_overrides_precede_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve();profiles = root/'out/play-profiles';profiles.mkdir(parents=True)
            (profiles/'CUSA00626.json').write_text('invalid JSON')
            env = {'SKY_SAVE_DATA_ROOT': str(root/'environment')}
            self.assertEqual(save_profile.select(root, 'CUSA00626', root/'chosen', env),
                             (root/'chosen', 'command-line'))
            self.assertEqual(save_profile.select(root, 'CUSA00626', environment=env),
                             (root/'environment', 'environment'))

    def test_saved_profile_rejects_wrong_title_missing_directory_and_redirection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve();profiles = root/'out/play-profiles';profiles.mkdir(parents=True)
            actual = root/'out/actual';(actual/'CUSA00626').mkdir(parents=True)
            link = root/'out/linked';link.symlink_to(actual, target_is_directory=True)
            child_link = root/'out/child-link';child_link.mkdir()
            (child_link/'CUSA00626').symlink_to(actual/'CUSA00626', target_is_directory=True)
            for title, path in [('CUSA00016', actual), ('CUSA00626', root/'out/missing'),
                                ('CUSA00626', link), ('CUSA00626', child_link),
                                ('CUSA00626', root/'outside')]:
                (profiles/'CUSA00626.json').write_text(json.dumps(dict(
                    schema_version=1, title_id=title, save_root=str(path))))
                with self.subTest(title=title, path=path), self.assertRaises(ValueError):
                    save_profile.select(root, 'CUSA00626', environment={})
            with self.assertRaises(ValueError):
                save_profile.select(root, '../other', environment={})


if __name__ == '__main__':
    unittest.main()

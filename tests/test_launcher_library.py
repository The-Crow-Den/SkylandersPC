# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import launcher_library as library, launcher_packages as packages
from test_game_install import sfo


class LibraryTests(unittest.TestCase):
    def test_library_roundtrip_and_missing_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'library.json'
            value = library.defaults()
            value['games'][0]['settings'] = {'resolution':'2160p','fullscreen':True}
            library.save(path,value)
            self.assertEqual(library.load(path),value)
            value['selected']='removed';library.save(path,value)
            self.assertEqual(library.load(path)['selected'],'swap-force')

    def test_invalid_override_and_path_identifier_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'library.json'
            for bad in [{'resolution':'bad'}, {'fullscreen':'yes'}, {'extra':True}]:
                value=library.defaults();value['games'][0]['settings']=bad
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):library.load(path)
            value=library.defaults();value['games'][0]['id']='../outside'
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):library.load(path)


class PackageTests(unittest.TestCase):
    def make(self, staging, kind, category, ver, content='content'):
        root=staging/kind/'extracted';(root/'sce_sys').mkdir(parents=True)
        (root/'sce_sys/param.sfo').write_bytes(sfo(dict(TITLE_ID='CUSA00626',APP_VER=ver,CATEGORY=category,CONTENT_ID=content)))
        (root/'eboot.bin').write_bytes(b'synthetic')
        return root

    def test_matching_base_and_update_publish_to_discoverable_folders(self):
        from tools.game_install import discover
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staging=root/'import'
            self.make(staging,'base','gd','01.00');self.make(staging,'update','gp','01.01')
            paths=packages.publish(staging,root/'Game',True)
            self.assertEqual(len(paths),2)
            self.assertEqual(discover(root/'Game').app_version,'01.01')

    def test_wrong_update_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staging=root/'import'
            base=self.make(staging,'base','gd','01.00');self.make(staging,'update','gp','01.01','wrong')
            with self.assertRaisesRegex(ValueError,'Update'):packages.publish(staging,root/'Game',True)
            self.assertTrue(base.exists());self.assertFalse((root/'Game').exists())

    def test_existing_install_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staging=root/'import';base=self.make(staging,'base','gd','01.00')
            (base/'linked').symlink_to(base/'eboot.bin')
            with self.assertRaisesRegex(ValueError,'symlinks'):packages.publish(staging,root/'Game',True)
            (base/'linked').unlink()
            existing=root/'Game/existing/sce_sys';existing.mkdir(parents=True);(existing/'param.sfo').write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError,'already'):packages.publish(staging,root/'Game',True)
            self.assertTrue(base.exists());self.assertEqual((existing/'param.sfo').read_bytes(),b'existing')

    def test_second_move_failure_rolls_back_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staging=root/'import'
            base=self.make(staging,'base','gd','01.00');update=self.make(staging,'update','gp','01.01')
            real_move=packages.shutil.move
            def move(source,target):
                if source==str(update):raise OSError('synthetic publication failure')
                return real_move(source,target)
            with patch.object(packages.shutil,'move',side_effect=move):
                with self.assertRaises(OSError):packages.publish(staging,root/'Game',True)
            self.assertTrue(base.exists());self.assertTrue(update.exists())
            self.assertEqual(list((root/'Game').iterdir()),[])

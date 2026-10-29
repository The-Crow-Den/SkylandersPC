# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import launcher_library as library, launcher_packages as packages, game_library as installs
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
            entry=packages.publish(staging,installs.directory(root))
            self.assertTrue(Path(entry['base_path']).is_dir());self.assertTrue(Path(entry['update_path']).is_dir())
            self.assertEqual(discover(entry).app_version,'01.01')

    def test_wrong_update_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staging=root/'import'
            base=self.make(staging,'base','gd','01.00');self.make(staging,'update','gp','01.01','wrong')
            with self.assertRaisesRegex(ValueError,'Update'):packages.publish(staging,installs.directory(root))
            self.assertTrue(base.exists());self.assertEqual(installs.read_entries(installs.directory(root)),[])

    def test_existing_install_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staging=root/'import';base=self.make(staging,'base','gd','01.00')
            (base/'linked').symlink_to(base/'eboot.bin')
            with self.assertRaisesRegex(ValueError,'symlinks'):packages.publish(staging,installs.directory(root))
            (base/'linked').unlink()
            entry=packages.publish(staging,installs.directory(root))
            staging=root/'second';base=self.make(staging,'base','gd','01.00')
            with self.assertRaisesRegex(ValueError,'already'):packages.publish(staging,installs.directory(root))
            self.assertTrue(base.exists());self.assertEqual(Path(entry['base_path']).joinpath('eboot.bin').read_bytes(),b'synthetic')

    def test_second_move_failure_rolls_back_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);staging=root/'import'
            base=self.make(staging,'base','gd','01.00');update=self.make(staging,'update','gp','01.01')
            real_move=installs.shutil.move
            def move(source,target):
                if source==str(update):raise OSError('synthetic publication failure')
                return real_move(source,target)
            with patch.object(installs.shutil,'move',side_effect=move):
                with self.assertRaises(OSError):packages.publish(staging,installs.directory(root))
            self.assertTrue(base.exists());self.assertTrue(update.exists())
            self.assertEqual(installs.read_entries(installs.directory(root)),[])
            self.assertFalse((installs.directory(root)/'CUSA00626/01.00/base').exists())


class PackageSelectionTests(unittest.TestCase):
    def pkg(self, root, name, category, title='CUSA00626', content='content', version='01.00'):
        import struct
        data=sfo(dict(TITLE_ID=title,APP_VER=version,CATEGORY=category,CONTENT_ID=content))
        package=bytearray(0x3000);package[:4]=b'\x7fCNT'
        struct.pack_into('>I',package,0x10,1);struct.pack_into('>I',package,0x18,0x1000)
        struct.pack_into('>6IQ',package,0x1000,0x1000,0,0,0,0x1100,len(data),0)
        struct.pack_into('>QQ',package,0x410,0x2000,0x1000)
        struct.pack_into('>Q',package,0x430,len(package))
        package[0x1100:0x1100+len(data)]=data
        path=root/name;path.write_bytes(package);return path

    def test_reads_real_header_metadata_and_checks_both_choices_without_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=self.pkg(root,'game.pkg','gd');update=self.pkg(root,'update.pkg','gp',version='01.01')
            self.assertEqual(packages.package_info(base)['CATEGORY'],'gd')
            packages.check_packages(base,update)
            with self.assertRaisesRegex(ValueError,'looks like an update'):packages.check_packages(update,base)
            wrong=self.pkg(root,'wrong.pkg','gp',title='CUSA99999',version='01.01')
            with self.assertRaisesRegex(ValueError,'does not match'):packages.check_packages(base,wrong)
            with self.assertRaisesRegex(ValueError,'game first'):packages.check_packages(None,update)
            installed=[dict(title_id='CUSA00626',content_id='content',base_version='01.00')]
            packages.check_packages(None,update,installed)
            broken=root/'broken.pkg';broken.write_bytes(b'not a package')
            with self.assertRaisesRegex(ValueError,'complete PS4 PKG'):packages.package_info(broken)

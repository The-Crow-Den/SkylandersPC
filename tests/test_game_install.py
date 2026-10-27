# SPDX-License-Identifier: GPL-3.0-or-later
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from tools.game_install import discover
from tools.game_build import configuration, US_UPDATE_SHA256


def sfo(values):
    keys=bytearray(); data=bytearray(); entries=[]
    for name,value in values.items():
        encoded=value.encode()+b'\0'
        entries.append(struct.pack('<HHIII',len(keys),0x204,len(encoded),len(encoded),len(data)))
        keys.extend(name.encode()+b'\0');data.extend(encoded)
    start=20+len(entries)*16
    return struct.pack('<4s4I',b'\0PSF',0x101,start,start+len(keys),len(entries))+b''.join(entries)+keys+data


class InstallTests(unittest.TestCase):
    def make(self,root,name,category,ver,content='UP0002-CUSA00626_00-SKYLANDERSTRAPTE'):
        path=root/name;(path/'sce_sys').mkdir(parents=True)
        (path/'sce_sys/param.sfo').write_bytes(sfo(dict(TITLE_ID='CUSA00626',APP_VER=ver,CATEGORY=category,CONTENT_ID=content)))
        (path/'eboot.bin').write_bytes(name.encode())
        return path

    def test_update_wins_and_base_fallback_is_immutable(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'Game';base=self.make(root,'base','gd','01.00');update=self.make(root,'update','gp','01.01')
            (base/'unchanged').write_bytes(b'base-only');(update/'added').write_bytes(b'update-only')
            install=discover(root);out=install.materialize(Path(t)/'merged')
            self.assertEqual(install.app_version,'01.01')
            self.assertEqual(install.source('eboot.bin'),update/'eboot.bin')
            self.assertEqual((out/'eboot.bin').read_bytes(),b'update')
            self.assertEqual((out/'unchanged').read_bytes(),b'base-only')
            self.assertEqual((out/'added').read_bytes(),b'update-only')
            self.assertEqual((base/'eboot.bin').read_bytes(),b'base')
            self.assertEqual((out/'eboot.bin').stat().st_ino,(update/'eboot.bin').stat().st_ino)
            with self.assertRaises(ValueError):install.materialize(out)
            with self.assertRaises(ValueError):install.materialize(base/'bad')
            with self.assertRaises(ValueError):install.source('../escape')

    def test_wrong_content_id_and_duplicate_versions_refused(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.make(root,'base','gd','01.00');u=self.make(root,'update','gp','01.01','other')
            with self.assertRaisesRegex(ValueError,'content ID'):discover(root)
            (u/'sce_sys/param.sfo').write_bytes(sfo(dict(TITLE_ID='CUSA00626',APP_VER='01.01',CATEGORY='gp',CONTENT_ID='UP0002-CUSA00626_00-SKYLANDERSTRAPTE')))
            self.make(root,'duplicate','gp','01.01')
            with self.assertRaisesRegex(ValueError,'Ambiguous'):discover(root)

    def test_symlinks_refused_and_unknown_executable_has_no_profile(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'Game';base=self.make(root,'base','gd','01.00');install=discover(root)
            with self.assertRaisesRegex(ValueError,'profile'):configuration(Path(t),install,'60-delta')
            (base/'link').symlink_to(base/'eboot.bin')
            with self.assertRaisesRegex(ValueError,'symlinks'):install.materialize(Path(t)/'out')
            self.assertFalse((Path(t)/'out').exists())

    def test_identity_and_hash_are_both_required_for_update_profiles(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'Game';self.make(root,'base','gd','01.00');self.make(root,'update','gp','01.01');install=discover(root)
            with patch('tools.game_build.hashlib.sha256') as sha:
                sha.return_value.hexdigest.return_value=US_UPDATE_SHA256
                result=configuration(Path(t),install,'60-delta')
                self.assertEqual(result['pack'].name,'native-us-01.01-60-delta')
                self.assertEqual(result['level-events'].name,'trap-team-us-01.01-level-events.json')
            with self.assertRaises(ValueError):configuration(Path(t),install,'60-delta')

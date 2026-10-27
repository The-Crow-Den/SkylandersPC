# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from types import SimpleNamespace
import os
import struct
import tempfile
import unittest
from unittest.mock import patch
from tools import trophy_store,launcher_trophies

NPWR='NPWR12345_00'
XML=b'<trophyconf><title-name>Test</title-name><trophy id="0" ttype="B" gid="0"><name>First</name></trophy><trophy id="1" ttype="G" gid="2"><name>Extra</name></trophy></trophyconf>'

def archive(path,items):
    header=bytearray(96);header[:4]=b'\xdc\xa2M\0';struct.pack_into('>II',header,16,len(items),64)
    table=bytearray();payload=bytearray();offset=96+64*len(items)
    for name,data,flag in items:
        row=bytearray(64);row[:len(name)]=name.encode();struct.pack_into('>QQI',row,32,offset,len(data),flag)
        table+=row;payload+=data;offset+=len(data)
    path.write_bytes(header+table+payload)

class TrophyStoreTests(unittest.TestCase):
    def test_encryption_and_wrong_key(self):
        from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
        key=bytes(range(16));iv=bytes(range(16,32))
        encryptor=Cipher(algorithms.AES(key),modes.CBC(bytes(16))).encryptor();derived=encryptor.update(NPWR.encode().ljust(16,b'\0'))+encryptor.finalize()
        encryptor=Cipher(algorithms.AES(derived),modes.CBC(iv)).encryptor();plain=XML+bytes((-len(XML))%16)
        encoded=iv+encryptor.update(plain)+encryptor.finalize()
        self.assertEqual(trophy_store.decrypt_xml(encoded,key,NPWR),XML)
        with self.assertRaises(ValueError):trophy_store.decrypt_xml(encoded,bytes(16),NPWR)
        with self.assertRaises(ValueError):trophy_store.decrypt_xml(encoded[:-1],key,NPWR)
    def test_progress_survives_preparation_and_users_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_DATA_HOME':tmp}):
            root=Path(tmp);game=root/'game';(game/'sce_sys/trophy').mkdir(parents=True)
            archive(game/'sce_sys/trophy/trophy00.trp',[('TROP000.PNG',b'png0',0),('TROP001.PNG',b'png1',0)])
            (game/'sce_sys/npbind.dat').write_bytes(NPWR.encode());definition=root/'definition.xml';definition.write_bytes(XML)
            install=SimpleNamespace(base=game,title_id='CUSA00626',source=lambda name:game/name)
            with patch.object(launcher_trophies,'game_sources',return_value=(None,definition,None,None)):
                session=root/'session';session.mkdir();store=root/'store';result=trophy_store.prepare(root,install,session,store=store)
                self.assertTrue(result['available']);self.assertFalse(result['encrypted'])
                progress=store/'users/4096'/f'{NPWR}.xml';before=progress.read_bytes();progress.write_bytes(before.replace(b'unlockstate="false"',b'unlockstate="true"',1));saved=progress.read_bytes()
                again=root/'again';again.mkdir();trophy_store.prepare(root,install,again,store=store)
                self.assertEqual(progress.read_bytes(),saved)
                self.assertIn('0\t4\t0\t0\t1\t0\tFirst',(again/'trophies/4096.tsv').read_text())
                self.assertIn('1\t2\t2\t0\t0\t0\tExtra',(again/'trophies/4096.tsv').read_text())
                self.assertFalse(launcher_trophies.read_xml(store/'users/4097'/f'{NPWR}.xml')[1][0]['unlocked'])
                redirected=root/'redirected';redirected.mkdir();(redirected/'catalogues').symlink_to(store/'catalogues',target_is_directory=True)
                with self.assertRaises(ValueError):trophy_store.prepare(root,install,again,store=redirected)
    def test_archive_bounds_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'test.trp';archive(file,[('../escape',b'x',0)])
            with self.assertRaises(ValueError):trophy_store.entries(file)
            archive(file,[('TROP000.PNG',b'x',0)]);file.write_bytes(file.read_bytes()[:-1])
            with self.assertRaises(ValueError):trophy_store.entries(file)
    def test_private_key_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'private.toml';path.write_text('[Keys]\ntrophyKey="000102030405060708090a0b0c0d0e0f"\n')
            self.assertEqual(trophy_store.configured_key(path),bytes(range(16)))
            path.write_text('{"Keys":{"trophyKey":"000102030405060708090a0b0c0d0e0f"}}')
            self.assertEqual(trophy_store.configured_key(path),bytes(range(16)))
            path.write_text('0'*32)
            with self.assertRaises(ValueError):trophy_store.configured_key(path)

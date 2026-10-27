# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import struct
import tempfile
import unittest
from tools import launcher_trophies as trophies


def xml(title='Skylanders Trap Team',unlocked=False):
    return f'<trophyconf><title-name>{title}</title-name><trophy id="0" ttype="G" unlockstate="{str(unlocked).lower()}"><name>First steps</name><detail>Complete the first level.</detail></trophy><trophy id="1" ttype="B"><name>Collector</name><detail>Find a collectible.</detail></trophy></trophyconf>'


class TrophyTests(unittest.TestCase):
    def test_catalogue_never_counts_as_user_progress(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'definitions.xml';path.write_text(xml(unlocked=True))
            result=trophies.snapshot(root,dict(id='trap-team',name='Trap Team',trophy_definitions=str(path),trophies={'earned':99,'total':99}))
            self.assertEqual(result['total'],2);self.assertIsNone(result['percent'])
            self.assertTrue(all(row['unlocked'] is None for row in result['rows']))

    def test_real_user_xml_drives_locked_and_unlocked_states(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'user.xml';path.write_text(xml(unlocked=True))
            original=path.read_bytes()
            result=trophies.snapshot(root,dict(id='trap-team',name='Trap Team',trophy_progress=str(path)))
            self.assertEqual(result['percent'],50);self.assertEqual(result['earned'],1)
            self.assertFalse(result['rows'][1]['unlocked']);self.assertEqual(path.read_bytes(),original)

    def test_wrong_title_and_mismatched_catalogue_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);definitions=root/'definitions.xml';definitions.write_text(xml())
            progress=root/'user.xml';progress.write_text(xml('Other game',True))
            game=dict(id='trap-team',name='Trap Team',trophy_definitions=str(definitions),trophy_progress=str(progress))
            with self.assertRaisesRegex(ValueError,'match'):trophies.snapshot(root,game)
            with self.assertRaisesRegex(ValueError,'selected game'):trophies.snapshot(root,dict(id='swap-force',name='Swap Force',trophy_progress=str(definitions)))

    def test_title_punctuation_does_not_break_native_metadata_upgrade(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);definitions=root/'definitions.xml';progress=root/'NPWR12345_00.xml'
            definitions.write_text(xml('Skylanders™ Trap Team'))
            progress.write_text(xml('Skylanders Trap Team',True))
            game=dict(id='trap-team',name='Trap Team',trophy_definitions=str(definitions),trophy_progress=str(progress))
            self.assertEqual(trophies.snapshot(root,game)['earned'],1)

    def test_archive_catalogue_and_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'installed';directory=folder/'sce_sys/trophy';directory.mkdir(parents=True)
            path=directory/'trophy00.trp'
            header=bytearray(96);header[:4]=b'\xdc\xa2M\0';struct.pack_into('>II',header,16,1,64)
            entry=bytearray(64);entry[:11]=b'TROP000.PNG';struct.pack_into('>QQ',entry,32,160,4)
            path.write_bytes(header+entry+b'icon')
            result=trophies.snapshot(root,dict(id='custom',name='Custom',installed_paths=[str(folder)]))
            self.assertEqual(result['total'],1);self.assertIsNone(result['percent'])
            self.assertEqual(trophies.icon_bytes(result,0),b'icon')
            struct.pack_into('>QQ',entry,32,999999,4);path.write_bytes(header+entry+b'icon')
            with self.assertRaisesRegex(ValueError,'outside'):trophies.archive(path)

    def test_normal_save_and_entities_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'save.xml'
            for data in ('<save/>','<!DOCTYPE x><trophyconf/>','not xml'):
                path.write_text(data)
                with self.assertRaises(ValueError):trophies.read_xml(path)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic figure tags only: a made-up seed and generated identities."""
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from tools import figure_data as fd
from tools import figure_collection as fc

SEED = b'synthetic test seed, not the format seed'


def counter():
    values = itertools.count(1)
    return lambda n: bytes(next(values) & 0xff for _ in range(n))


def played(identity=14, variant=0, xp=(1500, 0, 0), gold=250, sequences=((5, 3), (4, 2)), nickname=''):
    """A tag in the shape the game leaves after play: both save areas, newest by sequence."""
    raw = bytearray(fd.blank(identity, variant, counter()))
    plain = bytearray(raw)
    for area, (header_sequence, extended_sequence) in zip(fd.AREAS, sequences):
        def put(block, offset, data):
            plain[(area + block) * 16 + offset:(area + block) * 16 + offset + len(data)] = data
        put(0, 0, xp[0].to_bytes(3, 'little')); put(0, 3, gold.to_bytes(2, 'little'))
        put(0, 5, (100 + header_sequence).to_bytes(4, 'little')); put(0, 9, bytes([header_sequence]))
        put(1, 6, b'\x01\x04'); put(5, 0, b'\x0b\x14\x1b\x0a\xea\x07')
        name = nickname.encode('utf-16le').ljust(32, b'\0'); put(2, 0, name[:16]); put(4, 0, name[16:])
        block = lambda i: bytes(plain[(area + i) * 16:(area + i) * 16 + 16])
        put(0, 12, fd.crc16(block(1) + block(2) + block(4)).to_bytes(2, 'little'))
        put(0, 10, fd.crc16(block(5) + block(6) + block(8) + bytes(0xe0)).to_bytes(2, 'little'))
        put(0, 14, fd.crc16(block(0)[:14] + b'\x05\x00').to_bytes(2, 'little'))
        put(9, 2, bytes([extended_sequence])); put(9, 3, xp[1].to_bytes(2, 'little')); put(9, 8, xp[2].to_bytes(3, 'little'))
        put(9, 0, fd.crc16(b'\x06\x01' + block(9)[2:] + block(10) + block(12) + block(13)).to_bytes(2, 'little'))
    for index in range(8, 64):
        if index % 4 != 3 and any(plain[index * 16:index * 16 + 16]):
            key = hashlib.md5(bytes(raw[:32]) + bytes([index]) + SEED).digest()
            raw[index * 16:index * 16 + 16] = Cipher(algorithms.AES(key), modes.ECB()).encryptor().update(bytes(plain[index * 16:index * 16 + 16]))
    return bytes(raw)


class FigureDataTests(unittest.TestCase):
    def test_blank_has_identity_and_is_not_editable(self):
        figure = fd.Figure(fd.blank(16, 0x2805, counter()), SEED)
        self.assertEqual((figure.identity, figure.variant, figure.kind), (16, 0x2805, 'character'))
        self.assertFalse(figure.editable)
        self.assertEqual(figure.to_bytes(), figure.raw)
        with self.assertRaises(fd.FigureError):
            figure.gold = 10

    def test_reads_newest_areas_and_preserves_unedited_bytes(self):
        raw = played(xp=(33000, 2000, 0), gold=1234, nickname='Splash')
        figure = fd.Figure(raw, SEED)
        self.assertEqual((figure.header, figure.extended), (0x08, 0x08))
        self.assertEqual((figure.xp, figure.level, figure.gold, figure.nickname), (35000, 10, 1234, 'Splash'))
        self.assertEqual(figure.to_bytes(), raw)

    def test_sequence_wraparound_selects_second_area(self):
        figure = fd.Figure(played(sequences=((255, 9), (0, 10))), SEED)
        self.assertEqual((figure.header, figure.extended), (0x24, 0x24))

    def test_edit_round_trip_touches_only_active_blocks(self):
        raw = played()
        figure = fd.Figure(raw, SEED)
        figure.nickname = 'Ember Fürst'; figure.gold = fd.MAX_GOLD; figure.level = 17
        edited = figure.to_bytes()
        again = fd.Figure(edited, SEED)
        self.assertEqual((again.nickname, again.gold, again.level, again.xp), ('Ember Fürst', 65000, 17, fd.LEVEL_XP[16]))
        changed = {b for b in range(64) if edited[b * 16:b * 16 + 16] != raw[b * 16:b * 16 + 16]}
        self.assertEqual(changed, {0x08, 0x0a, 0x0c, 0x11})
        self.assertEqual(again.seconds_played, fd.Figure(raw, SEED).seconds_played)
        again.level = 3
        self.assertEqual(fd.Figure(again.to_bytes(), SEED).xp, 2200)

    def test_experience_split_and_limits(self):
        figure = fd.Figure(played(), SEED)
        figure.xp = fd.MAX_XP
        result = fd.Figure(figure.to_bytes(), SEED)
        self.assertEqual((result.level, result._read(0x08, 0, 0, 3), result._read(0x08, 9, 3, 2), result._read(0x08, 9, 8, 3)),
                         (20, 33000, 63500, 101000))
        for setter, value in (('xp', fd.MAX_XP + 1), ('gold', fd.MAX_GOLD + 1), ('gold', -1), ('level', 21), ('nickname', 'x' * 16)):
            with self.assertRaises(fd.FigureError):
                setattr(figure, setter, value)

    def test_level_table(self):
        self.assertEqual([fd.level_for(fd.xp_for(level)) for level in range(1, 21)], list(range(1, 21)))
        self.assertEqual(fd.level_for(32999), 9)

    def test_rekey_keeps_progress_with_new_uid(self):
        raw = played(gold=777, nickname='Twin')
        copy = fd.rekey(raw, SEED, lambda n: b'\x10\x20\x30\x40'[:n])
        figure = fd.Figure(copy, SEED)
        self.assertNotEqual(copy[:4], raw[:4])
        self.assertEqual((figure.gold, figure.nickname, figure.xp), (777, 'Twin', 1500))

    def test_damaged_identity_is_refused(self):
        raw = bytearray(played()); raw[0x10] ^= 1
        with self.assertRaises(fd.FigureError):
            fd.Figure(bytes(raw), SEED)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.root = Path(self.temporary.name)
        (self.root / '.local/portal-assets').mkdir(parents=True)
        (self.root / '.local/portal-assets/trap-metadata.seed').write_bytes(SEED)
        (self.root / '.local/portal-assets/figure-names.json').write_text(json.dumps({'14:0': 'Gill Grunt', '16:0': 'Spyro', '230:0': 'Hand of Fate'}))
        self.collection = fc.Collection(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_working_copy_is_the_edited_save(self):
        library = played(gold=10)
        path = self.collection.characters / 'created-abc.sky'; path.parent.mkdir(parents=True); path.write_bytes(library)
        working = self.collection.figures / f'import-{fc.fnv1a64(library):016x}.sky'; working.parent.mkdir(parents=True)
        working.write_bytes(played(gold=500))
        entry, = self.collection.entries()
        self.assertEqual((entry.name, entry.figure.gold, entry.working), ('Gill Grunt', 500, working))
        figure = fd.Figure(entry.figure.raw, SEED); figure.gold = 900
        saved = self.collection.save(entry, figure.to_bytes())
        self.assertEqual(saved.figure.gold, 900)
        self.assertEqual(path.read_bytes(), library)
        self.assertEqual(fd.Figure(next(self.collection.backups.glob('*.sky')).read_bytes(), SEED).gold, 500)

    def test_create_import_duplicate_and_remove(self):
        created = self.collection.create(16, 0)
        self.assertEqual((created.name, created.figure.editable), ('Spyro', False))
        with self.assertRaises(fd.FigureError):
            self.collection.create(211, 0)
        dump = self.root / 'dump.sky'; dump.write_bytes(played(gold=42))
        imported = self.collection.import_dump(dump)
        self.assertEqual(self.collection.import_dump(dump).path, imported.path)
        copy = self.collection.duplicate(imported)
        self.assertEqual(copy.figure.gold, 42); self.assertNotEqual(copy.figure.raw[:4], imported.figure.raw[:4])
        # The native importer's identical copy of a created tag is listed once.
        twin = self.collection.characters / f'{fc.fnv1a64(created.path.read_bytes()):016x}.sky'
        twin.write_bytes(created.path.read_bytes())
        self.assertEqual(len(self.collection.entries()), 3)
        folder = self.collection.remove(created)
        self.assertFalse(created.path.exists()); self.assertFalse(twin.exists())
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([created.path.name, twin.name]))
        self.assertEqual(len(self.collection.entries()), 2)

    def test_names_are_read_from_portal_sources(self):
        (self.root / '.local/portal-assets/figure-names.json').unlink()
        source = self.root / 'wiiu'
        cpp = source / 'Cemu-main/src/Cafe/OS/libs/nsyshid/Skylander.cpp'; cpp.parent.mkdir(parents=True)
        cpp.write_text('{{0, 0x0000}, "Whirlwind"},\n{{16, 0x1801}, "Series 2 Spyro"},\n{{211, 0x3001}, "Water Trap"},')
        (self.root / '.local/native-gpu-build').mkdir(parents=True)
        (self.root / '.local/native-gpu-build/CMakeCache.txt').write_text(f'SKY_PORTAL_SOURCE_ROOT:PATH={source}\n')
        collection = fc.Collection(self.root)
        self.assertEqual(collection.names[(16, 0x1801)], 'Series 2 Spyro')
        self.assertEqual([c[0] for c in collection.choices()], ['Series 2 Spyro', 'Whirlwind'])
        self.assertTrue((self.root / '.local/portal-assets/figure-names.json').is_file())


if __name__ == '__main__':
    unittest.main()

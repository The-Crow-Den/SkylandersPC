# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import game_portraits


def texture(colour):
    """A synthetic 192x192 BC3 texture: opaque alpha, one RGB565 colour."""
    sections = 0x30
    header = bytearray(sections + 0x120); struct.pack_into('<I', header, 0x28, sections)
    struct.pack_into('<HH', header, sections + 0x110, 192, 192)
    block = bytes((255, 255, 0, 0, 0, 0, 0, 0)) + struct.pack('<HHI', colour, colour, 0)
    return bytes(header) + block * (48 * 48)


def archive(members):
    names = b''.join(name.encode() + b'\0' for name, _ in members)
    count = len(members); headers = 0x38 + 4 * count; table = headers + 16 * count
    data = bytearray(table); data[:4] = b'IGA\x1a'
    struct.pack_into('<II', data, 0x0C, count, 0x800); struct.pack_into('<Q', data, 0x28, table)
    offsets = b''; at = 0
    for name, _ in members:offsets += struct.pack('<I', 4 * count + at); at += len(name) + 1
    data += offsets + names
    for i, (_, body) in enumerate(members):
        struct.pack_into('<IIII', data, headers + 16 * i, len(data), 0, len(body), 0xFFFFFFFF); data += body
    return bytes(data)


class GamePortraitTests(unittest.TestCase):
    def test_collection_pictures_become_cached_portraits(self):
        red = 0xF800
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp)/'game'; (game/'misc').mkdir(parents=True)
            prefix = 'C:/tfb/build/ps4/ui_sky4/collection_images/'
            (game/'misc/ui_collection_champions.arc').write_bytes(archive([
                (prefix + '2011/30_0_chopchop.png/0x614506a5.png.igb.tex.igz', texture(red)),
                (prefix + 'readme.txt', b'not a portrait')]))
            (game/'misc/ui_collection_traps.arc').write_bytes(archive([
                (prefix + 'traps/216_12291.png/0x1.png.igb.tex.igz', texture(red))]))
            index = game_portraits.prepare(Path(temp)/'out', [Path(temp)/'missing-update', game])
            self.assertEqual(index, {'30:0': '30_0.png', '216:12291': '216_12291.png'})
            png = (Path(temp)/'out/30_0.png').read_bytes()
            width, height = struct.unpack('>II', png[16:24]); self.assertEqual((width, height), (96, 96))
            raw = zlib.decompress(png[png.index(b'IDAT') + 4:png.index(b'IEND') - 8])
            self.assertEqual(raw[1:5], bytes((255, 0, 0, 255)))
            saved = json.loads((Path(temp)/'out/index.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['portraits'], index)

    def test_portal_atlas_gets_game_pictures_and_keeps_villains(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp)/'assets'; (assets/'game').mkdir(parents=True)
            red = bytes((255, 0, 0, 255)) * 96
            (assets/'game/30_0.png').write_bytes(game_portraits.png([red] * 96))
            (assets/'game/2011_0.png').write_bytes(game_portraits.png([red] * 96))
            (assets/'game/index.json').write_text(json.dumps(dict(schema_version=2, portraits={'30:0': '30_0.png', '2011:0': '2011_0.png'})), encoding='utf-8')
            width, height = 16 * 96, 20 * 96; atlas = bytearray(width * height * 4)
            atlas[0:4] = b'\x01\x02\x03\xff'                       # villain cell 0
            atlas[(302 % 16) * 384:(302 % 16) * 384 + 4] = b'\x09\x09\x09\xff'  # element icon at cell 302 (row 18)
            at = 18 * 96 * width * 4 + (302 % 16) * 384; atlas[at:at + 4] = b'\x07\x07\x07\xff'
            (assets/'portraits.rgba').write_bytes(struct.pack('<II', width, height) + bytes(atlas))
            (assets/'element-index.txt').write_text('0 302\n', encoding='utf-8')
            (assets/'sources.json').write_text(json.dumps(dict(sources=[dict(cell=0, kind='villain', cache='00.image'),
                dict(cell=302, kind='element', cache='e.image'), dict(cell=100, kind='figure', cache='old.image')])), encoding='utf-8')
            self.assertTrue(game_portraits.install(assets)); self.assertFalse(game_portraits.install(assets))
            data = (assets/'portraits.rgba').read_bytes(); w, h = struct.unpack_from('<II', data)
            self.assertEqual(data[8:12], b'\x01\x02\x03\xff')
            self.assertEqual((assets/'element-index.txt').read_text(encoding='utf-8'), '0 1\n')
            self.assertEqual(data[8 + 384:8 + 388], b'\x07\x07\x07\xff')
            cell = lambda c: data[8 + (c // 16) * 96 * w * 4 + (c % 16) * 384:][:4]
            lines = (assets/'portrait-index.txt').read_text(encoding='utf-8').split('\n')
            self.assertEqual(lines[0], f'SKYPORTRAITS1 16 {h // 96}')
            entries = {tuple(map(int, l.split()[:2])): int(l.split()[2]) for l in lines[1:] if l}
            self.assertEqual(entries[(30, 0)], 64); self.assertEqual(entries[(1011, 0)], entries[(2011, 0)])
            self.assertEqual(cell(64), bytes((255, 0, 0, 255)))
            kinds = sorted(s['kind'] for s in json.loads((assets/'sources.json').read_text(encoding='utf-8'))['sources'])
            self.assertEqual(kinds, ['element', 'figure', 'figure', 'villain'])

    def test_unknown_archives_are_refused(self):
        with self.assertRaises(ValueError):list(game_portraits.members(b'NOPE' + bytes(64)))


if __name__ == '__main__':
    unittest.main()

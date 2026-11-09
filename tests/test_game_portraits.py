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
            saved = json.loads((Path(temp)/'out/index.json').read_text())
            self.assertEqual(saved['portraits'], index)

    def test_unknown_archives_are_refused(self):
        with self.assertRaises(ValueError):list(game_portraits.members(b'NOPE' + bytes(64)))


if __name__ == '__main__':
    unittest.main()

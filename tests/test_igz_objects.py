# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import igz_objects

BASE = 0x1000


def pack(offsets):
    """The packed offset format igz_objects reads (offset = previous + 4*(value+1))."""
    nibbles, previous = [], 0
    for offset in offsets:
        value = (offset - previous) // 4 - 1
        previous = offset
        while True:
            part, value = value & 7, value >> 3
            nibbles.append(part | (8 if value else 0))
            if not value:
                break
    if len(nibbles) % 2:
        nibbles.append(0)
    return bytes(nibbles[i] | nibbles[i + 1] << 4 for i in range(0, len(nibbles), 2))


def chunk(tag, count, payload):
    size = (16 + len(payload) + 3) // 4 * 4
    return struct.pack('<4sIII', tag, count, size, 16) + payload + bytes(size - 16 - len(payload))


def igz(objects, pointers):
    """objects: [(size, type, {field offset: pointer value})]; pointers: list of (object index, field)."""
    body, starts = bytearray(8), []  # the first object follows an 8-byte header
    for size, kind, fields in objects:
        starts.append(len(body))
        item = bytearray(size);struct.pack_into('<Q', item, 0, kind)
        for field, value in fields.items():
            struct.pack_into('<Q', item, field, value)
        body += item
    rofs = sorted(starts[index] + field for index, field in pointers)
    fixups = chunk(b'RVTB', len(starts), pack(starts)) + chunk(b'ROFS', len(rofs), pack(rofs)) + chunk(b'ROOT', 1, bytes(4))
    head = bytearray(0x800);head[:4] = igz_objects.MAGIC
    struct.pack_into('<II', head, 0x28, BASE, len(body))
    data = head + fixups
    return bytes(data + bytes(BASE - len(data)) + body), starts


class IgzObjectTests(unittest.TestCase):
    def test_offsets_round_trip(self):
        offsets = [8, 16, 0x72cc, 0x733c, 0x10000]
        self.assertEqual(igz_objects._unpack(pack(offsets), len(offsets)), offsets)

    def test_pointer_follows_its_object_past_an_extra_object(self):
        # The other copy has one more (language) object early on, shifting the rest.
        common = [(0x40, 3, {}), (0x30, 5, {})]
        later = [(0x20, 7, {}), (0x28, 9, {8: 0})]
        source, s_starts = igz(common + later, [(3, 8)])
        target, t_starts = igz(common[:1] + [(0x50, 11, {})] + common[1:] + later, [(4, 8)])
        translate = igz_objects.Translator(source, target)
        # Inside the third common object, at +0x10.
        self.assertEqual(translate(s_starts[2] + 0x10), t_starts[3] + 0x10)
        self.assertIn(s_starts[3] + 8, translate.pointers)
        self.assertIn(t_starts[4] + 8, translate.target_pointers)
        self.assertIsNone(translate(10 ** 6))

    def test_fixups_follow_the_objects(self):
        # The edit points a plain field at another object and renames a string; the
        # other copy has an extra object, so the new pointer field sits elsewhere.
        def build(objects, pointers, strings, room=0x40):
            body, starts = bytearray(8), []
            for size, kind, fields in objects:
                starts.append(len(body))
                item = bytearray(size);struct.pack_into('<Q', item, 0, kind)
                for field, value in fields.items():
                    struct.pack_into('<Q', item, field, value)
                body += item
            rofs = sorted(starts[index] + field for index, field in pointers)
            text = igz_objects._encode_strings(strings) + bytes(room)
            fixups = chunk(b'TSTR', len(strings), text) + chunk(b'RVTB', len(starts), pack(starts)) + \
                chunk(b'ROFS', len(rofs), pack(rofs)) + chunk(b'ROOT', 1, bytes(4))
            head = bytearray(0x800);head[:4] = igz_objects.MAGIC
            struct.pack_into('<II', head, 0x28, 0x800 + len(fixups), len(body))
            return bytes(head + fixups + body), starts
        common = [(0x40, 3, {}), (0x30, 5, {})]
        later = [(0x20, 7, {}), (0x28, 9, {})]
        source, s_starts = build(common + later, [(3, 8)], [b'Hurt Location', b'ab'])
        edited, _ = build(common + later, [(3, 8), (2, 8)], [b'hurt giver', b'ab'], room=0x42)
        target, t_starts = build(common[:1] + [(0x50, 11, {})] + common[1:] + later, [(4, 8)],
                                 [b'Hurt Location', b'ab'])
        translate = igz_objects.Translator(source, target)
        head = igz_objects.port_fixups(source, edited, target, translate)
        start = struct.unpack_from('<I', target, 0x28)[0]
        self.assertEqual(len(head), start)
        result = head + target[start:]
        self.assertEqual(igz_objects.pointer_fields(result), {t_starts[4] + 8, t_starts[3] + 8})
        tag, count, extra, payload = igz_objects._layout(result)[0]
        self.assertEqual(igz_objects._strings(payload, count), [b'hurt giver', b'ab'])

    def test_fixups_refuse_unmatched_entries(self):
        source, _ = igz([(0x40, 3, {})], [])
        edited, _ = igz([(0x40, 3, {})], [(0, 0x18)])
        target, _ = igz([(0x50, 4, {})], [])
        with self.assertRaises(ValueError):
            igz_objects.port_fixups(source, edited, target, igz_objects.Translator(source, target))

    def test_refuses_other_files(self):
        with self.assertRaises(ValueError):
            igz_objects.objects(b'IGA\x1a' + bytes(100))


if __name__ == '__main__':
    unittest.main()

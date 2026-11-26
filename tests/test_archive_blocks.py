# SPDX-License-Identifier: GPL-3.0-or-later
import json
import lzma
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import archive_blocks
import asset_mod
import mod_manifest

ALIGN = 0x800
PROPS = bytes.fromhex('5d00800000')


def compress(plain):
    filters = [dict(id=lzma.FILTER_LZMA1, dict_size=0x8000, lc=3, lp=0, pb=2)]
    return lzma.compress(plain, format=lzma.FORMAT_RAW, filters=filters)


def archive(members, pad=0):
    """A small IGA archive of raw-LZMA members; pad shifts every member, like a repack."""
    count = len(members)
    names = b''.join(name.encode() + b'\0' for name, _ in members)
    table = 0x38 + 4 * count + 16 * count
    header_end = table + 4 * count + len(names)
    at = (header_end + pad + ALIGN - 1) // ALIGN * ALIGN
    body, entries = bytearray(), []
    for name, plain in members:
        entries.append((at, len(plain)))
        for start in range(0, len(plain), archive_blocks.BLOCK):
            stream = compress(plain[start:start + archive_blocks.BLOCK])
            block = struct.pack('<H', len(stream)) + PROPS + stream
            block += bytes(-len(block) % ALIGN)
            body += block;at += len(block)
    data = bytearray(b'IGA\x1a' + struct.pack('<I', 0x0B) + bytes(4) + struct.pack('<II', count, ALIGN))
    data += bytes(0x28 - len(data)) + struct.pack('<Q', table) + bytes(0x38 - 0x30)
    data += bytes(4 * count)
    for offset, size in entries:
        data += struct.pack('<IIII', offset, 0, size, 0x20000000)
    position = 4 * count
    for name, _ in members:
        data += struct.pack('<I', position);position += len(name) + 1
    data += names
    first = (header_end + pad + ALIGN - 1) // ALIGN * ALIGN
    data += bytes(first - len(data))
    return bytes(data + body)


def member(pointer, shift=0):
    """Two 32 KiB blocks of varied data: a marked field, and the value elsewhere."""
    plain = bytearray(bytes(range(256)) * 256)
    plain[0x100:0x110] = b'MARK' + struct.pack('<I', 0x1111 + shift) + b'\xaa' * 8        # field to change
    plain[0x9000:0x9010] = b'SRC!' + struct.pack('<Q', pointer) + b'\xbb' * 4         # value to copy
    return bytes(plain)


EDIT = dict(member='a.bin', find_hex='4d41524b ???????? aaaaaaaaaaaaaaaa', at=8, length=8,
            copy=dict(member='a.bin', find_hex='53524321 ???????????????? bbbbbbbb', at=4))


class ArchiveBlockTests(unittest.TestCase):
    def test_blocks_decode_every_member(self):
        data = archive([('a.bin', member(7)), ('b.bin', b'tail' * 10)])
        found = list(archive_blocks.blocks(data))
        self.assertEqual([(b['member'], b['member_offset']) for b in found], [('a.bin', 0), ('a.bin', 0x8000), ('b.bin', 0)])
        self.assertEqual(b''.join(b['plain'] for b in found[:2]), member(7))

    def test_one_portable_edit_fits_two_builds(self):
        # The second build moves the data and its pointer and changes an unrelated value.
        for pad, pointer, shift in ((0, 0x1234, 0), (0x1800, 0x5678, 3)):
            with self.subTest(pad=pad):
                data = archive([('a.bin', member(pointer, shift))], pad=pad)
                recipe = archive_blocks.resolve(data, 'x.arc', [EDIT])
                patched, _ = asset_mod.patch_asset(data, recipe)
                plain = b''.join(b['plain'] for b in archive_blocks.blocks(patched))
                self.assertEqual(plain[0x108:0x110], struct.pack('<Q', pointer))
                self.assertEqual(plain[:0x108] + plain[0x110:], member(pointer, shift)[:0x108] + member(pointer, shift)[0x110:])

    def test_literal_replacement_and_expected_bytes(self):
        data = archive([('a.bin', member(1))])
        recipe = archive_blocks.resolve(data, 'x.arc', [dict(find_hex='4d41524b', at=0, replacement_hex='4e4f5045')])
        edit = recipe['chunks'][0]['edits'][0]
        self.assertEqual((edit['offset'], edit['expected_hex'], edit['replacement_hex']), (0x100, '4d41524b', '4e4f5045'))

    def test_refuses_missing_repeated_and_unsafe_edits(self):
        data = archive([('a.bin', member(1))])
        cases = {'not found': dict(find_hex='deadbeefdeadbeef', replacement_hex='00'),
                 r'found \d+ times': dict(find_hex='00010203', replacement_hex='ff'),
                 'wildcards': dict(find_hex='4d41524b????', at=4, replacement_hex='0000'),
                 'inside its find_hex': dict(find_hex='4d41', at=1, replacement_hex='0000'),
                 'already have the new value': dict(find_hex='4d41524b', replacement_hex='4d41524b'),
                 'exactly one of': dict(find_hex='4d41524b'),
                 'unknown fields': dict(find_hex='4d41524b', replacement_hex='00', offset=3)}
        for message, edit in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                archive_blocks.resolve(data, 'x.arc', [edit])

    def test_member_limits_where_an_edit_matches(self):
        data = archive([('a.bin', member(1)), ('b.bin', b'MARK' + b'\0' * 60)])
        with self.assertRaisesRegex(ValueError, 'found 2 times'):
            archive_blocks.resolve(data, 'x.arc', [dict(find_hex='4d41524b', replacement_hex='00')])
        recipe = archive_blocks.resolve(data, 'x.arc', [dict(member='b.bin', find_hex='4d41524b', replacement_hex='00')])
        self.assertEqual(len(recipe['chunks']), 1)

    def test_mod_plan_resolves_against_the_installed_file(self):
        build = 'ab' * 32
        manifest = mod_manifest.parse(dict(schema_version=1, id='demo', name='Demo', version='1', author='me', licence='MIT',
                                           targets=[dict(title_id='CUSA00001', app_version='01.00', executable_sha256=build)],
                                           operations=[dict(type='asset-find', asset='data/x.arc', edits=[EDIT])]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.arc';path.write_bytes(archive([('a.bin', member(0x42))], pad=0x800))
            cache = Path(folder) / 'cache'
            for _ in range(2):  # the second plan reads the cached recipe
                applied = mod_manifest.plan({'demo': manifest}, ['demo'], build, asset_source=lambda relative: path, find_cache=cache)
                profile = mod_manifest.asset_profile(applied, 'CUSA00001', '01.00', build)
                self.assertEqual(profile['assets'][0]['asset'], 'data/x.arc')
                self.assertEqual(len(list(cache.glob('*.json'))), 1)
            patched, _ = asset_mod.patch_asset(path.read_bytes(), profile['assets'][0])
            self.assertIn(struct.pack('<Q', 0x42), b''.join(b['plain'] for b in archive_blocks.blocks(patched))[0x100:0x110])
            self.assertEqual(mod_manifest.record(applied)[0]['operations'], [dict(type='asset-find', assets=['data/x.arc'], edits=1)])
        with self.assertRaisesRegex(mod_manifest.ModError, 'original game files'):
            mod_manifest.plan({'demo': manifest}, ['demo'], build)

    def test_manifest_checks_portable_edits(self):
        base = dict(schema_version=1, id='demo', name='Demo', version='1', author='me', licence='MIT',
                    targets=[dict(title_id='CUSA00001', app_version='01.00', executable_sha256='ab' * 32)])
        with self.assertRaisesRegex(mod_manifest.ModError, 'edit 0'):
            mod_manifest.parse(dict(base, operations=[dict(type='asset-find', asset='x.arc', edits=[dict(find_hex='zz', replacement_hex='00')])]))
        with self.assertRaisesRegex(mod_manifest.ModError, 'asset path'):
            mod_manifest.parse(dict(base, operations=[dict(type='asset-find', asset='../x.arc', edits=[EDIT])]))


if __name__ == '__main__':
    unittest.main()

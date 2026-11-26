# SPDX-License-Identifier: GPL-3.0-or-later
import random
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_blocks
import asset_mod
import make_mod
from test_archive_blocks import archive

# Two records hold pointers; a field of the first is what the mod changes. A second
# build moves both records and shifts every pointer, as an update repack does.
FIELD, SOURCE = 0x2004, 0x5004


def build(shift):
    rng = random.Random(7)
    plain = bytearray(rng.randbytes(0x8000))
    # A field holding a pointer, then a fixed tag the edit is found by.
    plain[FIELD - 8:FIELD + 24] = struct.pack('<QQ', 0x41000 + shift, 0x24e28) + b'FIELDTAG' + bytes(8)
    # Where the game already holds the value the mod wants.
    plain[SOURCE - 8:SOURCE + 24] = struct.pack('<QQ', 0x52000 + shift, 0x6c4d8 + shift) + b'SRCTAG!!' + bytes(8)
    return bytes(plain)


def plain_of(data):
    return b''.join(block['plain'] for block in archive_blocks.blocks(data))


class MakeModTests(unittest.TestCase):
    def test_runs_join_small_gaps_and_split_at_blocks(self):
        original = bytes(0x10010)
        edited = bytearray(original)
        edited[10] = edited[14] = 1          # one run: the gap is small
        edited[40] = 1                      # its own run
        edited[0x7ffe:0x8002] = b'\1' * 4   # crosses a block boundary
        self.assertEqual(make_mod.runs(original, bytes(edited)), [(10, 15), (40, 41), (0x7ffe, 0x8000), (0x8000, 0x8002)])

    def test_changed_pointer_is_copied_per_build(self):
        first, second = archive([('a.bin', build(0))]), archive([('a.bin', build(0x68))], pad=0x800)
        edited = bytearray(build(0))
        edited[FIELD:FIELD + 8] = struct.pack('<Q', 0x6c4d8)  # the author points the field at the source value
        edits, fitting = make_mod.portable_edits(first, [second], {'a.bin': bytes(edited)})
        self.assertEqual(fitting, [True])
        self.assertIn('copy', edits[0])
        for data, shift in ((first, 0), (second, 0x68)):
            recipe = archive_blocks.resolve(data, 'x.arc', edits)
            patched = plain_of(asset_mod.patch_asset(data, recipe)[0])
            # Each build gets its own pointer, not the one from the build that was edited.
            self.assertEqual(struct.unpack_from('<Q', patched, FIELD)[0], 0x6c4d8 + shift)
            expected = bytearray(build(shift));expected[FIELD:FIELD + 8] = struct.pack('<Q', 0x6c4d8 + shift)
            self.assertEqual(patched, bytes(expected))

    def test_literal_change_fits_a_build_with_moved_pointers(self):
        first, second = archive([('a.bin', build(0))]), archive([('a.bin', build(0x68))])
        edited = bytearray(build(0));edited[FIELD + 8:FIELD + 13] = b'MODDED'[:5]
        edits, fitting = make_mod.portable_edits(first, [second], {'a.bin': bytes(edited)})
        self.assertEqual(fitting, [True])
        self.assertEqual(edits[0]['replacement_hex'], b'MODDE'.hex())

    def test_build_with_different_bytes_is_reported(self):
        changed = bytearray(build(0x68));changed[FIELD:FIELD + 8] = struct.pack('<Q', 0x99999)
        first, second = archive([('a.bin', build(0))]), archive([('a.bin', bytes(changed))])
        edited = bytearray(build(0));edited[FIELD:FIELD + 8] = struct.pack('<Q', 0x6c4d8)
        self.assertEqual(make_mod.portable_edits(first, [second], {'a.bin': bytes(edited)})[1], [False])

    def test_port_moves_identical_blocks(self):
        source, target = archive([('a.bin', build(0))]), archive([('a.bin', build(0))], pad=0x1800)
        recipe = archive_blocks.resolve(source, 'x.arc', [dict(member='a.bin', find_hex=b'FIELDTAG'.hex(), replacement_hex=b'NEWTAG!!'.hex())])
        ported, how = make_mod.port_asset(recipe, source, target)
        self.assertEqual(how, 'identical blocks')
        self.assertNotEqual(ported['chunks'][0]['offset'], recipe['chunks'][0]['offset'])
        self.assertIn(b'NEWTAG!!', plain_of(asset_mod.patch_asset(target, ported)[0]))
        self.assertEqual(make_mod.port_asset(recipe, source, source), (recipe, 'same archive'))

    def test_port_relocates_a_moved_pointer(self):
        # The field's old pointer differs per build; the new value is the same in both.
        def variant(shift):
            plain = bytearray(build(shift))
            plain[FIELD:FIELD + 8] = struct.pack('<Q', 0x24e28 + shift)
            plain[0x7000:0x7008] = struct.pack('<Q', 0xadd60)
            return bytes(plain)
        source, target = archive([('a.bin', variant(0))]), archive([('a.bin', variant(0x60))])
        recipe = archive_blocks.resolve(source, 'x.arc', [dict(member='a.bin', find_hex=b'FIELDTAG'.hex() , replacement_hex='00')])
        recipe['chunks'][0]['edits'] = [dict(offset=FIELD, expected_hex=struct.pack('<Q', 0x24e28).hex(),
                                             replacement_hex=struct.pack('<Q', 0xadd60).hex())]
        ported, how = make_mod.port_asset(recipe, source, target)
        self.assertTrue(how.startswith('relocated'))
        edit = ported['chunks'][0]['edits'][0]
        self.assertEqual(bytes.fromhex(edit['expected_hex'])[:3], struct.pack('<Q', 0x24e28 + 0x60)[:3])
        patched = plain_of(asset_mod.patch_asset(target, ported)[0])
        self.assertEqual(struct.unpack_from('<Q', patched, FIELD)[0], 0xadd60)
        # A new pointer that does not exist in the other build is refused, never invented.
        recipe['chunks'][0]['edits'][0]['replacement_hex'] = struct.pack('<Q', 0xbeef00).hex()
        with self.assertRaisesRegex(ValueError, 'does not occur'):
            make_mod.port_asset(recipe, source, target)

    def test_refusals(self):
        data = archive([('a.bin', build(0))])
        with self.assertRaisesRegex(ValueError, 'changed size'):
            make_mod.portable_edits(data, [], {'a.bin': build(0) + b'x'})
        with self.assertRaisesRegex(ValueError, 'No changes'):
            make_mod.portable_edits(data, [], {'a.bin': build(0)})
        with self.assertRaisesRegex(ValueError, 'not in this archive'):
            make_mod.portable_edits(data, [], {'b.bin': b''})

    def test_member_names_become_safe_paths(self):
        self.assertEqual(str(make_mod.safe_name('c:\\temp/a//b.igz')), 'c_/temp/a/b.igz')
        for bad in ('..', '/', 'a/../b'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make_mod.safe_name(bad)


if __name__ == '__main__':
    unittest.main()

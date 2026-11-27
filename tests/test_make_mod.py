# SPDX-License-Identifier: GPL-3.0-or-later
import random
from pathlib import Path
import struct
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_blocks
import asset_mod
import make_mod
import mod_manifest
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
        # A game data file (IGZ, object section at 0): the field's old pointer and the
        # object the new pointer names both sit 0x60 later in the other build.
        def variant(shift, moved=True):
            plain = bytearray(build(shift))
            plain[0:4] = b'\x01ZGI';plain[0x28:0x2c] = bytes(4)
            plain[FIELD:FIELD + 8] = struct.pack('<Q', 0x24e28 + shift)
            obj = 0x6000 + (shift if moved else 0)
            plain[obj:obj + 128] = bytes(range(7, 135))
            return bytes(plain)
        source, target = archive([('a.bin', variant(0))]), archive([('a.bin', variant(0x60))])
        recipe = archive_blocks.resolve(source, 'x.arc', [dict(member='a.bin', find_hex=b'FIELDTAG'.hex(), replacement_hex='00')])
        recipe['chunks'][0]['edits'] = [dict(offset=FIELD, expected_hex=struct.pack('<Q', 0x24e28).hex(),
                                             replacement_hex=struct.pack('<Q', 0x6000).hex())]
        ported, how = make_mod.port_asset(recipe, source, target)
        self.assertTrue(how.startswith('relocated'))
        patched = plain_of(asset_mod.patch_asset(target, ported)[0])
        # The new pointer follows its object, never the other build's stale value.
        self.assertEqual(struct.unpack_from('<Q', patched, FIELD)[0], 0x6060)
        # An object that cannot be found once is refused, never guessed.
        recipe['chunks'][0]['edits'][0]['replacement_hex'] = struct.pack('<Q', 0x7fc0).hex()  # its object would run past the file
        with self.assertRaisesRegex(ValueError, 'not found once'):
            make_mod.port_asset(recipe, source, target)

    def test_refusals(self):
        data = archive([('a.bin', build(0))])
        with self.assertRaisesRegex(ValueError, 'changed size'):
            make_mod.portable_edits(data, [], {'a.bin': build(0) + b'x'})
        with self.assertRaisesRegex(ValueError, 'No changes'):
            make_mod.portable_edits(data, [], {'a.bin': build(0)})
        with self.assertRaisesRegex(ValueError, 'not in this archive'):
            make_mod.portable_edits(data, [], {'b.bin': b''})

    def test_portable_mod_that_does_not_fit_is_reported_as_unfit(self):
        data = archive([('a.bin', build(0))])
        manifest = mod_manifest.parse(dict(
            schema_version=1, id='region', name='Region', version='1.0.0', author='Tests', licence='GPL-3.0-or-later',
            targets=[dict(title_id='CUSA00000', app_version='01.00', executable_sha256='a' * 64)],
            operations=[dict(type='asset-find', asset='x.arc', edits=[dict(find_hex=b'NOTHERE!'.hex(), replacement_hex='00')])]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.arc';path.write_bytes(data)
            with self.assertRaises(mod_manifest.ModUnfit) as caught:
                mod_manifest.plan({'region': manifest}, ['region'], 'a' * 64, asset_source=lambda _: path)
        self.assertEqual(caught.exception.ident, 'region')

    def test_member_names_become_safe_paths(self):
        self.assertEqual(str(make_mod.safe_name('c:\\temp/a//b.igz')), 'c_/temp/a/b.igz')
        for bad in ('..', '/', 'a/../b'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make_mod.safe_name(bad)

    def test_compact_edits_patch_the_same_bytes(self):
        rng = random.Random(7)
        plain = bytes(rng.randrange(256) for _ in range(4096))
        moved = plain[100:400]  # a run shifted by 4 bytes, as when a table grows
        new = bytes([1, 2, 3, 4]) + moved
        edits = [dict(offset=96, expected_hex=plain[96:400].hex(), replacement_hex=new.hex())]
        compact = make_mod.compact_edits(plain, edits)
        self.assertTrue(any('copy_from' in item for item in compact))
        self.assertFalse(any('replacement_hex' in item for item in compact))
        self.assertEqual(asset_mod.edits(plain, compact), asset_mod.edits(plain, edits))

    def test_object_port_translates_a_pointer_the_edit_creates(self):
        # The edit turns a plain field into a pointer (adding it to the fixups). The
        # other copy has one more object early on, so the pointer must move with it.
        from test_igz_objects import chunk, pack
        import hashlib
        import igz_objects

        def igz(objects, pointers, room=0x40):
            body, starts = bytearray(8), []
            for size, kind, fields in objects:
                starts.append(len(body))
                item = bytearray(size);struct.pack_into('<Q', item, 0, kind)
                for field, value in fields.items():
                    struct.pack_into('<Q', item, field, value)
                body += item
            rofs = sorted(starts[index] + field for index, field in pointers)
            fixups = chunk(b'TSTR', 1, b'ab\0\0' + bytes(room)) + chunk(b'RVTB', len(starts), pack(starts)) + \
                chunk(b'ROFS', len(rofs), pack(rofs)) + chunk(b'ROOT', 1, bytes(4))
            head = bytearray(0x800);head[:4] = igz_objects.MAGIC
            struct.pack_into('<II', head, 0x28, 0x800 + len(fixups), len(body))
            return bytes(head + fixups + body), starts

        common, later = [(0x40, 3, {}), (0x30, 5, {})], [(0x20, 7, {}), (0x28, 9, {8: 0x1234})]
        source, s_starts = igz(common + later, [], room=0x44)  # the edited table is 4 bytes longer
        edited, _ = igz(common + later[:1] + [(0x28, 9, {8: 0})], [(3, 8)])
        edited = bytearray(edited)  # the new pointer names the third object
        struct.pack_into('<Q', edited, struct.unpack_from('<I', edited, 0x28)[0] + s_starts[3] + 8, s_starts[2])
        target, t_starts = igz(common[:1] + [(0x50, 11, {})] + common[1:] + later, [], room=0x44)
        source_archive, target_archive = archive([('level.bld', source)]), archive([('level.bld', target)])
        chunks = []
        for block in archive_blocks.blocks(source_archive):
            start = block['member_offset'];plain = block['plain'];new = bytes(edited[start:start + len(plain)])
            edits = [dict(offset=a, expected_hex=plain[a:b].hex(), replacement_hex=new[a:b].hex())
                     for a, b in make_mod.runs(plain, new)]
            if edits:
                chunks.append(dict(block['chunk'], decoded_sha256=hashlib.sha256(plain).hexdigest(), edits=edits))
        recipe = dict(asset='x.bld', source_sha256=hashlib.sha256(source_archive).hexdigest(), chunks=chunks)
        self.assertEqual(plain_of(asset_mod.patch_asset(source_archive, recipe)[0]), bytes(edited))
        ported = make_mod.port_by_objects(recipe, source_archive, target_archive)
        result = plain_of(asset_mod.patch_asset(target_archive, ported)[0])
        start = struct.unpack_from('<I', result, 0x28)[0]
        self.assertEqual(struct.unpack_from('<Q', result, start + t_starts[4] + 8)[0], t_starts[3])
        self.assertEqual(igz_objects.pointer_fields(result), {t_starts[4] + 8})


if __name__ == '__main__':
    unittest.main()

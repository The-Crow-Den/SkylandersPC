# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import lzma
import os
import random
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import asset_mod


def fixture(compressed=True):
    plain = b'original rule ' * 100
    changed = b'optional rule '
    if compressed:
        filters = [dict(id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)]
        encoded = lzma.compress(plain, format=lzma.FORMAT_RAW, filters=filters)
        payload = struct.pack('<H', len(encoded)) + b'\x5d\x00\x80\x00\x00' + encoded
        allocation = 2048
    else:
        payload, allocation = plain, len(plain) + 32
    data = b'H' * 64 + payload + b'P' * (allocation - len(payload)) + b'T' * 64
    chunk = dict(offset=64, allocation=allocation, decoded_size=len(plain),
                 decoded_sha256=asset_mod.digest(plain),
                 encoding='raw-lzma' if compressed else 'raw',
                 edits=[dict(offset=0, expected_hex=plain[:len(changed)].hex(),
                             replacement_hex=changed.hex())])
    if compressed:
        chunk.update(encoded_size=len(encoded), properties_hex='5d00800000')
    recipe = dict(asset='level/test.bld', source_sha256=asset_mod.digest(data), chunks=[chunk])
    return data, recipe, plain, changed


class AssetModTests(unittest.TestCase):
    def test_copy_edits_read_original_bytes_and_fail_closed(self):
        original = b'AAAABBBBCCCC'
        move = dict(offset=4, copy_from=0, length=4,
                    expected_sha256=asset_mod.digest(b'BBBB'),
                    source_sha256=asset_mod.digest(b'AAAA'))
        first = dict(offset=0, expected_hex=b'AAAA'.hex(), replacement_hex=b'DDDD'.hex())
        self.assertEqual(asset_mod.edits(original, [first, move]), b'DDDDAAAACCCC')
        for field, value in (('copy_from', 11), ('length', 0),
                             ('expected_sha256', '0'*64), ('source_sha256', '0'*64)):
            bad = dict(move, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                asset_mod.edits(original, [bad])
        with self.assertRaisesRegex(ValueError, 'overlap'):
            asset_mod.edits(original, [move, dict(offset=6, expected_hex='4242', replacement_hex='4343')])

    def test_better_compression_is_lengthened_to_keep_the_next_block(self):
        plain = random.Random(5).randbytes(3200) + bytes(8192 - 3200)
        filters = [dict(id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)]
        encoded = lzma.compress(plain, format=lzma.FORMAT_RAW, filters=filters)
        allocation = (7 + len(encoded) + 511) // 512 * 512
        following = b'NEXT ARCHIVE BLOCK'
        original = (struct.pack('<H', len(encoded)) + bytes.fromhex('5d00800000') +
                    encoded + bytes(allocation - 7 - len(encoded)) + following)
        rng = random.Random(481)
        changed = bytes(rng.randrange(4) for _ in range(len(plain)))
        # Plain recompression would end more than one 512-byte unit early.
        self.assertLess(7 + len(lzma.compress(changed, format=lzma.FORMAT_RAW, filters=filters)), allocation - 512)
        recipe = dict(asset='level/test.bld', source_sha256=asset_mod.digest(original),
                      chunks=[dict(offset=0, allocation=allocation, decoded_size=len(plain),
                                   decoded_sha256=asset_mod.digest(plain), encoding='raw-lzma',
                                   alignment=512,
                                   encoded_size=len(encoded), properties_hex='5d00800000',
                                   edits=[dict(offset=0, expected_hex=plain.hex(),
                                               replacement_hex=changed.hex())])])
        output, _ = asset_mod.patch_asset(original, recipe)
        stored_size = struct.unpack_from('<H', output)[0]
        self.assertEqual((7 + stored_size + 511) // 512 * 512, allocation)  # walks to the next block
        self.assertEqual(output[allocation:], following)
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
        self.assertEqual(decoder.decompress(output[7:7+stored_size], max_length=len(plain)), changed)

    def test_block_that_cannot_be_lengthened_is_refused(self):
        plain = random.Random(482).randbytes(8192)
        filters = [dict(id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)]
        encoded = lzma.compress(plain, format=lzma.FORMAT_RAW, filters=filters)
        allocation = (7 + len(encoded) + 2047) // 2048 * 2048
        original = struct.pack('<H', len(encoded)) + bytes.fromhex('5d00800000') + encoded + bytes(allocation - 7 - len(encoded))
        recipe = dict(asset='level/test.bld', source_sha256=asset_mod.digest(original),
                      chunks=[dict(offset=0, allocation=allocation, decoded_size=len(plain),
                                   decoded_sha256=asset_mod.digest(plain), encoding='raw-lzma',
                                   alignment=2048, encoded_size=len(encoded), properties_hex='5d00800000',
                                   edits=[dict(offset=0, expected_hex=plain.hex(), replacement_hex=bytes(8192).hex())])])
        with self.assertRaisesRegex(ValueError, 'large enough'):
            asset_mod.patch_asset(original, recipe)

    def test_alignment_must_match_original_archive_boundary(self):
        data, recipe, _, _ = fixture()
        for alignment in (0, 3, 4096, -1):
            bad = copy.deepcopy(recipe)
            bad['chunks'][0]['alignment'] = alignment
            with self.subTest(alignment=alignment), self.assertRaisesRegex(ValueError, 'alignment'):
                asset_mod.patch_asset(data, bad)

    def test_alignment_does_not_pad_a_smaller_stream_within_the_same_block(self):
        plain = random.Random(934).randbytes(512)
        filters = [dict(id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)]
        encoded = lzma.compress(plain, format=lzma.FORMAT_RAW, filters=filters)
        original = (struct.pack('<H', len(encoded)) + bytes.fromhex('5d00800000') +
                    encoded + bytes(2048 - 7 - len(encoded)))
        chunk = dict(offset=0, allocation=2048, decoded_size=len(plain),
                     decoded_sha256=asset_mod.digest(plain), encoding='raw-lzma',
                     encoded_size=len(encoded), properties_hex='5d00800000', alignment=2048,
                     edits=[dict(offset=0, expected_hex=plain.hex(), replacement_hex=bytes(512).hex())])
        output, _ = asset_mod.patch_asset(original, dict(source_sha256=asset_mod.digest(original), chunks=[chunk]))
        expected = lzma.compress(bytes(512), format=lzma.FORMAT_RAW,
            filters=[dict(filters[0], mode=lzma.MODE_NORMAL, nice_len=64, mf=lzma.MF_BT4)])
        self.assertEqual(struct.unpack_from('<H', output)[0], len(expected))
        self.assertLess(len(expected), len(encoded))

    def test_composing_independent_fields_in_one_compressed_chunk(self):
        data, recipe, plain, changed = fixture()
        second = copy.deepcopy(recipe)
        second['chunks'][0]['edits'][0]['offset'] = 28
        profiles = [dict(executable_sha256='same', assets=[item]) for item in (recipe, second)]
        combined = asset_mod.combine_profiles(profiles)
        self.assertEqual(len(recipe['chunks'][0]['edits']), 1)
        self.assertEqual(len(combined['assets'][0]['chunks'][0]['edits']), 2)
        output, _ = asset_mod.patch_asset(data, combined['assets'][0])
        size = struct.unpack_from('<H', output, 64)[0]
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                    filters=[dict(id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)])
        expected = bytearray(plain)
        expected[:len(changed)] = changed
        expected[28:28+len(changed)] = changed
        self.assertEqual(decoder.decompress(output[71:71+size]), bytes(expected))

    def test_composition_allows_copy_sources_but_rejects_destination_overlap(self):
        data, recipe, plain, changed = fixture()
        other = copy.deepcopy(recipe)
        other['chunks'][0]['edits'] = [dict(
            offset=42, copy_from=7, length=14,
            expected_sha256=asset_mod.digest(plain[42:56]),
            source_sha256=asset_mod.digest(plain[7:21]))]
        profiles = [dict(executable_sha256='same', assets=[r]) for r in (recipe, other)]
        composed = asset_mod.combine_profiles(profiles)
        output, _ = asset_mod.patch_asset(data, composed['assets'][0])
        size = struct.unpack_from('<H', output, 64)[0]
        decoded = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[dict(
            id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)]).decompress(output[71:71+size])
        self.assertEqual(decoded[:len(changed)], changed)
        self.assertEqual(decoded[42:56], plain[7:21])
        other['chunks'][0]['edits'][0]['offset'] = 7
        with self.assertRaisesRegex(ValueError, 'overlap edits'):
            asset_mod.combine_profiles(profiles)

    def test_composition_rejects_conflicts_and_build_mismatch(self):
        _, recipe, _, _ = fixture()
        profile = dict(executable_sha256='same', assets=[recipe])
        with self.assertRaisesRegex(ValueError, 'overlap edits'):
            asset_mod.combine_profiles([profile, profile])
        other = copy.deepcopy(profile)
        other['executable_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'different game builds'):
            asset_mod.combine_profiles([profile, other])
        other = copy.deepcopy(profile)
        other['assets'][0]['chunks'][0]['decoded_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'shared chunk'):
            asset_mod.combine_profiles([profile, other])

    def test_recompression_and_unrelated_bytes(self):
        data, recipe, plain, changed = fixture()
        result, metadata = asset_mod.patch_asset(data, recipe)
        n = struct.unpack_from('<H', result, 64)[0]
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                    filters=[dict(id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)])
        self.assertEqual(decoder.decompress(result[71:71+n]), changed + plain[len(changed):])
        self.assertEqual(result[:64], data[:64])
        self.assertEqual(result[-64:], data[-64:])
        self.assertEqual(len(result), len(data))
        self.assertEqual(metadata['output_sha256'], asset_mod.digest(result))

    def test_raw_chunk_preserves_padding(self):
        data, recipe, plain, changed = fixture(False)
        result, _ = asset_mod.patch_asset(data, recipe)
        self.assertEqual(result[64:64+len(plain)], changed + plain[len(changed):])
        self.assertEqual(result[64+len(plain):], data[64+len(plain):])

    def test_original_stream_can_use_external_size_without_end_marker(self):
        data, recipe, _, _ = fixture()
        chunk = recipe['chunks'][0]
        old_size = chunk['encoded_size']
        chunk['encoded_size'] -= 5
        modified = bytearray(data)
        struct.pack_into('<H', modified, 64, chunk['encoded_size'])
        modified[71 + old_size - 5:71 + old_size] = bytes(5)
        recipe['source_sha256'] = asset_mod.digest(modified)
        result, _ = asset_mod.patch_asset(bytes(modified), recipe)
        self.assertEqual(len(result), len(modified))

    def test_fail_closed_on_hash_bytes_and_overlaps(self):
        data, recipe, _, _ = fixture()
        with self.assertRaisesRegex(ValueError, 'unknown source'):
            asset_mod.patch_asset(data + b'?', recipe)
        for kind in ('expected', 'decoded', 'chunk overlap', 'edit overlap', 'bounds'):
            broken = copy.deepcopy(recipe)
            if kind == 'expected':
                broken['chunks'][0]['edits'][0]['expected_hex'] = '00' * 14
            elif kind == 'decoded':
                broken['chunks'][0]['decoded_sha256'] = '0' * 64
            elif kind == 'chunk overlap':
                broken['chunks'].append(copy.deepcopy(broken['chunks'][0]))
            elif kind == 'edit overlap':
                broken['chunks'][0]['edits'] *= 2
            else:
                broken['chunks'][0]['allocation'] = len(data)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                asset_mod.patch_asset(data, broken)

    def test_private_hard_link_preparation_and_default_off(self):
        data, recipe, _, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, session = root/'original', root/'session'
            private = session/'game'
            for path in (original/'level', private/'level'):
                path.mkdir(parents=True)
            (original/'eboot.bin').write_bytes(b'synthetic executable')
            source, target = original/recipe['asset'], private/recipe['asset']
            source.write_bytes(data)
            os.link(source, target)
            profile = dict(executable_sha256=asset_mod.digest(b'synthetic executable'), assets=[recipe])
            self.assertFalse(asset_mod.prepare(original, private, session, profile)['enabled'])
            self.assertEqual(source.stat().st_ino, target.stat().st_ino)
            result = asset_mod.prepare(original, private, session, profile, enabled=True)
            self.assertTrue(result['enabled'])
            self.assertEqual(source.read_bytes(), data)
            self.assertNotEqual(target.read_bytes(), data)
            self.assertNotEqual(source.stat().st_ino, target.stat().st_ino)
            self.assertEqual({p.name for p in session.iterdir()}, {'game'})

    def test_validate_all_assets_before_writing(self):
        data, recipe, _, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, session = root/'original', root/'session'
            private = session/'game'
            for path in (original/'level', private/'level'):
                path.mkdir(parents=True)
            (original/'eboot.bin').write_bytes(b'executable')
            for name in ('test.bld', 'other.bld'):
                (original/'level'/name).write_bytes(data)
                os.link(original/'level'/name, private/'level'/name)
            bad = copy.deepcopy(recipe)
            bad.update(asset='level/other.bld', source_sha256='0'*64)
            profile = dict(executable_sha256=asset_mod.digest(b'executable'), assets=[recipe, bad])
            with self.assertRaises(ValueError):
                asset_mod.prepare(original, private, session, profile, enabled=True)
            self.assertEqual((private/recipe['asset']).read_bytes(), data)
            self.assertEqual((private/recipe['asset']).stat().st_ino,
                             (original/recipe['asset']).stat().st_ino)
            self.assertEqual({p.name for p in session.iterdir()}, {'game'})

    def test_cached_preparation_keeps_originals_and_staging_contract(self):
        data,recipe,_,_=fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=root/'original';(original/'level').mkdir(parents=True)
            (original/'eboot.bin').write_bytes(b'executable');(original/recipe['asset']).write_bytes(data)
            profile=dict(executable_sha256=asset_mod.digest(b'executable'),assets=[recipe])
            outputs=[]
            for label in ('cold','warm'):
                session=root/label;private=session/'game';(private/'level').mkdir(parents=True)
                os.link(original/recipe['asset'],private/recipe['asset'])
                result=asset_mod.prepare(original,private,session,profile,enabled=True,cache_directory=root/'cache')
                self.assertEqual(result['assets'][0]['cache'],'miss' if label=='cold' else 'hit')
                self.assertEqual((original/recipe['asset']).read_bytes(),data)
                self.assertNotEqual((original/recipe['asset']).stat().st_ino,(private/recipe['asset']).stat().st_ino)
                self.assertEqual({p.name for p in session.iterdir()},{'game'})
                outputs.append((private/recipe['asset']).read_bytes())
            self.assertEqual(outputs[0],outputs[1])

    def test_reused_hash_detects_same_size_mutation_with_restored_mtime(self):
        data,recipe,_,_=fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=root/'original';session=root/'session';private=session/'game'
            for folder in (original/'level',private/'level'):folder.mkdir(parents=True)
            (original/'eboot.bin').write_bytes(b'executable')
            source=original/recipe['asset'];source.write_bytes(data);os.link(source,private/recipe['asset'])
            profile=dict(executable_sha256=asset_mod.digest(b'executable'),assets=[recipe])
            real_patch=asset_mod.patch_asset
            def changing_patch(contents,plan):
                result=real_patch(contents,plan);before=source.stat()
                source.write_bytes(bytes([contents[0]^1])+contents[1:])
                os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
                return result
            with patch.object(asset_mod,'patch_asset',side_effect=changing_patch):
                with self.assertRaisesRegex(ValueError,'original asset changed'):
                    asset_mod.prepare(original,private,session,profile,enabled=True)
            self.assertEqual(source.stat().st_ino,(private/recipe['asset']).stat().st_ino)
            self.assertEqual({p.name for p in session.iterdir()},{'game'})

    def test_redirected_session_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, session, other = root/'original', root/'session', root/'other'
            for path in (original, session, other):
                path.mkdir()
            (original/'eboot.bin').write_bytes(b'executable')
            (session/'game').symlink_to(other, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'private session'):
                asset_mod.prepare(original, session/'game', session,
                    dict(executable_sha256=asset_mod.digest(b'executable'), assets=[]), enabled=True)

    def test_session_inside_original_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory)
            session = original/'accidental-output'
            (session/'game').mkdir(parents=True)
            (original/'eboot.bin').write_bytes(b'executable')
            with self.assertRaisesRegex(ValueError, 'private session'):
                asset_mod.prepare(original, session/'game', session,
                    dict(executable_sha256=asset_mod.digest(b'executable'), assets=[]), enabled=True)


if __name__ == '__main__':
    unittest.main()

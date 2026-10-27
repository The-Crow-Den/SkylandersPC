# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('prepare_native', TOOLS / 'prepare_native.py')
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)


def native_fixture():
    data = bytearray(0x800)
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 0, ident, 0xFE00, 62, 1, 0x400100,
                     64, 0, 0, 64, 56, 4, 64, 0, 0)
    rows = [(1, 5, 0, 0x400000, 0, 0x400, 0x400, 0x1000),
            (1, 6, 0x700, 0x401000, 0, 0x80, 0x100, 0x1000),
            (2, 4, 0x200, 0x400200, 0, 11 * 16, 11 * 16, 8),
            (0x61000000, 4, 0x400, 0, 0, 0x300, 0x300, 8)]
    for i, row in enumerate(rows):
        struct.pack_into('<II6Q', data, 64 + i * 56, *row)
    strings = b'\0syntheticNID#A#B\0libSynthetic\0syntheticModule\0'
    data[0x400:0x400 + len(strings)] = strings
    tags = [(0x61000035, 0), (0x61000037, len(strings)), (0x61000039, 0x80),
            (0x6100003B, 24), (0x6100003F, 72), (0x6100002F, 0x100),
            (0x61000031, 4 * 24), (0x61000033, 24),
            (0x61000015, strings.index(b'libSynthetic')),
            (0x6100000F, strings.index(b'syntheticModule') | (1 << 48)), (0, 0)]
    for i, row in enumerate(tags):
        struct.pack_into('<QQ', data, 0x200 + i * 16, *row)
    struct.pack_into('<IBBHQQ', data, 0x480 + 24, 1, 0x12, 0, 0, 0, 0)
    struct.pack_into('<IBBHQQ', data, 0x480 + 48, 0, 0x12, 0, 1, 0x400100, 0)
    relocs = [(0x401000, 8, 0x400100), (0x401008, (1 << 32) | 7, 0),
              (0x401010, (2 << 32) | 1, 4), (0x401018, (1 << 32) | 6, 0)]
    for i, row in enumerate(relocs):
        struct.pack_into('<QQq', data, 0x500 + i * 24, *row)
    return data


class NativePreparationTests(unittest.TestCase):
    def test_pack_layout_relocations_import_scopes_and_payload(self):
        data = native_fixture()
        packed, metadata = n.build_pack(data)
        magic, entry, base, size, nseg, nreloc, nimports = n.HEADER.unpack_from(packed)
        self.assertEqual((magic, entry, base, size, nseg, nreloc, nimports),
                         (b'SKYPS401', 0x400100, 0x400000, 0x2000, 2, 4, 1))
        segment = n.SEGMENT.unpack_from(packed, n.HEADER.size)
        self.assertEqual(packed[segment[4]:segment[4] + segment[2]], data[:0x400])
        relocation_offset = n.HEADER.size + 2 * n.SEGMENT.size
        relocs = [n.RELOCATION.unpack_from(packed, relocation_offset + i * n.RELOCATION.size) for i in range(4)]
        self.assertEqual(relocs[0], (0x401000, 8, 0, 0x400100))
        self.assertEqual(relocs[1], (0x401008, n.IMPORT_BIT | 7, 0, 0))
        self.assertEqual(relocs[2], (0x401010, 1, 0x400100, 4))
        import_offset = relocation_offset + 4 * n.RELOCATION.size
        self.assertEqual(packed[import_offset:import_offset + 128].rstrip(b'\0'), b'syntheticNID#libSynthetic#syntheticModule')
        self.assertEqual(metadata['imports'][0]['resolution'], 'unresolved')
        self.assertEqual(metadata['imports'][0]['raw_names'], ['syntheticNID#A#B'])

    def test_scope_ids_and_missing_descriptor_are_not_guessed(self):
        self.assertEqual(n.scope_id('BA'), 64)
        for invalid in ('', '!', 'AAAA', '---'):
            with self.subTest(scope=invalid), self.assertRaises(ValueError):
                n.scope_id(invalid)
        data = native_fixture()
        # Library descriptor now describes ID 2, while the symbol asks for A=0.
        descriptor = struct.unpack_from('<Q', data, 0x200 + 8 * 16 + 8)[0]
        struct.pack_into('<Q', data, 0x200 + 8 * 16 + 8, descriptor | (2 << 48))
        with self.assertRaisesRegex(ValueError, 'no matching'):
            n.build_pack(data)

    def test_rejects_unsupported_tls_targets_symbols_and_overlap(self):
        mutations = [(0x508, (1 << 32) | 16), (0x500, 0x500000),
                     (0x508, (999 << 32) | 7), (0x518, 0x401004),
                     (0x508, (1 << 32) | 8)]
        for offset, value in mutations:
            data = native_fixture()
            struct.pack_into('<Q', data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                n.build_pack(data)
        data = native_fixture()
        struct.pack_into('<H', data, 0x480 + 48 + 6, 0xFFF1)
        with self.assertRaisesRegex(ValueError, 'reserved'):
            n.build_pack(data)

    def test_rejects_overlapping_segments_and_unmapped_entry(self):
        data = native_fixture()
        struct.pack_into('<Q', data, 64 + 56 + 16, 0x400080)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            n.build_pack(data)
        data = native_fixture()
        struct.pack_into('<Q', data, 24, 0x401000)
        with self.assertRaisesRegex(ValueError, 'entry'):
            n.build_pack(data)

    def test_output_is_private_new_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.bin'
            source.write_bytes(native_fixture())
            before = source.read_bytes()
            with patch.object(n, 'ROOT', root):
                output = root / 'out' / 'native'
                metadata = n.prepare_path(source, output)
                self.assertEqual(json.loads((output / 'metadata.json').read_text())['pack_sha256'], metadata['pack_sha256'])
                with self.assertRaises(FileExistsError):
                    n.prepare_path(source, output)
                with self.assertRaises(ValueError):
                    n.prepare_path(source, root / 'outside-private-output')
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual((output / 'image.pack').read_bytes()[:8], b'SKYPS401')


if __name__ == '__main__':
    unittest.main()

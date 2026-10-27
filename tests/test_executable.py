# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('executable', Path(__file__).resolve().parents[1] / 'tools/executable.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


def elf_header(phnum=0, shoff=0, shnum=0):
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    return struct.pack('<16sHHIQQQIHHHHHH', ident, 0xFE00, 62, 1, 0x400000,
                       64 if phnum else 0, shoff, 0, 64, 56, phnum, 64, shnum, 0)


def sce_fixture():
    data = bytearray(0x400)
    data[:64] = elf_header(3)
    strings = b'\0syntheticNID#A#B\0libSceSynthetic\0syntheticModule\0'
    library_name = strings.index(b'libSce')
    module_name = strings.index(b'syntheticModule')
    tags = [(0x61000035, 0), (0x61000037, len(strings)), (0x61000039, 0x80),
            (0x6100003B, 24), (0x6100003F, 48),
            (0x61000015, library_name | (7 << 48) | (2 << 32)),
            (0x6100000F, module_name | (3 << 48)), (0, 0)]
    ph = [(1, 5, 0, 0x400000, 0, 0x300, 0x300, 0x1000),
          (2, 4, 0x100, 0x400100, 0, len(tags) * 16, len(tags) * 16, 8),
          (0x61000000, 4, 0x300, 0, 0, 0x100, 0x100, 8)]
    for index, row in enumerate(ph):
        struct.pack_into('<II6Q', data, 64 + index * 56, *row)
    for index, row in enumerate(tags):
        struct.pack_into('<QQ', data, 0x100 + index * 16, *row)
    data[0x300:0x300 + len(strings)] = strings
    struct.pack_into('<IBBHQQ', data, 0x380 + 24, 1, 0x12, 0, 0, 0, 0)
    return data


def self_fixture(elf):
    data = bytearray(0x600)
    data[:4] = b'O\x15=\x1d'
    struct.pack_into('<H', data, 24, 2)
    struct.pack_into('<4Q', data, 32, 0x800, 0x200, 0x300, 0x300)
    struct.pack_into('<4Q', data, 64, 0x800 | (2 << 20), 0x500, 0x100, 0x100)
    data[96:96 + 232] = elf[:232]
    data[0x200:0x500] = elf[:0x300]
    data[0x500:0x600] = elf[0x300:0x400]
    return data


class InspectionTests(unittest.TestCase):
    def test_omitted_optional_self_metadata_is_reported_but_loads_stay_required(self):
        data = self_fixture(sce_fixture())
        base = 96
        struct.pack_into('<H', data, base + 56, 4)
        position = base + 64 + 3 * 56
        struct.pack_into('<II6Q', data, position, 0x6FFFFF01, 0, 0x480, 0, 0, 16, 16, 1)
        report = e.inspect_bytes(data)
        self.assertEqual(report['unavailable_program_headers'], [3])
        self.assertEqual(report['imports']['count'], 1)
        struct.pack_into('<I', data, position, 1)
        with self.assertRaises(ValueError):
            e.inspect_bytes(data)

    def test_minimal_elf_has_no_import_table_not_resolved(self):
        report = e.inspect_bytes(elf_header())
        self.assertEqual(report['imports']['status'], 'no import table present')
        self.assertEqual(report['imports']['runtime_resolution'], 'not checked')

    def test_sce_imports_have_encoded_scope_and_raw_libraries(self):
        report = e.inspect_bytes(sce_fixture())
        self.assertEqual(report['imports']['count'], 1)
        symbol = report['imports']['symbols'][0]
        self.assertEqual(symbol['nid'], 'syntheticNID')
        self.assertEqual(symbol['library_id_encoded'], 'A')
        self.assertEqual(symbol['module_id_encoded'], 'B')
        self.assertEqual(symbol['resolution'], 'not checked')
        self.assertEqual(report['imports']['libraries'][0]['name'], 'syntheticModule')

    def test_plaintext_self_matches_elf_imports_and_does_not_write(self):
        elf = sce_fixture()
        container = self_fixture(elf)
        self.assertEqual(e.inspect_bytes(container)['imports'], e.inspect_bytes(elf)['imports'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.bin'
            path.write_bytes(container)
            e.inspect_path(path)
            self.assertEqual(path.read_bytes(), container)

    def test_encrypted_compressed_and_duplicate_self_mappings_refused(self):
        for flag in (0x802, 0x808, 0x800 | (4095 << 20)):
            data = self_fixture(sce_fixture())
            struct.pack_into('<Q', data, 32, flag)
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                e.inspect_bytes(data)
        data = self_fixture(sce_fixture())
        struct.pack_into('<Q', data, 64, 0x800)
        with self.assertRaises(ValueError):
            e.inspect_bytes(data)

    def test_truncation_and_invalid_header_ranges_refused(self):
        full = sce_fixture()
        for size in (0, 4, 63, 120, 0x180, 0x3FF):
            with self.subTest(size=size), self.assertRaises(ValueError):
                e.inspect_bytes(full[:size])
        for offset, fmt, value in ((18, '<H', 183), (52, '<H', 0), (56, '<H', 65535),
                                   (64 + 32, '<Q', 0x500), (64 + 40, '<Q', 1)):
            data = bytearray(full)
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                e.inspect_bytes(data)

    def test_dynamic_tables_validate_terminator_sizes_and_strings(self):
        for offset, value in ((0x100 + 7 * 16, 1), (0x100 + 3 * 16 + 8, 16),
                              (0x100 + 4 * 16 + 8, 47), (0x380 + 24, 0xFFFF)):
            data = sce_fixture()
            struct.pack_into('<Q' if offset != 0x380 + 24 else '<I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                e.inspect_bytes(data)
        data = sce_fixture()
        # String table claims one byte: undefined symbol's name lies outside it.
        struct.pack_into('<Q', data, 0x100 + 16 + 8, 1)
        with self.assertRaises(ValueError):
            e.inspect_bytes(data)

    def test_generic_dynsym_sections(self):
        data = bytearray(0x200)
        data[:64] = elf_header(shoff=64, shnum=3)
        struct.pack_into('<II4QII2Q', data, 128, 0, 3, 0, 0, 0x140, 6, 0, 0, 1, 0)
        struct.pack_into('<II4QII2Q', data, 192, 0, 11, 0, 0, 0x160, 48, 1, 0, 8, 24)
        data[0x140:0x146] = b'\0call\0'
        struct.pack_into('<IBBHQQ', data, 0x160 + 24, 1, 0x22, 0, 0, 0, 0)
        report = e.inspect_bytes(data)
        self.assertEqual(report['imports']['symbols'][0]['name'], 'call')
        self.assertTrue(report['imports']['symbols'][0]['weak'])
        struct.pack_into('<I', data, 192 + 40, 99)
        with self.assertRaises(ValueError):
            e.inspect_bytes(data)


if __name__ == '__main__':
    unittest.main()

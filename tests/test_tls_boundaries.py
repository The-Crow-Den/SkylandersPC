# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import struct
import unittest

from tools import tls_boundaries as t

BASE = 0x400000


def fixture():
    data = bytearray(0x500)
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 0, ident, 0xFE00, 62, 1,
                     BASE + 0x100, 64, 0, 0, 64, 56, 2, 64, 0, 0)
    struct.pack_into('<II6Q', data, 64, 1, 5, 0, BASE, 0, len(data), len(data), 4096)
    struct.pack_into('<II6Q', data, 120, 0x6474E550, 4, 0x400, BASE + 0x400, 0, 28, 28, 4)
    cie = b'\0\0\0\0\x01zR\0\x01\x78\x10\x01\x1b'
    struct.pack_into('<I', data, 0x200, len(cie))
    data[0x204:0x204 + len(cie)] = cie
    for fde, pc in ((0x220, 0x100), (0x240, 0x120)):
        content = struct.pack('<IiiB', fde + 4 - 0x200, pc - fde - 8, 9, 0)
        struct.pack_into('<I', data, fde, len(content))
        data[fde + 4:fde + 4 + len(content)] = content
    data[0x400:0x404] = b'\x01\x1b\x03\x3b'
    struct.pack_into('<iIiiii', data, 0x404, 0x200 - 0x404, 2,
                     0x100 - 0x400, 0x220 - 0x400, 0x120 - 0x400, 0x240 - 0x400)
    return data


def discover(data):
    return t.discover(data, hashlib.sha256(data).hexdigest())


class BoundaryTests(unittest.TestCase):
    def test_ranges_are_metadata_evidence_and_leave_gaps_unknown(self):
        data = fixture()
        before = bytes(data)
        report = discover(data)
        self.assertFalse(report['rewrite_authorized'])
        self.assertEqual(report['function_ranges'], [
            {'address': BASE + 0x100, 'size': 9, 'file_offset': 0x100},
            {'address': BASE + 0x120, 'size': 9, 'file_offset': 0x120}])
        self.assertEqual(sum(x['size'] for x in report['uncovered_ranges']), len(data) - 18)
        self.assertEqual(bytes(data), before)

    def test_hash_refused_before_container_parse(self):
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            t.discover(b'not an ELF', '0' * 64)
        for invalid in ('', 'A' * 64, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                t.discover(fixture(), invalid)

    def test_plaintext_self_reports_physical_source_offsets(self):
        elf = fixture()
        data = bytearray(0x700)
        data[:4] = b'O\x15=\x1d'
        struct.pack_into('<H', data, 24, 1)
        struct.pack_into('<4Q', data, 32, 0x800, 0x200, len(elf), len(elf))
        data[64:64 + 176] = elf[:176]
        data[0x200:0x700] = elf
        report = discover(data)
        self.assertEqual([r['file_offset'] for r in report['function_ranges']], [0x300, 0x320])

    def test_header_versions_encodings_and_counts_are_not_guessed(self):
        for offset, fmt, value in ((0x400, 'B', 2), (0x401, 'B', 0), (0x402, 'B', 0xff),
                                   (0x403, 'B', 3), (0x408, '<I', 0), (0x408, '<I', 1_000_001),
                                   (0x408, '<I', 4), (0x404, '<i', 0)):
            data = fixture()
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                discover(data)

    def test_bad_fde_ranges_references_and_lengths_refused(self):
        for offset, fmt, value in ((0x220, '<I', 0xffffffff), (0x220, '<I', 0),
                                   (0x224, '<I', 0), (0x224, '<I', 0xffff),
                                   (0x228, '<i', 0), (0x22c, '<i', -1),
                                   (0x22c, '<i', 0x7fffffff), (0x230, 'B', 127),
                                   (0x414, '<i', 0x100 - 0x400),
                                   (0x418, '<i', 0x220 - 0x400)):
            data = fixture()
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                discover(data)

    def test_bad_cie_augmentation_and_pointer_encoding_refused(self):
        for offset, value in ((0x204, 1), (0x208, 4), (0x209, ord('x')),
                              (0x20a, ord('X')), (0x20c, 0), (0x210, 0xff)):
            data = fixture()
            data[offset] = value
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                discover(data)

    def test_second_layout_uses_version_three_and_absolute_fde_pointers(self):
        data = fixture()
        data[0x208] = 3
        data[0x210] = 0
        for fde, pc in ((0x220, 0x100), (0x240, 0x120)):
            content = struct.pack('<IQQB', fde + 4 - 0x200, BASE + pc, 9, 0)
            struct.pack_into('<I', data, fde, len(content))
            data[fde + 4:fde + 4 + len(content)] = content
        report = discover(data)
        self.assertEqual([r['address'] for r in report['function_ranges']], [BASE + 0x100, BASE + 0x120])
        self.assertFalse(report['rewrite_authorized'])

    def test_nonexecuting_functions_are_refused(self):
        data = fixture()
        struct.pack_into('<I', data, 68, 4)
        with self.assertRaisesRegex(ValueError, 'outside executable'):
            discover(data)

    def test_nonreturning_thunks_require_exact_import_slot_and_original_jmp(self):
        from test_prepare_native import native_fixture
        data = native_fixture()
        old = b'syntheticNID#A#B'
        new = t.audit_imports.nid('__stack_chk_fail').encode() + b'#A#B'
        pos = data.index(old)
        data[pos:pos + len(old)] = bytes(len(old))
        data[pos:pos + len(new)] = new
        for old in (b'libSynthetic', b'syntheticModule'):
            pos = data.index(old)
            data[pos:pos + len(old)] = b'libkernel' + bytes(len(old) - len(b'libkernel'))
        slot = 0x401008
        thunk = b'\xff\x25' + struct.pack('<i', slot - (BASE + 0x180 + 6))
        data[0x180:0x186] = thunk
        report = t.nonreturning_import_thunks(data, hashlib.sha256(data).hexdigest())
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]['address'], BASE + 0x180)
        self.assertEqual(report[0]['expected_bytes_hex'], thunk.hex())
        self.assertEqual(report[0]['slot_address'], slot)
        # A data-only lookalike is not a thunk; the executable JMP must also
        # resolve to the exact declared import slot.
        data[0x680:0x686] = thunk
        data[0x182] ^= 1
        self.assertEqual(t.nonreturning_import_thunks(data, hashlib.sha256(data).hexdigest()), [])
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            t.nonreturning_import_thunks(data, '0' * 64)

    def test_bounded_leb_values_and_truncation(self):
        self.assertEqual(t._leb(b'\x78', 0, signed=True), (-8, 1))
        self.assertEqual(t._leb(b'\xff\x7f', 0), (16383, 2))
        for data in (b'', b'\x80' * 10, b'\xff' * 9 + b'\x02'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                t._leb(data, 0)


if __name__ == '__main__':
    unittest.main()

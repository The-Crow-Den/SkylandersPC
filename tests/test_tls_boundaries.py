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


def exception_fixture(call_encoding=3, type_encoding=0xff, pointer_encoding=0x1b):
    data = fixture()
    cie = b'\0\0\0\0\x01zLR\0\x01\x78\x10\x02' + bytes((pointer_encoding, 0x1b))
    struct.pack_into('<I', data, 0x200, len(cie))
    data[0x204:0x204 + len(cie)] = cie
    width = 4 if pointer_encoding == 0x1b else 8
    for fde, pc in ((0x220, 0x100), (0x240, 0x120)):
        value = 0 if pc == 0x120 else (0x300 - (fde + 17) if width == 4 else BASE + 0x300)
        content = struct.pack('<IiiB', fde + 4 - 0x200, pc - fde - 8, 9, width)
        content += struct.pack('<i' if width == 4 else '<Q', value)
        struct.pack_into('<I', data, fde, len(content))
        data[fde + 4:fde + 4 + len(content)] = content
    header = bytes((0xff, type_encoding))
    if type_encoding != 0xff:
        header += b'\x3d'  # Type table base at0x340, relative to byte following this ULEB.
    row = struct.pack('<III', 0, 3, 5) + b'\0' if call_encoding == 3 else bytes((0, 3, 5, 0))
    blob = header + bytes((call_encoding, len(row))) + row
    data[0x300:0x300 + len(blob)] = blob
    return data


class BoundaryTests(unittest.TestCase):
    def test_exception_call_sites_add_roots_but_no_rewrite_authority(self):
        data = exception_fixture()
        before = bytes(data)
        report = discover(data)
        self.assertEqual(report['landing_pad_roots'], [BASE + 0x105])
        table, = report['exception_tables']
        self.assertEqual(table['address'], BASE + 0x300)
        self.assertEqual(table['parsed_size'], 17)
        self.assertEqual(table['call_sites'], [{'address': BASE + 0x100, 'size': 3,
            'landing_pad': BASE + 0x105, 'action_offset': 0}])
        self.assertFalse(table['action_type_payloads_parsed'])
        self.assertFalse(report['rewrite_authorized'])
        self.assertEqual(bytes(data), before)
        self.assertIn({'address': BASE + 0x300, 'size': 17, 'kind': 'exception-call-sites'}, report['metadata_ranges'])

    def test_uleb_call_sites_and_absolute_lsda_pointer(self):
        report = discover(exception_fixture(call_encoding=1, pointer_encoding=0))
        self.assertEqual(report['landing_pad_roots'], [BASE + 0x105])
        self.assertEqual(report['exception_tables'][0]['parsed_size'], 8)

    def test_exception_payloads_are_not_implicitly_classified(self):
        data = exception_fixture(type_encoding=0x9b)
        data[0x311] = 1  # First action at0x312; its payload is deliberately unparsed.
        report = discover(data)
        self.assertEqual(report['exception_tables'][0]['parsed_size'], 18)
        self.assertFalse(any(r['address'] <= BASE + 0x312 < r['address'] + r['size']
                             for r in report['metadata_ranges']))
        data[0x311] = 127
        with self.assertRaisesRegex(ValueError, 'action reference'):
            discover(data)

    def test_exception_encodings_and_lengths_refuse_unknown_forms(self):
        for offset, value in ((0x300, 0x1b), (0x301, 0x12), (0x302, 0x81),
                              (0x303, 12), (0x303, 14), (0x211, 3), (0x230, 0)):
            data = exception_fixture()
            data[offset] = value
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                discover(data)
        data = exception_fixture()
        data[0x303:0x30e] = b'\x80' * 11
        with self.assertRaisesRegex(ValueError, 'LEB'):
            discover(data)

    def test_exception_ranges_and_landing_pads_must_fit_the_function(self):
        for offset, value in ((0x304, 10), (0x308, 10), (0x30c, 9)):
            data = exception_fixture()
            struct.pack_into('<I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'function'):
                discover(data)
        data = exception_fixture()
        struct.pack_into('<I', data, 0x30c, 0)
        self.assertEqual(discover(data)['landing_pad_roots'], [])

    def test_exception_overlapping_call_sites_are_refused(self):
        data = exception_fixture()
        row = data[0x304:0x311]
        data[0x311:0x31e] = row
        data[0x303] = 26
        with self.assertRaisesRegex(ValueError, 'overlap'):
            discover(data)

    def test_exception_metadata_cannot_alias_function_code(self):
        data = exception_fixture()
        data[0x100:0x111] = data[0x300:0x311]
        struct.pack_into('<i', data, 0x231, 0x100 - 0x231)
        with self.assertRaisesRegex(ValueError, 'function overlaps typed metadata'):
            discover(data)

    def test_null_and_shared_exception_pointers(self):
        data = exception_fixture()
        struct.pack_into('<i', data, 0x231, 0)
        self.assertEqual(discover(data)['exception_tables'], [])
        data = exception_fixture()
        struct.pack_into('<i', data, 0x251, 0x300 - 0x251)
        report = discover(data)
        self.assertEqual(report['landing_pad_roots'], [BASE + 0x105, BASE + 0x125])
        self.assertEqual(len(report['exception_tables']), 2)
        self.assertEqual(sum(r['kind'] == 'exception-call-sites' for r in report['metadata_ranges']), 1)

    def test_empty_and_omitted_exception_tables(self):
        data = exception_fixture()
        data[0x303] = 0
        report = discover(data)
        self.assertEqual(report['landing_pad_roots'], [])
        self.assertEqual(report['exception_tables'][0]['call_sites'], [])
        self.assertEqual(report['exception_tables'][0]['parsed_size'], 4)
        data = exception_fixture()
        data[0x211] = 0xff
        for fde, pc in ((0x220, 0x100), (0x240, 0x120)):
            content = struct.pack('<IiiB', fde + 4 - 0x200, pc - fde - 8, 9, 0)
            struct.pack_into('<I', data, fde, len(content))
            data[fde + 4:fde + 4 + len(content)] = content
        self.assertEqual(discover(data)['exception_tables'], [])

    def test_exception_pointer_and_type_base_must_be_mapped(self):
        data = exception_fixture()
        struct.pack_into('<i', data, 0x231, 0x7fffffff)
        with self.assertRaisesRegex(ValueError, 'read-only'):
            discover(data)
        data = exception_fixture(type_encoding=0x9b)
        data[0x302] = 0
        with self.assertRaisesRegex(ValueError, 'type table base'):
            discover(data)
        data = exception_fixture()
        struct.pack_into('<I', data, 68, 7)
        with self.assertRaisesRegex(ValueError, 'read-only'):
            discover(data)

    def test_exception_records_are_bounded_for_self_and_entry_budget(self):
        elf = exception_fixture()
        data = bytearray(0x700)
        data[:4] = b'O\x15=\x1d'
        struct.pack_into('<H', data, 24, 1)
        struct.pack_into('<4Q', data, 32, 0x800, 0x200, len(elf), len(elf))
        data[64:64 + 176] = elf[:176]
        data[0x200:0x700] = elf
        self.assertEqual(discover(data)['landing_pad_roots'], [BASE + 0x105])
        with self.assertRaisesRegex(ValueError, 'budget'):
            t._lsda_call_sites(t.executable.Image(elf), BASE + 0x300, BASE + 0x100, 9, 0)

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

    def test_only_parsed_metadata_bytes_are_classified(self):
        report = discover(fixture())
        spans = report['metadata_ranges']
        self.assertEqual(spans[-1], {'address': BASE + 0x400, 'size': 28, 'kind': 'unwind'})
        self.assertTrue(any(s['address'] == BASE + 0x200 and s['size'] == 17 for s in spans))
        self.assertFalse(any(s['address'] <= BASE + 0x219 < s['address'] + s['size'] for s in spans))
        self.assertFalse(report['rewrite_authorized'])

    def test_function_cannot_alias_unwind_metadata(self):
        data = fixture()
        struct.pack_into('<i', data, 0x228, 0x200 - 0x228)
        struct.pack_into('<i', data, 0x40c, 0x200 - 0x400)
        struct.pack_into('<i', data, 0x248, 0x300 - 0x248)
        struct.pack_into('<i', data, 0x414, 0x300 - 0x400)
        with self.assertRaisesRegex(ValueError, 'overlaps typed metadata'):
            discover(data)

    def test_interpreter_extent_is_a_bounded_mapped_string(self):
        data = fixture()
        struct.pack_into('<H', data, 56, 3)
        struct.pack_into('<II6Q', data, 176, 3, 4, 0x180, BASE + 0x180, 0, 4, 4, 1)
        data[0x180:0x184] = b'/ld\0'
        report = discover(data)
        self.assertIn({'address': BASE + 0x180, 'size': 4, 'kind': 'interpreter'}, report['metadata_ranges'])
        data[0x183] = ord('x')
        with self.assertRaisesRegex(ValueError, 'interpreter'):
            discover(data)
        data[0x183] = 0
        struct.pack_into('<Q', data, 176 + 16, BASE + 0x190)
        with self.assertRaisesRegex(ValueError, 'interpreter'):
            discover(data)

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

    def test_nonreturning_libc_thunks_use_exact_abi_name_and_both_scopes(self):
        from test_prepare_native import native_fixture
        cases = [(name, library, module, int(library == module == 'libc'))
                 for name in ('_ZSt9terminatev', '__cxa_throw', '__cxa_rethrow',
                              '_Unwind_Resume', 'abort', 'exit', '_Exit')
                 for library, module in (('libc', 'libc'), ('libc', 'libkernel'),
                                         ('libkernel', 'libc'))]
        cases += [(name, 'libc', 'libc', 0) for name in (
            '__cxa_begin_catch', '__cxa_end_catch', '_Unwind_RaiseException',
            '_Unwind_Resume_or_Rethrow', 'atexit', '_ZSt13set_terminatePFvvE')]
        for name, library, module, expected in cases:
            with self.subTest(name=name, library=library, module=module):
                data = native_fixture()
                original = b'syntheticNID#A#B'
                encoded = t.audit_imports.nid(name).encode() + b'#A#B'
                at = data.index(original)
                data[at:at + len(original)] = bytes(len(original))
                data[at:at + len(encoded)] = encoded
                for old, value in ((b'libSynthetic', library), (b'syntheticModule', module)):
                    at = data.index(old)
                    data[at:at + len(old)] = value.encode() + bytes(len(old) - len(value))
                slot = 0x401008
                thunk = b'\xff\x25' + struct.pack('<i', slot - (BASE + 0x180 + 6))
                data[0x180:0x186] = thunk
                report = t.nonreturning_import_thunks(data, hashlib.sha256(data).hexdigest())
                self.assertEqual(len(report), expected)
                if expected:
                    self.assertEqual(report[0]['import'], t.audit_imports.nid(name) + '#libc#libc')
                    self.assertEqual(report[0]['expected_bytes_hex'], thunk.hex())
                    image = t.executable.Image(data)
                    one, _, _ = t.link_native.dynamic_tables(image)
                    symbol = next(s for s in t.module_graph.analyze_bytes(data, 'main')['imports']
                                  if s['nid'] == t.audit_imports.nid(name))
                    blob = next(p for p in image.programs if p['type'] == 0x61000000)
                    info = blob['offset'] + one(0x61000039) + symbol['index'] * 24 + 4
                    data[info] = (data[info] & 0xf0) | 1  # Object symbol cannot provide the function contract.
                    with self.assertRaisesRegex(ValueError, 'function declaration'):
                        t.nonreturning_import_thunks(data, hashlib.sha256(data).hexdigest())

    def test_bounded_leb_values_and_truncation(self):
        self.assertEqual(t._leb(b'\x78', 0, signed=True), (-8, 1))
        self.assertEqual(t._leb(b'\xff\x7f', 0), (16383, 2))
        for data in (b'', b'\x80' * 10, b'\xff' * 9 + b'\x02'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                t._leb(data, 0)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

from test_prepare_native import native_fixture

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('link_native', TOOLS / 'link_native.py')
l = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l)


def provider_fixture(tls=False, sentinel=False):
    data = native_fixture()
    struct.pack_into('<Q', data, 0x200 + 8 * 16, 0x61000013)
    struct.pack_into('<Q', data, 0x200 + 9 * 16, 0x6100000D)
    struct.pack_into('<H', data, 0x480 + 24 + 6, 1)
    struct.pack_into('<Q', data, 0x480 + 24 + 8, 0x400100)
    if tls:
        struct.pack_into('<H', data, 56, 5)
        struct.pack_into('<II6Q', data, 64 + 4 * 56, 7, 4, 0x740, 0x401040, 0, 8, 32, 8)
        symbol = 0
        if sentinel:
            struct.pack_into('<Q', data, 0x200 + 4 * 16 + 8, 96)
            struct.pack_into('<IBBHQQ', data, 0x480 + 72, 0, 3, 0, 0, 0, 0)
            symbol = 3
        struct.pack_into('<QQq', data, 0x500 + 3 * 24, 0x401018, (symbol << 32) | 16, 0)
    return data


class NativeLinkTests(unittest.TestCase):
    def test_boot_plan_records_tls_and_rejects_unimplemented_init_arrays(self):
        _, _, metadata = l.link_images([('main', native_fixture()), ('provider', provider_fixture(tls=True))])
        plan = l.boot_plan(metadata)
        self.assertEqual(struct.unpack_from('<8s2Q', plan), (b'SKYBOOT1', 0, 2))
        provider = struct.unpack_from('<6Q', plan, 24 + 48)
        tls = metadata['modules'][1]['tls'][0]
        self.assertEqual(provider, (2, 0, tls['address'], 8, 32, 8))
        metadata['modules'][1]['initialization']['init_array_bytes'] = 8
        with self.assertRaisesRegex(ValueError, 'initializer arrays'):
            l.boot_plan(metadata)

    def test_weak_requirement_is_preserved_in_import_sidecar(self):
        data = native_fixture()
        data[0x480 + 24 + 4] = 0x22
        _, types, metadata = l.link_images([('main', data)])
        self.assertEqual(types, b'\x82')
        self.assertTrue(metadata['imports'][0]['weak'])

    def test_exact_exports_replace_imports_and_rebase_provider_symbols(self):
        packed, types, metadata = l.link_images([('main', native_fixture()), ('provider', provider_fixture())])
        header = l.prepare_native.HEADER.unpack_from(packed)
        self.assertEqual(header[4:], (4, 8, 0))
        self.assertEqual(types, b'')
        self.assertEqual(metadata['bindings'], [{'consumer': 'main', 'provider': 'provider', 'sites': 2}])
        slide = metadata['modules'][1]['slide']
        start = l.prepare_native.HEADER.size + 4 * l.prepare_native.SEGMENT.size
        rows = [l.prepare_native.RELOCATION.unpack_from(packed, start + i * 32) for i in range(8)]
        main_import = next(row for row in rows if row[0] == 0x401008)
        self.assertEqual(main_import, (0x401008, 7, 0x400100 + slide, 0))
        self.assertEqual((0x400000 + slide) % 16384, 0)

    def test_tls_local_module_ids_metadata_and_unsupported_forms(self):
        for sentinel in (False, True):
            packed, types, metadata = l.link_images([('main', native_fixture()), ('provider', provider_fixture(tls=True, sentinel=sentinel))])
            self.assertEqual(metadata['modules'][1]['tls'][0]['module_id'], 2)
            offset = l.prepare_native.HEADER.size + 4 * l.prepare_native.SEGMENT.size
            rows = [l.prepare_native.RELOCATION.unpack_from(packed, offset + i * 32) for i in range(8)]
            self.assertEqual([r[2] for r in rows if r[1] == 16], [2])
        for info, addend in (((1 << 32) | 16, 0), (16, 1), (17, 0)):
            data = provider_fixture(tls=True)
            struct.pack_into('<Qq', data, 0x500 + 3 * 24 + 8, info, addend)
            with self.subTest(info=info, addend=addend), self.assertRaises(ValueError):
                l.link_images([('main', native_fixture()), ('provider', data)])

    def test_unresolved_scopes_stay_pending_and_types_match_count(self):
        packed, types, metadata = l.link_images([('main', native_fixture())])
        self.assertEqual(types, b'\x02')
        self.assertEqual(metadata['import_count'], 1)
        self.assertEqual(metadata['imports'][0]['name'], 'syntheticNID#libSynthetic#syntheticModule')
        self.assertEqual(metadata['imports'][0]['resolution'], 'unresolved')

    def test_versions_not_guessed_and_ambiguous_exporters_refused(self):
        different = provider_fixture()
        descriptor = struct.unpack_from('<Q', different, 0x200 + 8 * 16 + 8)[0]
        struct.pack_into('<Q', different, 0x200 + 8 * 16 + 8, descriptor | (1 << 32))
        _, _, metadata = l.link_images([('main', native_fixture()), ('wrong-version', different)])
        self.assertEqual(metadata['import_count'], 1)
        self.assertEqual(metadata['bindings'], [])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            l.link_images([('main', native_fixture()), ('one', provider_fixture()), ('two', provider_fixture())])

    def test_redundant_relative_symbol_only_accepted_if_same_defined_address(self):
        data = provider_fixture()
        struct.pack_into('<Q', data, 0x508, (1 << 32) | 8)
        l.link_images([('main', native_fixture()), ('provider', data)])
        struct.pack_into('<q', data, 0x510, 0x400108)
        with self.assertRaisesRegex(ValueError, 'nonredundant'):
            l.link_images([('main', native_fixture()), ('provider', data)])


if __name__ == '__main__':
    unittest.main()

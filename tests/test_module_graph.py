# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('module_graph', TOOLS / 'module_graph.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def module_fixture(export=False, library_version=1, module_version=0x101,
                   symbol_type=2, raw_name=b'syntheticNID#A#B'):
    data = bytearray(0x300)
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 0, ident, 0xFE00, 62, 1, 0,
                     64, 0, 0, 64, 56, 2, 64, 0, 0)
    struct.pack_into('<II6Q', data, 64, 2, 4, 0x100, 0, 0, 128, 128, 8)
    struct.pack_into('<II6Q', data, 120, 0x61000000, 4, 0x200, 0, 0, 256, 256, 8)
    strings = b'\0' + raw_name + b'\0libSynthetic\0syntheticModule\0'
    data[0x200:0x200 + len(strings)] = strings
    tags = [(0x61000035, 0), (0x61000037, len(strings)), (0x61000039, 0x80),
            (0x6100003B, 24), (0x6100003F, 48),
            (0x61000013 if export else 0x61000015, strings.index(b'libSynthetic') | library_version << 32),
            (0x6100000D if export else 0x6100000F,
             strings.index(b'syntheticModule') | module_version << 32 | 1 << 48), (0, 0)]
    for i, row in enumerate(tags):
        struct.pack_into('<QQ', data, 0x100 + i * 16, *row)
    struct.pack_into('<IBBHQQ', data, 0x280 + 24, 1, 0x10 | symbol_type, 0,
                     1 if export else 0, 0x1000 if export else 0, 0)
    return data


class ModuleGraphTests(unittest.TestCase):
    def test_export_descriptors_canonicalize_and_match_exact_identity(self):
        caller = g.analyze_bytes(module_fixture(), 'main')
        provider = g.analyze_bytes(module_fixture(export=True), 'provider')
        self.assertEqual(provider['exports'][0]['name'], 'syntheticNID#libSynthetic#syntheticModule')
        report = g.match_modules([caller], [provider])['consumers'][0]
        self.assertEqual(len(report['matched']), 1)
        self.assertFalse(report['missing'])
        self.assertEqual(report['matched'][0]['provider'], 'provider')

    def test_versions_and_symbol_types_are_not_substituted(self):
        caller = g.analyze_bytes(module_fixture(), 'main')
        for kwargs in ({'library_version': 2}, {'module_version': 0x102}):
            provider = g.analyze_bytes(module_fixture(export=True, **kwargs), 'wrong-version')
            report = g.match_modules([caller], [provider])['consumers'][0]
            self.assertEqual(len(report['missing']), 1)
            self.assertFalse(report['matched'])
        provider = g.analyze_bytes(module_fixture(export=True, symbol_type=1), 'object')
        report = g.match_modules([caller], [provider])['consumers'][0]
        self.assertEqual(len(report['type_mismatch']), 1)
        self.assertFalse(report['matched'])

    def test_duplicate_providers_are_reported_ambiguous(self):
        caller = g.analyze_bytes(module_fixture(), 'main')
        providers = [g.analyze_bytes(module_fixture(export=True), name) for name in ('one', 'two')]
        report = g.match_modules([caller], providers)['consumers'][0]
        self.assertEqual(len(report['ambiguous']), 1)
        self.assertFalse(report['matched'])

    def test_plain_weak_imports_are_explicitly_unscoped(self):
        data = module_fixture(raw_name=b'module_start', symbol_type=0)
        struct.pack_into('<B', data, 0x280 + 24 + 4, 0x20)
        module = g.analyze_bytes(data, 'weak')
        report = g.match_modules([module], [])['consumers'][0]
        self.assertTrue(report['missing'][0]['weak'])
        self.assertEqual(report['missing_by_library'], {'<unscoped>': 1})

    def test_malformed_tables_and_missing_descriptors_fail(self):
        for offset, value in ((0x100 + 3 * 16 + 8, 16),
                              (0x100 + 4 * 16 + 8, 47),
                              (0x100 + 6 * 16 + 8, 0),
                              (0x100 + 7 * 16, 0x1234)):
            data = module_fixture()
            struct.pack_into('<Q', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                g.analyze_bytes(data, 'malformed')


if __name__ == '__main__':
    unittest.main()

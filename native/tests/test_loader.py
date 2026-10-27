# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic native-loader format and no-execution regressions."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()
IMPORT = 1 << 63
BASE = 0x400000


def fixture(relocations=None, imports=None):
    if relocations is None:
        relocations = [(BASE + 4096, 8, 0, BASE + 32),
                       (BASE + 4104, 1, BASE + 16, 8)]
    imports = imports or []
    payload = 56 + 80 + len(relocations) * 32 + len(imports) * 128
    result = bytearray(struct.pack('<8s6Q', b'SKYPS401', BASE, BASE, 8192, 2,
                                   len(relocations), len(imports)))
    result += struct.pack('<5Q', BASE, 4096, 64, 5, payload)
    result += struct.pack('<5Q', BASE + 4096, 4096, 16, 6, payload + 64)
    for row in relocations:
        result += struct.pack('<QQQq', *row)
    for name in imports:
        result += name.encode().ljust(128, b'\0')
    # int3 bytes would trap immediately if this tool ever accidentally called entry.
    result += b'\xCC' * 64 + bytes(16)
    return result


class LoaderTests(unittest.TestCase):
    def test_package_parameter_comes_from_selected_root(self):
        data = fixture([(BASE + 4096, IMPORT | 7, 0, 0)],
                       ['99b82IKXpH4#libSceAppContent#libSceAppContentUtil'])
        payload = struct.unpack_from('<Q', data, 56 + 32)[0]
        code = b'\xbf\x01\x00\x00\x00'
        code += b'\x48\x8d\x35' + struct.pack('<i', 4104 - len(code) - 7)
        code += b'\x48\x83\xec\x08'
        code += b'\xff\x15' + struct.pack('<i', 4096 - len(code) - 6)
        code += b'\x48\x83\xc4\x08'
        code += b'\x8b\x05' + struct.pack('<i', 4104 - len(code) - 6) + b'\xc3'
        data[payload:payload + len(code)] = code
        boot = struct.pack('<8s2Q6Q', b'SKYBOOT1', 0, 1, 1, 0, 0, 0, 0, 1)
        key = b'USER_DEFINED_PARAM_1\0'
        values = (36 + len(key) + 3) & ~3
        sfo = struct.pack('<4s4IHHIII', b'\0PSF', 0x101, 36, values, 1, 0, 0x404, 4, 4, 0)
        sfo += key + bytes(values - 36 - len(key)) + struct.pack('<I', 42)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sce_sys').mkdir()
            (root / 'image.pack').write_bytes(data)
            (root / 'types').write_bytes(b'\x02')
            (root / 'boot').write_bytes(boot)
            for content, okay in ((sfo, True), (sfo[:19], False)):
                (root / 'sce_sys/param.sfo').write_bytes(content)
                result = subprocess.run([str(BINARY), '--trace-start', str(root / 'image.pack'),
                                         str(root / 'types'), str(root / 'boot'), str(root)],
                                        capture_output=True, text=True, timeout=5)
                if okay:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stderr.splitlines()[-1])['return_value'], 42)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('entry-attempt', result.stderr)

    def test_boot_initializes_dependency_and_main_static_tls(self):
        data = fixture([])
        payload = struct.unpack_from('<Q', data, 56 + 32)[0]
        # Return the static TLS template plus a flag set only by module init.
        code = b'\x64\x48\x8b\x04\x25\xf8\xff\xff\xff'
        code += b'\x48\x03\x05' + struct.pack('<i', 4104 - len(code) - 7) + b'\xc3'
        data[payload:payload + len(code)] = code
        init = b'\x48\xc7\x05' + struct.pack('<i', 4104 - 32 - 11) + struct.pack('<I', 1)
        init += b'\x31\xc0\xc3'
        data[payload + 32:payload + 32 + len(init)] = init
        struct.pack_into('<Q', data, payload + 64, 41)
        boot = struct.pack('<8s2Q', b'SKYBOOT1', 0, 2)
        boot += struct.pack('<6Q', 1, 0, BASE + 4096, 8, 8, 8)
        boot += struct.pack('<6Q', 2, BASE + 32, 0, 0, 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'image.pack').write_bytes(data)
            (root / 'types').write_bytes(b'')
            for plan, okay in ((boot, True), (boot[:-1], False),
                               (boot[:24] + struct.pack('<6Q', 1, 0, BASE + 4096, 8, 8, 3) + boot[72:], False)):
                (root / 'boot').write_bytes(plan)
                result = subprocess.run([str(BINARY), '--trace-start', str(root / 'image.pack'),
                                         str(root / 'types'), str(root / 'boot')],
                                        capture_output=True, text=True, timeout=5)
                if okay:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stderr.splitlines()[-1])['return_value'], 42)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('entry-attempt', result.stderr)

    def test_missing_weak_symbol_is_null(self):
        data = fixture([(BASE + 4096, IMPORT | 6, 0, 0)], ['optional-symbol'])
        payload = struct.unpack_from('<Q', data, 56 + 32)[0]
        data[payload:payload + 8] = b'\x48\x8b\x05' + struct.pack('<i', 4096 - 7) + b'\xc3'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'image.pack').write_bytes(data)
            (root / 'types').write_bytes(b'\x80')
            result = subprocess.run([str(BINARY), '--trace-start', str(root / 'image.pack'), str(root / 'types')],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stderr.splitlines()[-1])['return_value'], 0)

    def test_stack_guard_read_scope_type_and_write_protection(self):
        for identity, kind, write, expected in (
            ('f7uOxY9mM1U#libkernel#libkernel', 1, False, 20),
            ('f7uOxY9mM1U#wrong#libkernel', 1, False, 70),
            ('f7uOxY9mM1U#libkernel#libkernel', 0, False, 70),
            ('f7uOxY9mM1U#libkernel#libkernel', 1, True, 70),
        ):
            with self.subTest(identity=identity, kind=kind, write=write):
                data = fixture([(BASE + 4096, IMPORT | 6, 0, 0),
                                (BASE + 4104, IMPORT | 7, 1, 0)],
                               [identity, 'after-guard-read#lib#module'])
                payload = struct.unpack_from('<Q', data, 56 + 32)[0]
                code = b'\x48\x8b\x05' + struct.pack('<i', 4096 - 7)
                code += b'\x48\x8b\x08'  # mov rcx,[rax]: actual canary read
                if write:
                    code += b'\x48\x89\x08'  # must fault on read-only guard
                code += b'\x48\x83\xec\x08'  # align RSP before the SysV import call
                code += b'\xff\x15' + struct.pack('<i', 4104 - len(code) - 6)
                data[payload:payload + len(code)] = code
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / 'image.pack').write_bytes(data)
                    (root / 'types').write_bytes(bytes([kind, 2]))
                    result = subprocess.run([str(BINARY), '--trace-start',
                                             str(root / 'image.pack'), str(root / 'types')],
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    if expected == 20:
                        self.assertEqual(json.loads(result.stderr.splitlines()[-1])['name'],
                                         'after-guard-read#lib#module')

    def test_trace_start_stops_at_function_import(self):
        data = fixture([(BASE + 4096, IMPORT | 7, 0, 0)], ['synthetic#lib#module'])
        payload = struct.unpack_from('<Q', data, 56 + 32)[0]
        data[payload:payload + 10] = b'\x48\x83\xec\x08\xff\x15' + struct.pack('<i', 4096 - 10)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'image.pack').write_bytes(data)
            (root / 'types').write_bytes(b'\x02')
            result = subprocess.run([str(BINARY), '--trace-start', str(root / 'image.pack'), str(root / 'types')],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 20, result.stderr)
            event = json.loads(result.stderr.splitlines()[-1])
            self.assertEqual(event['event'], 'unsupported-import')
            self.assertEqual(event['name'], 'synthetic#lib#module')
            self.assertTrue(event['guest_executed'])

    def test_local_tls_module_relocation_is_bounded(self):
        self.run_pack(fixture([(BASE + 4096, 16, 2, 0)]), '--load')
        for symbol, addend in ((0, 0), (17, 0), (2, 1)):
            self.run_pack(fixture([(BASE + 4096, 16, symbol, addend)]), okay=False)

    def run_pack(self, data, mode='--inspect', okay=True):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.pack'
            path.write_bytes(data)
            result = subprocess.run([str(BINARY), mode, str(path)], capture_output=True,
                                    text=True, timeout=5)
            self.assertEqual(path.read_bytes(), data)
            if okay:
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(result.stdout)
                self.assertFalse(parsed['guest_executed'])
                return parsed
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith('error:'), result.stderr)
            return result.stderr

    def test_inspect_never_calls_entry_or_maps_guest(self):
        report = self.run_pack(fixture())
        self.assertEqual(report['status'], 'inspected; not mapped')
        self.assertEqual(report['internal_relocations_applied'], 0)
        self.assertEqual(report['internal_relocations'], 2)

    def test_load_copies_and_relocates_without_entry_call(self):
        report = self.run_pack(fixture(), '--load')
        self.assertEqual(report['status'], 'loaded; entry not called')
        self.assertEqual(report['internal_relocations_applied'], 2)

    def test_imports_are_explicit_pending(self):
        relocations = [(BASE + 4096, IMPORT | 7, 0, 0),
                       (BASE + 4104, IMPORT | 6, 0, 0),
                       (BASE + 4112, IMPORT | 1, 1, 2)]
        report = self.run_pack(fixture(relocations, ['synthetic#lib#module', 'other#lib#module']), '--load')
        self.assertEqual(report['unresolved_import_relocations'], 3)
        self.assertEqual(len(report['unresolved_imports']), 2)
        self.assertFalse(report['executable_permissions_enabled'])

    def test_exact_libc_scope_binds_real_host_service(self):
        relocations = [(BASE + 4096, IMPORT | 7, 0, 0),
                       (BASE + 4104, IMPORT | 1, 0, 1),
                       (BASE + 4112, IMPORT | 6, 1, 0)]
        report = self.run_pack(fixture(relocations, ['Q3VBxCXhUHs#libc#libc',
                                                     'Q3VBxCXhUHs#wrong#libc']), '--load')
        self.assertEqual(report['resolved_import_relocations'], 2)
        self.assertEqual(report['unresolved_import_relocations'], 1)
        self.assertEqual(len(report['resolved_imports']), 1)
        self.assertEqual(report['unresolved_imports'][0]['name'], 'Q3VBxCXhUHs#wrong#libc')

    def test_malformed_headers_counts_and_payloads_refused(self):
        original = fixture()
        cases = [original[:55], bytearray(original)]
        cases[1][0] = 0
        for offset, value in ((16, (1 << 64) - 1), (24, 0), (24, 513 * 1024 * 1024), (32, 0),
                              (40, (1 << 64) - 1), (56 + 16, 4097),
                              (56 + 24, 8), (56 + 32, 0), (8, BASE + 8192)):
            changed = bytearray(original)
            struct.pack_into('<Q', changed, offset, value)
            cases.append(changed)
        overlapping = bytearray(original)
        struct.pack_into('<Q', overlapping, 56 + 40, BASE + 4095)
        cases.append(overlapping)
        for data in cases:
            with self.subTest(length=len(data), head=data[:56].hex()):
                self.run_pack(data, okay=False)

    def test_invalid_relocations_refused(self):
        for relocation in ((BASE + 8190, 8, 0, BASE), (BASE + 4096, 99, 0, 0),
                           (BASE + 4096, IMPORT | 8, 0, 0),
                           (BASE + 4096, IMPORT | 7, 1, 0),
                           (BASE + 4096, 8, 1, BASE),
                           (BASE + 4096, 1, BASE + 8192, 0),
                           (BASE + 4096, IMPORT | 6, 0, 1)):
            with self.subTest(relocation=relocation):
                self.run_pack(fixture([relocation], ['synthetic#lib#module']), okay=False)
        self.run_pack(fixture([(BASE + 4096, 8, 0, BASE), (BASE + 4100, 8, 0, BASE)]), okay=False)
        self.run_pack(fixture([(BASE + 4096, 8, 0, -1)]), '--load', okay=False)

    def test_import_name_terminator_utf8_padding_refused(self):
        initial = fixture([], ['synthetic#lib#module'])
        import_offset = 56 + 80
        for value in (b'x' * 128, b'\xFF' + bytes(127), b'a\0x' + bytes(125)):
            data = bytearray(initial)
            data[import_offset:import_offset + 128] = value
            self.run_pack(data, okay=False)


if __name__ == '__main__':
    unittest.main()

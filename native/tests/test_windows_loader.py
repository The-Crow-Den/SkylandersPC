# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows loader operations, guest entry and emulated guest TLS."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
# The shared format fixture consumes the executable argument once.
from test_loader import fixture, run_tls_fixture, BINARY


class WindowsLoaderTests(unittest.TestCase):
    def test_inspection_and_mapping_never_enter_guest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'synthetic.pack'
            path.write_bytes(fixture())
            for mode, status in (('--inspect', 'inspected; not mapped'),
                                 ('--load', 'loaded; entry not called')):
                result = subprocess.run([str(BINARY), mode, str(path)],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report['status'], status)
                self.assertFalse(report['guest_executed'])
                self.assertNotIn('entry-attempt', result.stderr)

    def test_guest_entry_reports_a_trap_at_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'synthetic.pack'
            path.write_bytes(fixture())  # int3 at the entry point
            types = root / 'types'
            types.write_bytes(b'')
            result = subprocess.run([str(BINARY), '--trace-start', str(path), str(types)],
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('entry-attempt', result.stderr)
            fault = next(json.loads(line) for line in result.stderr.splitlines()
                         if line.startswith('{"event":"guest-fault"'))
            self.assertTrue(fault['guest_executed'])
            entry = next(json.loads(line) for line in result.stderr.splitlines()
                         if line.startswith('{"event":"entry-attempt"'))
            self.assertEqual(fault['pc'], entry['entry'])

    def test_guest_tls_load_is_emulated_against_the_tcb(self):
        # Windows' zero FS base makes the load fault; guest_fs emulates it.
        self.assertEqual(run_tls_fixture(self), 0)

if __name__ == '__main__':
    unittest.main()

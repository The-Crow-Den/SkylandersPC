# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows loader operations and explicit refusal of unadmitted guest entry."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
# The shared format fixture consumes the executable argument once.
from test_loader import fixture, BINARY


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

    def test_unadmitted_execution_is_refused_before_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'synthetic.pack'
            path.write_bytes(fixture())
            types = root / 'types'
            types.write_bytes(b'')
            for mode in ('--run', '--trace-start'):
                result = subprocess.run([str(BINARY), mode, str(path), str(types)],
                                        capture_output=True, text=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('admitted executable/TLS rewrite profile', result.stderr)
                self.assertNotIn('entry-attempt', result.stderr)


if __name__ == '__main__':
    unittest.main()

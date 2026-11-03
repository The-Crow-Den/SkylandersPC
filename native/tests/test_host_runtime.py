# SPDX-License-Identifier: GPL-3.0-or-later
"""Real native runtime support: child faults, diagnostics and platform paths."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()


class RuntimeHostTests(unittest.TestCase):
    def run_native(self, mode, env=None):
        return subprocess.run([str(BINARY), mode], env=env, capture_output=True,
                              encoding='utf-8', errors='strict', timeout=15)

    def test_real_recovery_and_exclusive_handler_ownership(self):
        for mode in ('basic', '--recover', '--guest-recover'):
            with self.subTest(mode=mode):
                result = self.run_native(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('runtime host tests passed', result.stdout)

    def test_real_fatal_fault_and_returning_reporter(self):
        for mode in ('--fatal', '--guest-fatal', '--report-return'):
            with self.subTest(mode=mode):
                result = self.run_native(mode)
                self.assertEqual(result.returncode, 70, result.stderr)
                event = json.loads(result.stderr.splitlines()[-1])
                self.assertEqual(event['event'], 'runtime-fault')
                self.assertEqual(event['kind'], 1)
                self.assertEqual(event['pc'], event['expected_pc'])
                self.assertEqual(event['tls'], 123)
                self.assertEqual(event['native_code'], 0xc000001d if os.name == 'nt' else 4)

    @unittest.skipIf(os.name == 'nt', 'POSIX software-signal compatibility')
    def test_software_signal_still_gets_runtime_diagnostic(self):
        result = self.run_native('--software')
        self.assertEqual(result.returncode, 70, result.stderr)
        self.assertEqual(json.loads(result.stderr.splitlines()[-1])['native_code'], 4)

    def test_diagnostic_is_flushed_before_immediate_exit(self):
        result = self.run_native('--diagnostic')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, 'runtime-host-check:42:flushed\n')

    def test_diagnostic_worker_does_not_return(self):
        with subprocess.Popen([str(BINARY), '--suspend'], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, encoding='utf-8') as process:
            ready = threading.Event()
            line = []

            def read_marker():
                line.append(process.stderr.readline())
                ready.set()

            reader = threading.Thread(target=read_marker)
            reader.start()
            try:
                self.assertTrue(ready.wait(15), 'worker did not reach suspension')
                reader.join(1)
                self.assertEqual(line, ['runtime-worker-suspended\n'])
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.1)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=15)
                reader.join(1)

    def test_save_root_and_unicode_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'data_λ'
            env = os.environ.copy()
            if os.name == 'nt':
                env['LOCALAPPDATA'] = str(root)
                expected = root / 'skylanders-pc' / 'saves'
            else:
                env['XDG_DATA_HOME'] = str(root)
                env['HOME'] = directory
                expected = root / 'skylanders-pc' / 'saves'
            result = self.run_native('--save-root', env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), expected)
            self.assertFalse(root.exists())  # A lookup must not create storage.
            if os.name != 'nt':
                env['XDG_DATA_HOME'] = 'relative'
                result = self.run_native('--save-root', env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(Path(result.stdout.strip()), Path(directory) / '.local/share/skylanders-pc/saves')
            for key in ('LOCALAPPDATA', 'HOME', 'XDG_DATA_HOME'):
                env.pop(key, None)
            result = self.run_native('--save-root', env)
            self.assertEqual(result.returncode, 1, result.stderr)
            if os.name == 'nt':
                env['LOCALAPPDATA'] = 'relative'
                result = self.run_native('--save-root', env)
                self.assertEqual(result.returncode, 1, result.stderr)


if __name__ == '__main__':
    unittest.main()

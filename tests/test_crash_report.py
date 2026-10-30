# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import crash_report

HOST = {'gpu': 'Test GPU 1.0', 'distro': 'Test Linux', 'kernel': '6.0-test', 'machine': 'x86_64'}


class CrashReportTest(unittest.TestCase):
    def session(self, root, log_lines, exit_info):
        session = Path(root) / 'session'
        session.mkdir()
        (session / 'session.json').write_text(json.dumps({
            'installation': {'title_id': 'CUSA00000', 'app_version': '01.01', 'executable_sha256': 'ab' * 32,
                             'base': '/home/alice/Games/base'},
            'save_selection': {'root': '/home/alice/saves'}, 'variant': 'original', 'memory_mode': 'compact'}))
        (session / 'runtime.log').write_text('\n'.join(log_lines) + '\n')
        if exit_info is not None:
            (session / 'exit.json').write_text(json.dumps(exit_info))
        return session

    def test_report_contents_and_tail(self):
        with tempfile.TemporaryDirectory() as root:
            lines = [f'line {i}' for i in range(300)]
            lines.insert(250, '{"event":"guest-fault","signal":11,"pc":1,"address":2,"guest_executed":true}')
            session = self.session(root, lines, {'returncode': -11, 'signal': 11, 'stop_reason': 'process-exit'})
            report = crash_report.build_report(session, 128 + 11, host=HOST, revision='abc123', home='/home/alice', user='alice')
        for text in ('CUSA00000 version 01.01', 'ab' * 32, 'abc123', 'Test GPU 1.0', 'Test Linux', '6.0-test',
                     'signal 11', 'Host fault:', '"memory_mode": "compact"', 'line 299'):
            self.assertIn(text, report)
        self.assertNotIn('line 100\n', report)
        self.assertIn('Last 200 lines', report)
        self.assertNotIn('saves', report)  # Save locations are not settings.

    def test_missing_session_and_exit_code(self):
        report = crash_report.build_report(None, 1, host=HOST, revision='r', home='/home/alice', user='alice')
        self.assertIn('launcher exit code 1', report)
        with tempfile.TemporaryDirectory() as root:
            session = self.session(root, ['boom'], {'returncode': 3, 'signal': None, 'stop_reason': 'process-exit'})
            self.assertIn('exit code 3', crash_report.build_report(session, 3, host=HOST, revision='r', home='/x', user='nobody'))

    def test_redaction(self):
        text = 'open /home/alice/a and /home/bob/b and /Users/carol/c by alice; alice-tools stays; /opt/x'
        result = crash_report.redact(text, home='/home/alice', user='alice')
        for secret in ('alice;', '/home/alice', 'bob', 'carol'):
            self.assertNotIn(secret, result)
        self.assertIn('~/a', result)
        self.assertIn('/home/<user>/b', result)
        self.assertIn('by <user>;', result)
        self.assertIn('alice-tools', result)
        self.assertIn('/opt/x', result)

    def test_session_directory(self):
        out = 'x\nRuntime log: /tmp/s1/runtime.log\nRuntime log: /tmp/s2/runtime.log\nRuntime log: /tmp/s3/run'
        self.assertEqual(crash_report.session_directory(out), Path('/tmp/s2'))
        self.assertIsNone(crash_report.session_directory('nothing\n'))

    def test_fault_lines(self):
        lines = ['ok', '{"event":"fault-host-owner","file":"x","offset":1}', '{"event":"trophy-unlocked"}']
        self.assertEqual(crash_report.fault_lines(lines), [lines[1]])


if __name__ == '__main__':
    unittest.main()

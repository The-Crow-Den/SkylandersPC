# SPDX-License-Identifier: GPL-3.0-or-later
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import host_process


class AnsiSafeTest(unittest.TestCase):
    def test_unchanged_off_windows_or_ascii(self):
        self.assertEqual(host_process.ansi_safe('/home/josé/x', windows=False), '/home/josé/x')
        self.assertEqual(host_process.ansi_safe('/tmp/plain', windows=True, shorten=lambda t: 'X'), '/tmp/plain')
        self.assertEqual(host_process.ansi_safe('josé', windows=True, shorten=lambda t: 'X'), 'josé')

    def test_existing_part_shortened_and_rest_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / 'José';user.mkdir()
            shortened = {str(user): str(Path(tmp) / 'JOS~1')}
            value = host_process.ansi_safe(str(user / 'Saved Games' / 'new.csv'), windows=True, shorten=shortened.get)
            self.assertEqual(value, str(Path(tmp) / 'JOS~1' / 'Saved Games' / 'new.csv'))

    def test_left_alone_when_no_ascii_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / 'José';user.mkdir()
            self.assertEqual(host_process.ansi_safe(str(user / 'Zoë'), windows=True, shorten=lambda t: t), str(user / 'Zoë'))


if __name__ == '__main__':
    unittest.main()

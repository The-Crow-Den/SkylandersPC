# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys, tempfile, unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import launcher_install_dialog as dialog

Usage = namedtuple('Usage', 'total used free')


class SpaceTest(unittest.TestCase):
    def test_shortage_names_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / 'game.pkg';pkg.write_bytes(b'x' * 1000)
            with patch.object(dialog.shutil, 'disk_usage', return_value=Usage(0, 0, 1 << 30)), \
                 patch.object(dialog.game_library, 'directory', return_value=Path(tmp) / 'Games'):
                message = dialog.space_shortage(tmp, [('base', str(pkg))])
            self.assertIn('2.0 GB', message);self.assertIn('1.0 GB is free', message)

    def test_enough_space_and_folders_need_no_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'unpacked';folder.mkdir()
            with patch.object(dialog.shutil, 'disk_usage', return_value=Usage(0, 0, 3 << 30)), \
                 patch.object(dialog.game_library, 'directory', return_value=Path(tmp)):
                self.assertIsNone(dialog.space_shortage(tmp, [('base', str(folder))]))


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-module CLI checks using only original synthetic metadata."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_executable import sce_fixture
from test_workspace import sfo_fixture

ROOT = Path(__file__).resolve().parents[1]


class CliIntegrationTests(unittest.TestCase):
    def test_inventory_and_profile_cli_work_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / 'synthetic game'
            (game / 'sce_sys').mkdir(parents=True)
            (game / 'eboot.bin').write_bytes(sce_fixture())
            (game / 'sce_sys/param.sfo').write_bytes(sfo_fixture())
            inspected = subprocess.run([sys.executable, str(ROOT / 'tools/workspace.py'),
                                        'inventory', str(game)], cwd=root, capture_output=True,
                                       text=True, check=True, timeout=5)
            report = json.loads(inspected.stdout)
            self.assertEqual(report['imports']['count'], 1)
            self.assertEqual(report['imports']['symbols'][0]['resolution'], 'not checked')
            inventory = root / 'inventory.json'
            inventory.write_text(inspected.stdout)
            identified = subprocess.run([sys.executable, str(ROOT / 'tools/profiles.py'),
                                         'trap-team', str(inventory)], cwd=root,
                                        capture_output=True, text=True, check=True, timeout=5)
            match = json.loads(identified.stdout)
            self.assertEqual(match['status'], 'unverified')
            self.assertFalse(match['patches_allowed'])
            self.assertEqual((game / 'eboot.bin').read_bytes(), sce_fixture())


if __name__ == '__main__':
    unittest.main()

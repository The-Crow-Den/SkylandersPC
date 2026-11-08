# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import launcher_trophies
import psn_trophies


class PackagedTrophyTest(unittest.TestCase):
    def test_trap_team_names_fill_catalogue(self):
        title, rows = psn_trophies.packaged(ROOT, 'NPWR06603_00')
        self.assertEqual((len(rows), rows[0]['grade']), (47, 'P'))
        with tempfile.TemporaryDirectory() as temp:
            icons = Path(temp)/'catalogues'/'NPWR06603_00-x'/'Icons';icons.mkdir(parents=True)
            for i in rows:(icons/f'TROP{i:03}.PNG').write_bytes(b'')
            [path] = psn_trophies.write_catalogue(temp, 'NPWR06603_00', title, rows)
            self.assertEqual(launcher_trophies.read_xml(path)[1][1]['name'], 'Soda Saver')

    def test_missing_or_invalid_ids(self):
        self.assertIsNone(psn_trophies.packaged(ROOT, 'NPWR00000_00'))
        self.assertIsNone(psn_trophies.packaged(ROOT, '../x'))


if __name__ == '__main__':
    unittest.main()

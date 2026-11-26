# SPDX-License-Identifier: GPL-3.0-or-later
import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import user_data


@unittest.skipIf(os.name == 'nt', 'Linux layout')
class UserData(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.top = Path(self.temp.name)
        self.env = {'HOME': str(self.top/'home'), 'XDG_DATA_HOME': str(self.top/'data')}
        self.root = self.top/'install';(self.root/'.local').mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_location(self):
        self.assertEqual(user_data.base(self.env), self.top/'data/SkylandersPC')
        self.assertEqual(user_data.base({'HOME': '/home/player'}), Path('/home/player/.local/share/SkylandersPC'))
        self.assertEqual(user_data.base({'SKYLANDERS_DATA': '/portable'}), Path('/portable'))

    def test_install_without_marker_keeps_its_own_folders(self):
        self.assertEqual(user_data.path(self.root, 'out/figures', self.env), self.root/'out/figures')

    def test_migration_copies_verified_and_keeps_originals(self):
        old = self.top/'data/skylanders-pc/saves/CUSA00626';old.mkdir(parents=True);(old/'save.bin').write_bytes(b'progress')
        figures = self.root/'out/figures';figures.mkdir(parents=True);(figures/'a.sky').write_bytes(b'figure')
        (self.root/'.local/launcher-settings.json').write_text('{"x": 1}', encoding='utf-8')
        report = user_data.migrate(self.root, self.env)
        new = user_data.base(self.env)
        self.assertEqual((new/'saves/CUSA00626/save.bin').read_bytes(), b'progress')
        self.assertEqual((new/'figures/progress/a.sky').read_bytes(), b'figure')
        self.assertEqual(json.loads((new/'settings/launcher-settings.json').read_text(encoding='utf-8')), {'x': 1})
        self.assertTrue((old/'save.bin').is_file() and (figures/'a.sky').is_file())  # originals stay
        self.assertTrue(user_data.adopted(self.root))
        self.assertEqual(user_data.path(self.root, 'out/figures', self.env), new/'figures/progress')
        self.assertEqual(len(report['copied']), 3);self.assertEqual(report['conflicts'], [])

    def test_conflict_is_never_overwritten(self):
        new = user_data.base(self.env)/'settings';new.mkdir(parents=True);(new/'launcher-settings.json').write_text('{"kept": true}', encoding='utf-8')
        (self.root/'.local/launcher-settings.json').write_text('{"old": true}', encoding='utf-8')
        report = user_data.migrate(self.root, self.env)
        self.assertEqual(json.loads((new/'launcher-settings.json').read_text(encoding='utf-8')), {'kept': True})
        self.assertEqual(len(report['conflicts']), 1)


if __name__ == '__main__':
    unittest.main()

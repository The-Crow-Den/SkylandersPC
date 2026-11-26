# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
from tools import pc_menu_prefs

ROOT=Path(__file__).resolve().parents[1]


class PcMenuPreferenceTests(unittest.TestCase):
    def test_stored_beside_saves_outside_the_repository(self):
        path=pc_menu_prefs.path({'XDG_DATA_HOME':'/data','HOME':'/home/user'})
        self.assertEqual(path,Path('/data/SkylandersPC/pc-menu-preferences.json'))

    def test_recent_figures_rotate_and_favourites_toggle(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'prefs.json'
            for number in range(10):pc_menu_prefs.record_recent('trap-team',0,f'Figure {number}',file)
            pc_menu_prefs.record_recent('trap-team',0,'Figure 3',file)
            recent=pc_menu_prefs.load(file)['trap-team']['recent']['0']
            self.assertEqual(recent[0],'Figure 3');self.assertEqual(len(recent),pc_menu_prefs.RECENT);self.assertEqual(recent.count('Figure 3'),1)
            pc_menu_prefs.toggle_favourite('trap-team',2,'Healing Elixir',file)
            self.assertEqual(pc_menu_prefs.load(file)['trap-team']['favourites']['2'],['Healing Elixir'])
            pc_menu_prefs.toggle_favourite('trap-team',2,'Healing Elixir',file)
            self.assertEqual(pc_menu_prefs.load(file)['trap-team']['favourites']['2'],[])

    def test_invalid_input_and_corrupt_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'prefs.json'
            for title,kind,name in (('../x',0,'A'),('trap-team',1,'A'),('trap-team',0,''),('trap-team',0,'x'*97)):
                with self.assertRaises(ValueError):pc_menu_prefs.record_recent(title,kind,name,file)
            file.write_text('not json', encoding='utf-8');self.assertEqual(pc_menu_prefs.load(file),{})
            file.write_text(json.dumps({'trap-team':{'recent':{'0':['Ok',5,None],'7':['Bad']}},'BAD TITLE':{}}), encoding='utf-8')
            self.assertEqual(pc_menu_prefs.load(file),{'trap-team':{'favourites':{},'recent':{'0':['Ok']}}})

    def test_menu_has_quick_row_and_no_snapshot(self):
        page=(ROOT/'tools/pc_menu/index.html').read_text(encoding='utf-8');script=(ROOT/'tools/pc_menu/menu.js').read_text(encoding='utf-8')
        host=(ROOT/'tools/pc_overlay.py').read_text(encoding='utf-8')
        for marker in ('data-quick','data-favourite'):self.assertIn(marker,page)
        self.assertNotIn('data-snapshot',page)
        # Moving along the rail must not quit; only A/Enter does.
        self.assertIn("matches('[data-quit]')",script)
        for slot in ('toggleFavourite','placed','preferences'):
            self.assertRegex(script,rf'bridge\??\.{slot}\(');self.assertIn(f'def {slot}(',host)
        self.assertNotIn('snapshotSaves',host+script)
        # A full swapper is favourited as "Top + Bottom" and placed top first.
        self.assertIn("main.name+' + '+bottom.name",script);self.assertIn('function placeCombo(',script)


if __name__=='__main__':
    unittest.main()

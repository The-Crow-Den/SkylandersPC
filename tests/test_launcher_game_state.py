# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import os
from tools import game_library,game_prepare,launcher_game_state
from test_game_install import sfo


class RemovalTests(unittest.TestCase):
    def make(self,root,where):
        folder=root/where;(folder/'sce_sys').mkdir(parents=True)
        (folder/'sce_sys/param.sfo').write_bytes(sfo(dict(TITLE_ID='CUSA99999',CATEGORY='gd',APP_VER='01.00',CONTENT_ID='synthetic')))
        (folder/'eboot.bin').write_bytes(b'synthetic')
        return folder

    def test_linked_originals_saves_figures_settings_and_packs_are_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.make(root,'Game/original');game={'id':'title-cusa99999','title_id':'CUSA99999'}
            for name in ('saves/progress','figures/figure.sky','.local/preferences.json','out/pack/image.pack'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'keep')
            game_library.register(root)
            launcher_game_state.remove(root,game)
            self.assertEqual((source/'eboot.bin').read_bytes(),b'synthetic')
            self.assertEqual(game_library.entries(root,[]),[])
            for name in ('saves/progress','figures/figure.sky','.local/preferences.json','out/pack/image.pack'):
                self.assertEqual((root/name).read_bytes(),b'keep')

    def test_failed_removal_rolls_back_managed_files_and_manifests(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.make(root,'incoming');entry=game_library.publish(game_library.directory(root),source)
            manifest=game_library.manifest_path(game_library.directory(root),entry);before=manifest.read_bytes()
            real=game_library.write_json
            def fail(path,value):
                if Path(path).name=='removed-games.json':raise OSError('synthetic metadata failure')
                return real(path,value)
            with patch.object(game_library,'write_json',side_effect=fail),self.assertRaises(OSError):
                launcher_game_state.remove(root,{'id':'title-cusa99999','title_id':'CUSA99999'})
            self.assertEqual(manifest.read_bytes(),before);self.assertTrue(Path(entry['base_path']).is_dir())
            self.assertEqual(len(game_library.entries(root,[])),1)


class StaleHostTests(unittest.TestCase):
    def snapshot(self, error):
        entry=dict(base_path='',update_path='',base_version='01.00',update_version='01.01')
        with patch.object(game_library,'resolve_entry',return_value=entry),patch.object(game_library,'supported',return_value=True),\
             patch.object(game_prepare,'require_ready',side_effect=error),patch.object(os,'name','posix'):
            return launcher_game_state.snapshot('/x',{'id':'trap-team','name':'Trap Team'})

    def test_changed_game_host_is_rebuilt_by_play_not_repair(self):
        state=self.snapshot(game_prepare.PreparationError('Game setup needs runtime. Choose Repair in the launcher to finish setup.'))
        self.assertEqual((state['state'],state['rebuild']),('Ready',True))

    def test_outdated_setup_step_is_redone_by_play(self):
        # After a launcher update: Play runs the same setup Repair would, then starts.
        state=self.snapshot(game_prepare.PreparationError('Game setup needs pack.60-delta. Choose Repair in the launcher to finish setup.'))
        self.assertEqual((state['state'],state['rebuild']),('Ready',True))

    def test_unreadable_setup_still_needs_repair(self):
        state=self.snapshot(OSError('Permission denied'))
        self.assertEqual((state['state'],state['rebuild']),('Needs repair',False))
        state=self.snapshot(game_prepare.PreparationError('Game setup is running. It will be ready when setup finishes.'))
        self.assertEqual((state['state'],state['rebuild']),('Needs repair',False))

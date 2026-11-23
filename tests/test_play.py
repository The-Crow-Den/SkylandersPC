# SPDX-License-Identifier: GPL-3.0-or-later
import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import play, launcher_model


class Play(unittest.TestCase):
    def test_uses_the_launchers_saved_settings_and_mods(self):
        game = {'id': 'trap-team', 'name': 'Trap Team', 'installation': 'CUSA00626@01.01', 'settings': {'resolution': '1440p'}, 'mod_settings': {}}
        with patch.object(play.launcher_model, 'load', return_value=dict(launcher_model.DEFAULTS)), \
             patch.object(play.launcher_mods, 'selection', return_value={'sixty-fps': True}) as mods, \
             patch.object(play.launcher_model, 'command', return_value=['python', 'run_session.py']) as command:
            self.assertEqual(play.command(Path('/install'), game, 'python'), ['python', 'run_session.py'])
        value = command.call_args.args[2]
        self.assertEqual(value['resolution'], '1440p')  # the game's own setting wins
        self.assertEqual(command.call_args.kwargs['mods'], {'sixty-fps': True})
        mods.assert_called_once()

    def test_unknown_game_is_explained(self):
        with patch.object(play.launcher_library, 'load', return_value={'games': [{'id': 'trap-team', 'name': 'Trap Team'}]}), \
             patch.object(play.launcher_library, 'sync_installations'):
            with self.assertRaisesRegex(SystemExit, 'not installed'):play.find_game(Path('/install'), 'trap-team')
            with self.assertRaisesRegex(SystemExit, 'Unknown game'):play.find_game(Path('/install'), 'giants')


if __name__ == '__main__':
    unittest.main()

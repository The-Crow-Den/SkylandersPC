# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest

from tools import launcher_model as model
from tools.run_session import exclusive_session


class LauncherModelTests(unittest.TestCase):
    def test_shared_session_lock_refuses_overlap_and_releases_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.lock'
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                with exclusive_session(path):
                    with self.assertRaisesRegex(ValueError, 'Another Trap Team session'):
                        with exclusive_session(path):
                            self.fail('second session acquired the same save lock')
                    raise RuntimeError('synthetic failure')
            with exclusive_session(path):
                self.assertTrue(path.is_file())

    def test_launch_preserves_paths_as_arguments_and_explicit_policy(self):
        value = dict(model.DEFAULTS, figure='/figures/Dino Rang $(example).sky',
                     unlock_nightmare=True, level_events=True)
        argv = model.command('/project with spaces', '/python', value)
        self.assertEqual(argv[:2], ['/python', '/project with spaces/tools/run_session.py'])
        self.assertEqual(argv[argv.index('--figure') + 1], value['figure'])
        self.assertEqual(argv[argv.index('--frame-policy')+1],'auto')
        self.assertIn('--no-mangohud', argv)
        self.assertIn('--unlock-nightmare', argv)
        self.assertIn('--level-events', argv)
        self.assertIn('--motion-blur', argv)
        self.assertEqual(argv[argv.index('--frame-limit') + 1], '30')
        self.assertNotIn('--seconds', argv)

    def test_gameplay_mod_switches_are_forwarded_explicitly(self):
        argv=model.command('/project','python',model.DEFAULTS,mods={'element-gates':True,'traptanium':False})
        self.assertIn('--element-gates',argv);self.assertIn('--no-traptanium',argv)
        for enabled, flag in ((True,'--unlock-expansions'),(False,'--no-unlock-expansions')):
            argv=model.command('/project','python',model.DEFAULTS,mods={'unlock-expansions':enabled})
            self.assertIn(flag,argv)
        for enabled, flag in ((True,'--replay-expansion-intros'),(False,'--no-replay-expansion-intros')):
            argv=model.command('/project','python',model.DEFAULTS,mods={'replay-expansion-intros':enabled})
            self.assertIn(flag,argv)
        with self.assertRaises(ValueError):model.command('/project','python',model.DEFAULTS,mods={'any-portal':True})
        with self.assertRaises(ValueError):model.command('/project','python',model.DEFAULTS,mods={'traptanium':'yes'})

    def test_legacy_game_mod_preferences_keep_their_values(self):
        from tools import launcher_mods, launcher_library
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            library=launcher_library.defaults()
            game=next(g for g in library['games'] if g['id']=='trap-team')
            game['mods']={'element-gates':True,'traptanium':False}
            path=root/'library.json';launcher_library.save(path,library)
            library=launcher_library.load(path)
            game=next(g for g in library['games'] if g['id']=='trap-team')
            selected=launcher_mods.selection(root,game)
            self.assertEqual(selected,{'element-gates':True,'traptanium':False,'unlock-expansions':False,'replay-expansion-intros':False})
            selected['unlock-expansions']=True
            game['mods']=selected;launcher_library.save(path,library)
            game=next(g for g in launcher_library.load(path)['games'] if g['id']=='trap-team')
            self.assertTrue(game['mods']['unlock-expansions'])
            self.assertIn('--unlock-expansions',model.command(root,'python',model.DEFAULTS,mods=selected))

    def test_bad_settings_refused_without_replacing_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            model.save(path, model.DEFAULTS)
            before = path.read_bytes()
            for patch in ({'frame_limit': True}, {'mangohud': 'yes'},
                          {'resolution': '8k'}, {'portal_volume': 101},
                          {'figure': 'bad\0path'}, {'extra': True}):
                with self.assertRaises(ValueError):
                    model.save(path, dict(model.DEFAULTS, **patch))
                self.assertEqual(path.read_bytes(), before)
            self.assertEqual(model.load(path), model.DEFAULTS)
            path.write_text(json.dumps({'resolution': '1080p'}))
            with self.assertRaises(ValueError):
                model.load(path)

    def test_old_preferences_migrate_without_losing_graphics(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'old.json'
            old=dict(model.DEFAULTS, resolution='1600p', frame_limit=60)
            old.pop('frame_policy')
            path.write_text(json.dumps(old))
            loaded=model.load(path)
            self.assertEqual(loaded['frame_policy'],'auto')
            self.assertEqual(loaded['resolution'],'1600p')
            self.assertEqual(loaded['frame_limit'],60)

    def test_readiness_reports_missing_build_and_devices_are_only_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(len(model.missing_files(root)), 5)
            device = root / 'js0/device/name'
            device.parent.mkdir(parents=True)
            device.write_text('DualSense Edge\n')
            self.assertEqual(model.controllers(root), ['DualSense Edge'])
            self.assertEqual(model.controllers(root / 'missing'), [])


if __name__ == '__main__':
    unittest.main()

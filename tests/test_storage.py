# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import storage, launcher_model, crash_report


class StorageTest(unittest.TestCase):
    def test_hard_links_count_once_and_clear_keeps_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cache = root / 'out/native-gpu-user/cache'; (cache / 'CUSA').mkdir(parents=True)
            (cache / 'CUSA/a.bin').write_bytes(b'x' * 100); os.link(cache / 'CUSA/a.bin', cache / 'b.bin')
            self.assertEqual(storage.size(cache), 100)
            self.assertEqual(storage.clear(root, 'shaders'), 100)
            self.assertTrue(cache.is_dir()); self.assertEqual(list(cache.iterdir()), [])

    def test_games_and_saves_are_not_clearable(self):
        for key in ('games', 'saves'):
            with self.assertRaises(ValueError):storage.clear('/nonexistent', key)

    def test_shader_setting(self):
        self.assertTrue(launcher_model.DEFAULTS['save_shaders'])
        with tempfile.TemporaryDirectory() as tmp:
            value = dict(launcher_model.DEFAULTS, save_shaders=False)
            argv = launcher_model.command(tmp, 'python', value)
            self.assertIn('--no-shader-cache', argv)
            self.assertNotIn('--no-shader-cache', launcher_model.command(tmp, 'python', launcher_model.DEFAULTS))

    def test_old_preferences_gain_shader_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'p.json'
            old = {k: v for k, v in launcher_model.DEFAULTS.items() if k != 'save_shaders'}
            path.write_text(__import__('json').dumps(old), encoding='utf-8')
            self.assertTrue(launcher_model.load(path)['save_shaders'])

    def test_windows_profile_paths_redacted(self):
        text = crash_report.redact(r'"C:\\Users\\Alice\\x" D:/Users/bob/y', home='/none', user='')
        self.assertNotIn('Alice', text); self.assertNotIn('bob', text)


if __name__ == '__main__':
    unittest.main()


class CacheLimitTest(unittest.TestCase):
    def test_limit_passed_and_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = launcher_model.command(tmp, 'python', dict(launcher_model.DEFAULTS, cache_limit_gb=32))
            self.assertEqual(argv[argv.index('--cache-limit-gb') + 1], '32')
        with self.assertRaises(ValueError):launcher_model.validate(dict(launcher_model.DEFAULTS, cache_limit_gb=3))

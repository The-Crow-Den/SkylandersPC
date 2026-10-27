# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic checks of the standalone launcher AppImage entry point (no image is built)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPRUN = ROOT / 'tools/appimage/AppRun.sh'


class AppRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.appdir = self.base / 'mount'
        python = self.appdir / 'usr/python/bin/python3'
        python.parent.mkdir(parents=True)
        # Stands in for the bundled interpreter: reports where and how it was started.
        python.write_text('#!/bin/sh\necho "cwd=$PWD"\necho "path=${PYTHONPATH-unset}"\nfor a; do echo "arg=$a"; done\n')
        python.chmod(0o755)
        self.repo = self.make_repo(self.base / 'games/SkylandersPS4')

    def tearDown(self):
        self.temp.cleanup()

    def make_repo(self, path):
        (path / 'tools').mkdir(parents=True)
        for name in ('launcher.py', 'run_session.py'):
            (path / 'tools' / name).write_text('')
        return path

    def run_apprun(self, *args, image=None, **extra):
        env = {key: value for key, value in os.environ.items() if key not in ('SKYLANDERS_ROOT', 'APPIMAGE')}
        env.update(APPDIR=str(self.appdir), PYTHONPATH='/host', **extra)
        if image is not None:
            env['APPIMAGE'] = str(image)
        return subprocess.run(['sh', str(APPRUN), *args], env=env, capture_output=True, text=True)

    def test_finds_checkout_beside_the_image(self):
        result = self.run_apprun('--flag', image=self.base / 'games/Launcher.AppImage')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('cwd=' + str(self.repo), result.stdout)
        self.assertIn('arg=' + str(self.repo / 'tools/launcher.py'), result.stdout)
        self.assertIn('arg=--flag', result.stdout)
        self.assertIn('path=unset', result.stdout)

    def test_finds_checkout_from_inside_it(self):
        dist = self.repo / 'out/dist'; dist.mkdir(parents=True)
        result = self.run_apprun(image=dist / 'Launcher.AppImage')
        self.assertIn('cwd=' + str(self.repo), result.stdout)

    def test_falls_back_to_recorded_build_checkout(self):
        record = self.appdir / 'usr/share/skylanders/root'
        record.parent.mkdir(parents=True); record.write_text(str(self.repo) + '\n')
        elsewhere = self.base / 'elsewhere'; elsewhere.mkdir()
        result = self.run_apprun(image=elsewhere / 'Launcher.AppImage')
        self.assertIn('cwd=' + str(self.repo), result.stdout)

    def test_explicit_root_wins_and_is_validated(self):
        other = self.make_repo(self.base / 'other')
        result = self.run_apprun(image=self.base / 'games/Launcher.AppImage', SKYLANDERS_ROOT=str(other))
        self.assertIn('cwd=' + str(other), result.stdout)
        result = self.run_apprun(image=self.base / 'games/Launcher.AppImage', SKYLANDERS_ROOT=str(self.base))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SKYLANDERS_ROOT', result.stderr)

    def test_missing_checkout_is_reported(self):
        elsewhere = self.base / 'elsewhere'; elsewhere.mkdir()
        result = self.run_apprun(image=elsewhere / 'Launcher.AppImage')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Cannot find the SkylandersPS4 checkout', result.stderr)

    def test_python_passthrough_skips_checkout_lookup(self):
        elsewhere = self.base / 'elsewhere'; elsewhere.mkdir()
        result = self.run_apprun('--python', '-c', 'pass', image=elsewhere / 'Launcher.AppImage')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('arg=')], ['arg=-c', 'arg=pass'])


if __name__ == '__main__':
    unittest.main()

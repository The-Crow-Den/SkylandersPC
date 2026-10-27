# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
from pathlib import Path
import unittest

from tools.pc_settings import validate_settings, load_settings, save_settings


class PcSettingsTests(unittest.TestCase):
    def settings(self):
        return dict(resolution='1600p', quality='performance', fullscreen=True,
                    fps_counter=False, frame_limit=60)

    def test_round_trip_and_missing_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.json'
            self.assertEqual(load_settings(path), {})
            save_settings(path,self.settings())
            self.assertEqual(load_settings(path),self.settings())
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_policy_round_trip_preserves_manual_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            value=dict(self.settings(),frame_policy='auto',controller_layout='keyboard-and-pad',controller_glyphs='nintendo')
            save_settings(path,value)
            self.assertEqual(load_settings(path),value)
            value['frame_policy']='manual'
            save_settings(path,value)
            self.assertEqual(load_settings(path),value)

    def test_restart_requests_accept_only_supported_choices(self):
        for key,value in [('resolution','../other'),('quality','ultra'),
                          ('fullscreen',1),('fps_counter','yes'),('frame_limit',True),
                          ('frame_limit',1000),('controller_glyphs','unknown'),('controller_glyphs',True),('controller_layout','unknown'),('frame_policy','unknown'),('frame_policy',True),('executable','/bin/false')]:
            candidate = self.settings()
            candidate[key] = value
            with self.assertRaises(ValueError):
                validate_settings(candidate)

# SPDX-License-Identifier: GPL-3.0-or-later
"""The optional HTML overlay falls back to the host's own menu (synthetic; no game or display)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import overlay_session


class OverlaySessionTests(unittest.TestCase):
    def test_native_menu_leaves_environment_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            environment = {'SKY_PC_WEB_MENU': '0', 'KEEP': '1'}
            with overlay_session.html_overlay(temp, temp, environment) as runtime:
                self.assertEqual(runtime, environment)
            self.assertFalse((Path(temp) / 'pc-overlay-status.json').exists())

    def test_missing_webengine_falls_back_to_native_menu(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(overlay_session.importlib.util, 'find_spec', return_value=None), \
                patch.object(overlay_session.shutil, 'which', return_value=None), \
                patch.object(overlay_session.subprocess, 'Popen') as popen:
            with overlay_session.html_overlay(temp, temp, {'SKY_PC_WEB_MENU': '1'}) as runtime:
                self.assertNotIn('SKY_PC_OVERLAY_DIR', runtime)
            popen.assert_not_called()
            status = json.loads((Path(temp) / 'pc-overlay-status.json').read_text())
            self.assertEqual((status['requested'], status['active']), ('web', 'native'))

    def test_trimmed_launcher_uses_available_system_webengine(self):
        with patch.object(overlay_session.importlib.util,'find_spec',return_value=None), \
                patch.object(overlay_session.sys,'executable','/bundle/python3'), \
                patch.object(overlay_session.shutil,'which',return_value='/usr/bin/python3'), \
                patch.object(overlay_session.subprocess,'run') as probe:
            probe.return_value.returncode=0
            self.assertEqual(overlay_session.overlay_python({'PATH':'/usr/bin'}),'/usr/bin/python3')
            self.assertEqual(probe.call_args.args[0][:2],['/usr/bin/python3','-c'])
            self.assertEqual(probe.call_args.kwargs['timeout'],4)

    def test_system_webengine_probe_sees_user_site_packages(self):
        bundle={'PATH':'/usr/bin','PYTHONNOUSERSITE':'1','PYTHONHOME':'/bundle','QT_PLUGIN_PATH':'/bundle/qt','HOME':'/home/player'}
        with patch.object(overlay_session.importlib.util,'find_spec',return_value=None), \
                patch.object(overlay_session.sys,'executable','/bundle/python3'), \
                patch.object(overlay_session.shutil,'which',return_value='/usr/bin/python3'), \
                patch.object(overlay_session.subprocess,'run') as probe:
            probe.return_value.returncode=0
            overlay_session.overlay_python(bundle)
        env=probe.call_args.kwargs['env']
        for key in ('PYTHONNOUSERSITE','PYTHONHOME','QT_PLUGIN_PATH'):self.assertNotIn(key,env)
        self.assertEqual((env['HOME'],probe.call_args.kwargs['cwd']),('/home/player','/'))
        self.assertNotIn('-I',probe.call_args.args[0]);self.assertNotIn('-s',probe.call_args.args[0])

    def test_failed_system_probe_is_bounded_and_deduplicated(self):
        with patch.object(overlay_session.importlib.util,'find_spec',return_value=None), \
                patch.object(overlay_session.sys,'executable','/bundle/python3'), \
                patch.object(overlay_session.shutil,'which',return_value='/usr/bin/python3'), \
                patch.object(overlay_session.subprocess,'run',side_effect=overlay_session.subprocess.TimeoutExpired('python3',4)) as probe:
            with self.assertRaisesRegex(RuntimeError,'WebEngine is unavailable'):
                overlay_session.overlay_python({'PATH':'/usr/bin'})
            self.assertEqual(probe.call_count,1)


if __name__ == '__main__':
    unittest.main()

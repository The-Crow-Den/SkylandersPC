# SPDX-License-Identifier: GPL-3.0-or-later
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import portal_devices, launcher_model


class PortalAutomaticTest(unittest.TestCase):
    def test_automatic_prefers_accessible_hid(self):
        portals = [{'id': 'xbox:1-2', 'family': 'xbox360', 'accessible': True},
                   {'id': 'hid:/dev/hidraw3', 'family': 'hid', 'accessible': False},
                   {'id': 'hid:/dev/hidraw4', 'family': 'hid', 'accessible': True}]
        self.assertEqual(portal_devices.automatic(portals)['id'], 'hid:/dev/hidraw4')
        self.assertIsNone(portal_devices.automatic(portals[:2]))

    def test_automatic_passes_figures_for_virtual_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = dict(launcher_model.DEFAULTS, portal_device='auto', figure='/x/spyro.sky')
            argv = launcher_model.command(tmp, 'python', value)
            self.assertIn('--figure', argv)
            self.assertEqual(argv[argv.index('--portal-device') + 1], 'auto')

    def test_udev_rule_installer_passes_rule_as_argument(self):
        command = portal_devices.install_rule_command()
        if command:
            self.assertEqual(command[0], 'pkexec'); self.assertEqual(command[-1], portal_devices.UDEV_RULE)


if __name__ == '__main__':
    unittest.main()

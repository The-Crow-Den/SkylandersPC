# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import portal_devices  # noqa: E402
import launcher_model as model  # noqa: E402


def fake_sysfs(root, hid=(), usb=()):
    for name, hid_id in hid:
        device = root / 'class/hidraw' / name / 'device'
        device.mkdir(parents=True)
        (device / 'uevent').write_text(f'HID_ID={hid_id}\nHID_NAME=Portal\n')
    for name, vendor, product in usb:
        device = root / 'bus/usb/devices' / name
        device.mkdir(parents=True)
        for key, value in (('idVendor', vendor), ('idProduct', product), ('busnum', '3'), ('devnum', '7')):
            (device / key).write_text(value + '\n')


class PortalDevicesTest(unittest.TestCase):
    def test_lists_hid_and_xbox_portals_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_sysfs(root, hid=[('hidraw4', '0003:00001430:00000150'), ('hidraw5', '0003:0000054C:00000DF2'),
                                  ('hidraw6', '0005:00001430:00000150')],
                       usb=[('3-2', '1430', '1f17'), ('3-3', '1430', '0150'), ('3-4', '054c', '0df2')])
            portals = portal_devices.list_portals(root)
        self.assertEqual([p['id'] for p in portals], ['hid:/dev/hidraw4', 'xbox:3-7'])
        self.assertEqual([p['family'] for p in portals], ['hid', 'xbox360'])

    def test_no_sysfs_means_no_portals(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(portal_devices.list_portals(folder), [])

    def test_choices(self):
        for value in ('virtual', 'auto', 'hid:/dev/hidraw3', 'xbox:3-7'):
            self.assertTrue(portal_devices.valid_choice(value))
        for value in ('', 'hid:/etc/passwd', 'virtual\0', 3):
            self.assertFalse(portal_devices.valid_choice(value))
        self.assertIn('udev', portal_devices.access_help())
        self.assertIn('ATTRS{idProduct}=="0150"', portal_devices.UDEV_RULE)

    def test_launcher_passes_the_chosen_portal(self):
        argv = model.command('/project', 'python', dict(model.DEFAULTS, portal_device='hid:/dev/hidraw4', figure='/f.sky'))
        self.assertEqual(argv[argv.index('--portal-device') + 1], 'hid:/dev/hidraw4')
        self.assertNotIn('--figure', argv)  # Starting figures belong to the virtual portal.
        self.assertNotIn('--portal-device', model.command('/project', 'python', model.DEFAULTS))
        with self.assertRaises(ValueError):
            model.validate(dict(model.DEFAULTS, portal_device='usb:anything'))

    def test_old_settings_default_to_the_virtual_portal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            import json
            path.write_text(json.dumps({k: v for k, v in model.DEFAULTS.items() if k != 'portal_device'}))
            self.assertEqual(model.load(path)['portal_device'], 'virtual')

    def test_transcript_has_no_figure_contents(self):
        lines = (ROOT / 'native/tests/data/portal_transcript_hid.txt').read_text().splitlines()
        reports = [line[2:].split() for line in lines if line[:2] in ('> ', '< ')]
        self.assertTrue(reports)
        self.assertFalse([r for r in reports if r[0] in ('51', '57') and len(r) > 3])  # No block data.


if __name__ == '__main__':
    unittest.main()

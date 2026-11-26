# SPDX-License-Identifier: GPL-3.0-or-later
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import portal_report

# Synthetic Xbox 360-style descriptors: device, config, vendor interface, two interrupt endpoints.
DEVICE = bytes([18,1,0,2,0xff,0xff,0xff,64,0x30,0x14,0x17,0x1f,0,1,1,2,3,1])
CONFIG = bytes([9,2,32,0,1,1,0,0x80,250])
INTERFACE = bytes([9,4,0,0,2,0xff,0x5d,1,0])
ENDPOINTS = bytes([7,5,0x81,3,32,0,1, 7,5,0x02,3,32,0,1])


class PortalReport(unittest.TestCase):
    def test_reads_fake_sysfs_without_serial(self):
        with tempfile.TemporaryDirectory() as root:
            node = Path(root)/'bus/usb/devices/3-2';node.mkdir(parents=True)
            for name, value in dict(idVendor='1430', idProduct='1f17', product='Portal', manufacturer='Activision',
                                    serial='SECRET', busnum='3', devnum='2', speed='12').items():
                (node/name).write_text(value+'\n', encoding='utf-8')
            (node/'descriptors').write_bytes(DEVICE+CONFIG+INTERFACE+ENDPOINTS)
            data = portal_report.report(sysfs=root)
        device = data['portals'][0]
        self.assertEqual(device['family'], 'xbox360')
        self.assertEqual(device['parsed']['device']['product'], '1f17')
        self.assertEqual([e['address'] for e in device['parsed']['interfaces'][0]['endpoints']], ['81', '02'])
        self.assertNotIn('SECRET', str(data))
        self.assertNotIn('node', device)

    def test_probe_never_reads_figures(self):
        source = Path(portal_report.__file__).read_text(encoding='utf-8')
        self.assertNotIn("b'Q'", source);self.assertNotIn("b'W'", source)


if __name__ == '__main__':
    unittest.main()

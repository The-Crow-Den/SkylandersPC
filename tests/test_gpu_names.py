# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import tempfile
import unittest
from tools import run_session


PCI_IDS = """# comment
10de  NVIDIA Corporation
\t2c59  GB203M / GN22-X11 [GeForce RTX 5080 Max-Q / Mobile]
\t\t1043 1234  Some subsystem
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t150e  Strix [Radeon 880M / 890M]
8086  Intel Corporation
\t1234  Plain Name Graphics
"""


class GpuNameTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory();root = Path(self.folder.name)
        self.ids = root/'pci.ids';self.ids.write_text(PCI_IDS)
        self.devices = root/'devices'
        for slot, (klass, vendor, device) in enumerate([('0x030000', '0x10de', '0x2c59'), ('0x038000', '0x1002', '0x150e'),
                                                        ('0x020000', '0x8086', '0x9999'), ('0x030000', '0x8086', '0x1234')]):
            path = self.devices/f'0000:0{slot}:00.0';path.mkdir(parents=True)
            for name, value in (('class', klass), ('vendor', vendor), ('device', device)):(path/name).write_text(value + '\n')

    def tearDown(self):
        self.folder.cleanup()

    def test_display_adapters_are_named_from_pci_ids(self):
        names = run_session.gpu_names(self.devices, (self.ids,))
        self.assertEqual(names, {'nvidia': ['NVIDIA GeForce RTX 5080 Max-Q / Mobile'], 'amd': ['AMD Radeon 880M / 890M'],
                                 'intel': ['Intel Plain Name Graphics']})  # the network card (class 0x02) is ignored

    def test_label_falls_back_to_the_maker(self):
        self.assertEqual(run_session.gpu_label('amd', {}), 'AMD')
        unknown = run_session.gpu_names(self.devices, (Path(self.folder.name)/'missing.ids',))
        self.assertEqual(unknown['nvidia'], ['NVIDIA GPU'])
        self.assertEqual(run_session.gpu_label('nvidia', {'nvidia': ['A', 'B']}), 'A + B')


if __name__ == '__main__':
    unittest.main()

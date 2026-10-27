# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from types import SimpleNamespace
from tools.fps_timing_audit import source_address, audit


class TimingAuditTests(unittest.TestCase):
    def image(self, regions):
        return SimpleNamespace(data=bytes(1024), regions=regions, programs=[
            dict(type=1, offset=64, filesz=32, vaddr=0x400000)])

    def test_self_physical_offset_is_not_elf_offset(self):
        self.assertEqual(source_address(self.image([(64, 32, 512)]), 520, 4), 0x400008)

    def test_elf_mapping(self):
        self.assertEqual(source_address(self.image(None), 72, 4), 0x400008)

    def test_unmapped_and_crossing_ranges_refused(self):
        for offset, size in ((511, 4), (541, 4), (544, 1)):
            with self.assertRaises(ValueError):
                source_address(self.image([(64, 32, 512)]), offset, size)

    def test_ambiguous_mapping_refused(self):
        with self.assertRaises(ValueError):
            source_address(self.image([(64, 32, 512)] * 2), 520, 4)

    def test_foreign_build_refused(self):
        with self.assertRaisesRegex(ValueError, 'exact US'):
            audit(b'foreign executable', {})

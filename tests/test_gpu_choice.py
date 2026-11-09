# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import run_session


class GpuChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.folder = Path(self.temp.name)
        for name in ('nvidia_icd.json', 'radeon_icd.x86_64.json', 'lvp_icd.json'):(self.folder/name).write_text('{}')

    def tearDown(self):self.temp.cleanup()

    def choose(self, choice, problem=''):return run_session.choose_gpu(choice, self.folder, problem)

    def test_listing_skips_software(self):
        self.assertEqual(run_session.installed_gpus(self.folder), ['nvidia', 'amd'])

    def test_automatic_prefers_working_nvidia(self):
        self.assertEqual(self.choose('auto'), (self.folder/'nvidia_icd.json', None))

    def test_broken_nvidia_falls_back_to_amd(self):
        manifest, warning = self.choose('auto', 'reboot')
        self.assertEqual(manifest.name, 'radeon_icd.x86_64.json'); self.assertIn('reboot', warning)
        manifest, warning = self.choose('nvidia', 'reboot')
        self.assertEqual(manifest.name, 'radeon_icd.x86_64.json'); self.assertIn('reboot', warning)

    def test_explicit_and_missing_choices(self):
        self.assertEqual(self.choose('amd')[0].name, 'radeon_icd.x86_64.json')
        manifest, warning = self.choose('intel')
        self.assertEqual(manifest.name, 'nvidia_icd.json'); self.assertIn('Intel', warning)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import asset_cache


class PruneTests(unittest.TestCase):
    def entry(self, cache, name, size, used):
        folder = cache/(name*64); folder.mkdir()
        (folder/'asset').write_bytes(b'x'*size); (folder/'manifest.json').write_text('{}', encoding='utf-8')
        os.utime(folder/'manifest.json', (used, used)); return folder

    def test_old_and_over_budget_entries_go_current_ones_stay(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp); now = 1_000_000_000
            old = self.entry(cache, 'a', 10, now - 30*86400)
            recent = self.entry(cache, 'b', 10, now - 86400)
            older_recent = self.entry(cache, 'c', 10, now - 2*86400)
            current = self.entry(cache, 'd', 50, now)
            freed = asset_cache.prune(cache, now - 1, max_bytes=65, now=now)
            self.assertFalse(old.exists()); self.assertFalse(older_recent.exists())
            self.assertTrue(recent.exists()); self.assertTrue(current.exists())
            self.assertEqual(freed, 4 + 20)  # manifests are 2 bytes each

    def test_session_entries_survive_any_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp); now = 1_000_000_000
            current = self.entry(cache, 'e', 100, now)
            asset_cache.prune(cache, now - 1, max_bytes=0, now=now)
            self.assertTrue(current.exists())


if __name__ == '__main__':
    unittest.main()

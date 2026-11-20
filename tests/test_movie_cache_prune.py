# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import movie_audio


class MovieCachePruneTest(unittest.TestCase):
    def test_oldest_removed_first_and_current_session_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            for name, age in (('old.mov', 300), ('mid.mov', 200), ('new.mov', 100), ('now.mov', 0)):
                (cache / name).write_bytes(b'x' * 10); os.utime(cache / name, (1000 - age,) * 2)
            freed = movie_audio.prune_cache(cache, used_since=950, max_bytes=15)
            self.assertEqual(sorted(p.name for p in cache.iterdir()), ['now.mov'])
            self.assertEqual(freed, 30)

    def test_under_cap_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.mov').write_bytes(b'x')
            self.assertEqual(movie_audio.prune_cache(tmp, used_since=0, max_bytes=10), 0)


if __name__ == '__main__':
    unittest.main()

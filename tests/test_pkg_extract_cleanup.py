import sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import pkg_extract


class ExtractCleanupTest(unittest.TestCase):
    def test_failed_extract_removes_partial_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'out'
            def boom(pkg, destination, keys, progress):
                (destination / 'sce_sys').mkdir(parents=True); (destination / 'sce_sys/x').write_text('partial')
                raise ValueError('bad pkg')
            with mock.patch.object(pkg_extract, '_extract', boom):
                with self.assertRaises(ValueError):pkg_extract.extract(Path(tmp) / 'a.pkg', dest)
            self.assertFalse(dest.exists())


if __name__ == '__main__':
    unittest.main()

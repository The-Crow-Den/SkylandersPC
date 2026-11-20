import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import updater


class UpdaterTest(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(updater.newer('v0.10.0', '0.9.9'))
        self.assertFalse(updater.newer('v0.1.0', '0.1.0'))
        self.assertFalse(updater.newer('nightly', '0.1.0'))

    def test_install_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(updater.install_kind(tmp), 'manual')
            (Path(tmp) / '.git').mkdir()
            self.assertEqual(updater.install_kind(tmp), 'git')

    def test_git_refuses_dirty_tree(self):
        run = lambda args, **k: SimpleNamespace(returncode=0, stdout=' M tools/x.py\n', stderr='')
        with self.assertRaises(ValueError):updater.update_git('/repo', run)


if __name__ == '__main__':
    unittest.main()

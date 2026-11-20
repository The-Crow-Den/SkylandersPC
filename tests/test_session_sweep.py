import os, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import run_session


class SessionSweepTest(unittest.TestCase):
    def test_removes_dead_and_old_keeps_live_and_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live, dead, old, recent = (root / n for n in ('live', 'dead', 'old', 'recent'))
            for d in (live, dead, old, recent):(d / 'game').mkdir(parents=True)
            held = run_session.hold_session(live); self.addCleanup(held.close)
            run_session.hold_session(dead).close()  # its game exited without cleaning up
            os.utime(old, (time.time() - 2 * 86400,) * 2)
            removed = run_session.sweep_sessions(root)
            self.assertEqual(sorted(removed), ['dead', 'old'])
            self.assertTrue(live.exists() and recent.exists())


if __name__ == '__main__':
    unittest.main()

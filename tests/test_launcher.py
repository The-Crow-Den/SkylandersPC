# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location('launcher_workspace', Path(__file__).resolve().parents[1] / 'tools/workspace.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class LauncherTests(unittest.TestCase):
    def test_spawn_error_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = w.execute([str(root / 'missing-runtime')], root, 1)
            self.assertEqual(result['reason'], 'spawn-error')
            self.assertIsNone(result['returncode'])
            self.assertFalse(result['gameplay_verified'])
            self.assertEqual(json.loads((root / 'result.json').read_text()), result)

    def test_interrupt_still_kills_and_reaps_child(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock(pid=12345, returncode=-signal.SIGKILL)
            process.wait.side_effect = [KeyboardInterrupt(), subprocess.TimeoutExpired('test', 3), -signal.SIGKILL]
            with patch.object(w.subprocess, 'Popen', return_value=process), patch.object(w.os, 'killpg') as kill:
                result = w.execute(['synthetic'], Path(directory), 1)
            self.assertEqual(result['reason'], 'interrupted')
            self.assertEqual(result['returncode'], -signal.SIGKILL)
            self.assertEqual(kill.call_args_list[-1].args, (12345, signal.SIGKILL))
            self.assertEqual(process.wait.call_count, 3)

    def test_invalid_timeout_does_not_start_process(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(w.subprocess, 'Popen') as spawn:
            for timeout in (0, 86401, True, 1.5):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    w.execute(['synthetic'], Path(directory), timeout)
            spawn.assert_not_called()

    def test_environment_keeps_home_and_routes_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = w.runtime_environment(root)
            self.assertEqual(result.get('HOME'), os.environ.get('HOME'))
            for variable in ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'TMPDIR'):
                self.assertTrue(Path(result[variable]).is_dir())
                Path(result[variable]).relative_to(root)
            for user in ('1000', '1001', '1002', '1003'):
                for folder in ('savedata', 'trophy', 'inputs'):
                    self.assertTrue((Path(result['XDG_DATA_HOME']) / 'shadPS4/home' / user / folder).is_dir())

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process-state check')
    def test_exited_parent_does_not_leave_running_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = ('import os,signal,time; from pathlib import Path; '
                     'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                     'Path("child.pid").write_text(str(os.getpid())); time.sleep(30)')
            parent = ('import subprocess,sys,time; from pathlib import Path; '
                      f'subprocess.Popen([sys.executable,"-c",{child!r}]); '
                      '\nwhile not Path("child.pid").exists(): time.sleep(0.01)')
            result = w.execute([sys.executable, '-c', parent], root, 5)
            self.assertEqual(result['returncode'], 0)
            pid = int((root / 'child.pid').read_text())
            # A killed orphan can remain a zombie until PID 1 reaps it; it must
            # no longer execute. Poll only for the signal to be delivered.
            import time
            deadline = time.monotonic() + 1
            while True:
                try:
                    state = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0]
                except FileNotFoundError:
                    break
                if state == 'Z':
                    break
                if time.monotonic() >= deadline:
                    self.fail(f'descendant {pid} still running: {state}')
                time.sleep(0.01)

    def test_session_claim_and_final_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / 'out/sessions/test'
            session.mkdir(parents=True)
            (session / 'logs').mkdir()
            binary = root / 'runtime'
            binary.write_bytes(b'synthetic')
            inventory = {'metadata': {}, 'executable': {}, 'modules': []}
            w.write_json(session / 'inventory.json', inventory)
            manifest = {'status': 'prepared; not launched', 'runtime_sha256': w.digest(binary), 'game_root': str(root / 'game')}
            w.write_json(session / 'session.json', manifest)
            with patch.object(w, 'ROOT', root), patch.object(w, 'pinned_runtime', return_value=binary), patch.object(w, 'inventory', return_value=inventory), patch.object(w, 'execute', return_value={'reason': 'spawn-error', 'returncode': None}) as execute:
                result = w.launch_session(session, 5)
                self.assertEqual(result['reason'], 'spawn-error')
                self.assertTrue((session / 'launch.claim').is_file())
                final = w.read_json(session / 'session.json')
                self.assertEqual(final['status'], 'launch finished; gameplay unverified')
                self.assertEqual(final['launch_outcome']['reason'], 'spawn-error')
                # Simulate a second caller which read the prepared state earlier.
                w.write_json(session / 'session.json', manifest)
                with self.assertRaisesRegex(ValueError, 'claimed'):
                    w.launch_session(session, 5)
                self.assertEqual(execute.call_count, 1)


if __name__ == '__main__':
    unittest.main()

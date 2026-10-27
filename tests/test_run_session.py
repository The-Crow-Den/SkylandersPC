# SPDX-License-Identifier: GPL-3.0-or-later
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

from tools.run_session import run_logged, overlay_environment, overlay_pci_configuration, renderer_environment, main


class RunSessionTests(unittest.TestCase):
    def test_automatic_policy_refuses_incompatible_timing_and_external_cap(self):
        for argv in (['--variant','original','--frame-policy','auto'],
                     ['--variant','60','--frame-policy','auto'],
                     ['--variant','60-delta','--frame-policy','auto','--present-limit','60']):
            with self.subTest(argv=argv):
                output=io.StringIO()
                with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as result:
                    main(argv)
                self.assertEqual(result.exception.code,2)
                self.assertIn('automatic FPS requires 60-delta',output.getvalue())

    def test_renderer_policy_preserves_guest_filters_and_explicit_overrides(self):
        source = {'BB_ASYNC_PIPELINES':'0','BB_GPU_SPIN_US':'25'}
        result = renderer_environment(source)
        self.assertEqual(result['BB_ANISO'],'0')
        self.assertEqual(result['BB_GPU_SPIN_US'],'25')
        self.assertEqual(result['BB_ASYNC_PIPELINES'],'0')
        self.assertNotIn('BB_ANISO',source)
        self.assertEqual(result['BB_PRESENT_AS_READY'],'1')
        self.assertEqual(result['BB_PRESENT_MODE'],'Fifo')
        chosen=renderer_environment({'BB_PRESENT_AS_READY':'0','BB_PRESENT_MODE':'Mailbox'})
        self.assertEqual(chosen['BB_PRESENT_AS_READY'],'0')
        self.assertEqual(chosen['BB_PRESENT_MODE'],'Mailbox')
        self.assertEqual(renderer_environment({'BB_ANISO':'8'})['BB_ANISO'],'8')
        sleeping = renderer_environment(source,'sleep')
        self.assertEqual(sleeping['BB_ANISO'],'0')
        self.assertEqual(sleeping['BB_GPU_SPIN_US'],'0')
        self.assertEqual(sleeping['BB_PIPE_SPIN_US'],'0')
        with self.assertRaises(ValueError):
            renderer_environment(source,idle='unknown')

    def test_overlay_preserves_environment_without_implicit_cap(self):
        original = {'HOME': '/synthetic', 'MANGOHUD_CONFIG': 'fps,gpu_stats'}
        env = overlay_environment(original)
        self.assertEqual(env['HOME'], original['HOME'])
        self.assertEqual(env['MANGOHUD_CONFIG'], original['MANGOHUD_CONFIG'])
        self.assertEqual(env['MANGOHUD'], '1')
        self.assertNotIn('MANGOHUD', original)

    def test_manual_phase_starts_at_30_and_removes_old_cap(self):
        env = overlay_environment({'MANGOHUD_CONFIG': 'fps,fps_limit=120,0,gpu_stats'}, phase_switch=True)
        self.assertEqual(env['MANGOHUD_CONFIG'], 'fps,gpu_stats,fps_limit_method=early,fps_limit=30+60,toggle_fps_limit=Shift_L+F1')

    def test_explicit_limiter_method_is_retained_for_comparison(self):
        env = overlay_environment({'MANGOHUD_CONFIG': 'fps,fps_limit_method=late'}, phase_switch=True)
        self.assertIn('fps_limit_method=late', env['MANGOHUD_CONFIG'])
        self.assertNotIn('fps_limit_method=early', env['MANGOHUD_CONFIG'])

    def test_pci_address_uses_file_and_rejects_config_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = overlay_pci_configuration(root, '0000:C5:00.0')
            self.assertEqual(path.read_text(), 'pci_dev=0000:c5:00.0\n')
            with self.assertRaises(FileExistsError):
                overlay_pci_configuration(root, '0000:c5:00.0')
            for value in ('0000', '0000:c5:00.0\nfps_limit=0', '../other', '0000:c5:00.8'):
                with self.assertRaises(ValueError):
                    overlay_pci_configuration(root, value)

    def test_actual_failure_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_logged([sys.executable, '-c', 'print("unsupported-call"); raise SystemExit(20)'], root, cwd=root)
            self.assertEqual(result['returncode'], 20)
            self.assertEqual(result['stop_reason'], 'process-exit')
            self.assertIn('unsupported-call', (root / 'runtime.log').read_text())
            self.assertEqual(json.loads((root / 'exit.json').read_text()), result)

    def test_requested_timeout_is_distinguished_from_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_logged([sys.executable, '-c', 'import time; time.sleep(60)'], root, cwd=root, seconds=0.1)
            self.assertEqual(result['stop_reason'], 'requested-time-limit')
            self.assertEqual(result['signal'], 15)

    def test_unrequested_signal_is_process_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_logged([sys.executable, '-c', 'import os, signal; os.kill(os.getpid(), signal.SIGTERM)'], root, cwd=root)
            self.assertEqual(result['stop_reason'], 'process-exit')
            self.assertEqual(result['returncode'], -15)
            self.assertEqual(result['signal'], 15)

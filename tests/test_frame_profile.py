# SPDX-License-Identifier: GPL-3.0-or-later
import json
import unittest

from tools.frame_profile import RENDERER, GUEST, summarize


def renderer_csv(samples):
    header = ['t_s', 'frame_ms', 'compiles', 'monotonic_us', *RENDERER]
    lines = [','.join(header)]
    for stamp, frame, extra in samples:
        values = dict.fromkeys(header, 0.0)
        values.update(frame_ms=frame, monotonic_us=stamp, stage_a_cpu_ms=4.0, **extra)
        lines.append(','.join(str(values[name]) for name in header))
    return '\n'.join(lines) + '\n'


def guest_csv(samples):
    header = ['monotonic_us', 'frame_ms', 'guest_threads', 'service_calls', *GUEST]
    lines = [','.join(header)]
    for stamp, main_cpu in samples:
        values = dict.fromkeys(header, 0.0)
        values.update(monotonic_us=stamp, frame_ms=16.7, main_cpu_ms=main_cpu, main_sync_ms=1.0)
        lines.append(','.join(str(values[name]) for name in header))
    return '\n'.join(lines) + '\n'


def phase(stamp, name, fps):
    return json.dumps(dict(event='trap-frame-policy-observation', observed_us=stamp, phase=name, wanted_fps=fps))


class FrameProfileTests(unittest.TestCase):
    def setUp(self):
        self.runtime = '\n'.join([phase(0, 'loading', 30), phase(5_000_000, 'gameplay', 60), 'not json'])
        gameplay = [(6_000_000 + i * 16_667, 16.67, {}) for i in range(100)]
        gameplay[10] = (gameplay[10][0], 80.0, dict(compiles=3))
        gameplay[20] = (gameplay[20][0], 60.0, dict(write_fault_ms=30.0))
        gameplay[30] = (gameplay[30][0], 50.0, {})
        self.frames = renderer_csv([(1_500_000, 33.3, {})] + gameplay)
        guest = [(stamp, 9.0) for stamp, _, _ in gameplay]
        guest[30] = (gameplay[30][0], 40.0)
        self.guest = guest_csv(guest) + '123,4'  # Truncated final line is ignored.

    def test_phases_and_long_frame_causes(self):
        report = summarize(self.frames, self.guest, self.runtime)
        by_phase = {entry['phase']: entry for entry in report['phases']}
        gameplay = by_phase['gameplay']
        self.assertEqual(gameplay['renderer_frames']['frames'], 100)
        self.assertEqual(gameplay['renderer_frames']['median_ms'], 16.67)
        self.assertEqual(gameplay['pipeline_compiles'], 3)
        self.assertEqual(gameplay['guest_frames']['frames'], 100)
        self.assertEqual(gameplay['guest_mean_ms']['main_sync_ms'], 1.0)
        self.assertEqual(gameplay['long_frames']['by_cause'],
                         {'pipeline-compile': 1, 'write-fault-tracking': 1, 'guest-main-cpu': 1})
        self.assertEqual(gameplay['long_frames']['worst'][0]['frame_ms'], 80.0)
        self.assertEqual(by_phase['loading']['renderer_frames']['frames'], 1)

    def test_compile_split_when_columns_present(self):
        header = ['t_s', 'frame_ms', 'compiles', 'monotonic_us', *RENDERER, 'module_compiles', 'module_compile_ms', 'compile_ms']
        lines = [','.join(header)]
        for i in range(20):
            values = dict.fromkeys(header, 0.0)
            values.update(frame_ms=16.67, monotonic_us=6_000_000 + i * 16_667)
            if i == 5:
                values.update(frame_ms=200.0, compiles=10, module_compiles=4, module_compile_ms=40.0, compile_ms=180.0)
            lines.append(','.join(str(values[name]) for name in header))
        report = summarize('\n'.join(lines) + '\n', '', self.runtime)
        gameplay = [entry for entry in report['phases'] if entry['phase'] == 'gameplay'][0]
        self.assertEqual(gameplay['compile_split'], dict(shader_translations=4, translation_ms=40.0,
                                                         pipelines_and_other=6, pipeline_ms=140.0))

    def test_settling_excludes_transition_frames(self):
        report = summarize(self.frames, self.guest, self.runtime, settling_ms=10_000)
        self.assertEqual(report['phases'], [])

    def test_guest_profile_is_optional(self):
        report = summarize(self.frames, '', self.runtime)
        gameplay = [entry for entry in report['phases'] if entry['phase'] == 'gameplay'][0]
        self.assertIsNone(gameplay['guest_mean_ms']['main_cpu_ms'])
        self.assertIn('unattributed', gameplay['long_frames']['by_cause'])

    def test_missing_columns_rejected(self):
        with self.assertRaises(ValueError):
            summarize('monotonic_us,frame_ms\n1,2\n', '', self.runtime)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
import json
import unittest
from tools.frame_timeline import summarize


def observation(stamp, phase, fps=30):
    return json.dumps(dict(event='trap-frame-policy-observation', observed_us=stamp,
                           phase=phase, wanted_fps=fps, actuated=True))


class FrameTimelineTests(unittest.TestCase):
    def test_phase_boundary_and_transition_hitches_remain_visible(self):
        log = '\n'.join([observation(1000000, 'cutscene'), observation(3000000, 'gameplay', 60)])
        frames = ('monotonic_us,frame_ms,compiles\n'
                  '900000,50,0\n1100000,50,1\n2200000,33.333,0\n'
                  '3000000,100,2\n4100000,16.667,0\n')
        result = summarize(frames, log)
        phases = {row['phase']: row for row in result['phases']}
        self.assertEqual(phases['unknown']['all_frames']['frames'], 1)
        self.assertEqual(phases['cutscene']['all_frames']['worst_ms'], 50)
        self.assertEqual(phases['cutscene']['settled_frames']['frames'], 1)
        self.assertEqual(phases['gameplay']['all_frames']['worst_ms'], 100)
        self.assertEqual(phases['gameplay']['settled_frames']['median_ms'], 16.667)
        self.assertEqual(phases['gameplay']['shader_pipeline_compiles'], 2)

    def test_old_csv_and_non_monotonic_input_fail(self):
        with self.assertRaisesRegex(ValueError, 'monotonic_us'):
            summarize('t_s,frame_ms\n0,33.3\n', '')
        with self.assertRaisesRegex(ValueError, 'non-monotonic'):
            summarize('monotonic_us,frame_ms\n100,33\n99,33\n', '')

    def test_invalid_durations_are_not_silently_averaged(self):
        for value in ('nan', 'inf', '-1', '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize('monotonic_us,frame_ms\n1,' + value + '\n', '')

    def test_provider_initial_row_is_explicitly_accounted_for(self):
        result = summarize('t_s,monotonic_us,frame_ms\n0.0000,100,0.00\n0.0333,33400,33.30\n', '')
        self.assertEqual(result['initial_samples_without_interval'], 1)
        self.assertEqual(result['phases'][0]['all_frames']['frames'], 1)

    def test_truncated_capture_tail_requires_explicit_opt_in_and_is_counted(self):
        frames = 'monotonic_us,frame_ms,compiles\n100,33,0\n200,66,1\n300,16'
        with self.assertRaisesRegex(ValueError, 'CSV row'):
            summarize(frames, '')
        result = summarize(frames, '', allow_incomplete_tail=True)
        self.assertEqual(result['incomplete_tail_samples_excluded'], 1)
        self.assertEqual(result['phases'][0]['all_frames']['frames'], 2)
        self.assertEqual(result['phases'][0]['all_frames']['worst_ms'], 66)
        self.assertEqual(result['phases'][0]['shader_pipeline_compiles'], 1)

    def test_tail_option_does_not_hide_bad_interior_or_oversized_rows(self):
        for frames in ('100,33\n200\n300,16\n', '100,33\n200,16,unexpected\n'):
            with self.subTest(frames=frames), self.assertRaisesRegex(ValueError, 'CSV row'):
                summarize('monotonic_us,frame_ms\n'+frames, '', allow_incomplete_tail=True)


if __name__ == '__main__':
    unittest.main()

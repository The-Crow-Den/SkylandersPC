# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from tools.frame_report import summarize


class FrameReportTests(unittest.TestCase):
    def test_interval_skip_counters(self):
        report = summarize('''Frame stats: 30.0 FPS, worst frame 99.0 ms (vblank 60 Hz); 2 shader/pipeline compiles, 40.0 ms;
Frame pacing: median 33.33 ms, stddev 2.0 ms, p99 35.0 ms, 1 frames over 1.5x median
GPU: 2 pipelines compiled in the background, 10 draws went without theirs meanwhile
GPU: 4 pipelines compiled in the background, 14 draws went without theirs meanwhile''')
        self.assertEqual(report['maximum_reported_skipped_pipeline_draws'], 14)
        self.assertEqual(report['total_reported_skipped_pipeline_draws'], 24)
        self.assertEqual(report['shader_compiles_in_sampled_windows'], 2)
        self.assertEqual(report['worst_frame_ms'], 99)

    def test_missing_data_is_not_zero_fps(self):
        report = summarize('no sampled frames')
        self.assertIsNone(report['fps_range'])
        self.assertIsNone(report['worst_frame_ms'])

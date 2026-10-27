# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from tools.benchmark_report import summarize

class BenchmarkReportTests(unittest.TestCase):
    def test_tail_excludes_loading_and_tolerates_incomplete_last_record(self):
        text='t_s,frame_ms,draws,compiles\n0,400,10,5\n10,16,100,0\n11,20,90,0\n12,16,100,0\n13,'
        result=summarize(text,2)
        self.assertEqual(result['frames'],3)
        self.assertEqual(result['worst_ms'],20)
        self.assertEqual(result['median_ms'],16)
        self.assertEqual(result['compiles'],0)
        self.assertAlmostEqual(result['mean_draws'],290/3)
    def test_empty_data_is_rejected(self):
        with self.assertRaises(ValueError):summarize('t_s,frame_ms\n')

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Summarize private frame diagnostics without claiming matched-scene speedups."""
import argparse
import json
from pathlib import Path
import re


def summarize(text):
    frames = re.findall(r'Frame stats: ([\d.]+) FPS, worst frame ([\d.]+) ms .*?; (\d+) shader/pipeline compiles, ([\d.]+) ms', text)
    pacing = re.findall(r'Frame pacing: median ([\d.]+) ms, stddev ([\d.]+) ms, p99 ([\d.]+) ms, (\d+) frames over 1.5x median', text)
    skipped = re.findall(r'GPU: (\d+) pipelines compiled in the background, (\d+) draws went without theirs meanwhile', text)
    return {
        'sample_windows': len(frames),
        'fps_range': [min(float(f[0]) for f in frames), max(float(f[0]) for f in frames)] if frames else None,
        'worst_frame_ms': max((float(f[1]) for f in frames), default=None),
        'shader_compiles_in_sampled_windows': sum(int(f[2]) for f in frames),
        'shader_compile_time_ms_in_sampled_windows': round(sum(float(f[3]) for f in frames), 2),
        'largest_sample_p99_ms': max((float(p[2]) for p in pacing), default=None),
        'long_frames_in_sampled_windows': sum(int(p[3]) for p in pacing),
        # The provider resets these counters after each diagnostic print.
        'total_reported_skipped_pipeline_draws': sum(int(s[1]) for s in skipped),
        'maximum_reported_skipped_pipeline_draws': max((int(s[1]) for s in skipped), default=0),
        'comparison_limit': 'Diagnostic sampled windows; scenes/cold-warm state must match before comparing. No gameplay-speed or performance claim.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.log.read_text(errors='replace')), indent=2))


if __name__ == '__main__':
    main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Join software flip diagnostics to the game's observed frame-policy phases.

These are dispatch timestamps, not display scanout or GPU completion times.
Keep scenes, cache state and diagnostic settings matched for any comparison.
"""
import argparse
import bisect
import csv
import io
import json
import math
from pathlib import Path


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return dict(frames=0)
    def percentile(p):
        return round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 3)
    return dict(frames=len(ordered), mean_ms=round(sum(ordered) / len(ordered), 3),
                median_ms=percentile(.5), p99_ms=percentile(.99),
                worst_ms=round(ordered[-1], 3),
                software_flip_fps=round(1000 * len(ordered) / sum(ordered), 3))


def summarize(csv_text, runtime_text, settling_ms=1000, *, allow_incomplete_tail=False):
    if not math.isfinite(settling_ms) or settling_ms < 0:
        raise ValueError('settling interval must be finite and nonnegative')
    events = []
    for line in runtime_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get('event') != 'trap-frame-policy-observation':
            continue
        stamp, phase, fps = event.get('observed_us'), event.get('phase'), event.get('wanted_fps')
        if type(stamp) is not int or stamp < 0 or not isinstance(phase, str) or type(fps) is not int:
            raise ValueError('invalid frame-policy observation')
        events.append((stamp, phase, fps, event.get('actuated') is True))
    events.sort(key=lambda event: event[0])
    times = [event[0] for event in events]
    reader = csv.DictReader(io.StringIO(csv_text))
    if not {'monotonic_us', 'frame_ms'} <= set(reader.fieldnames or []):
        raise ValueError('frame CSV needs monotonic_us and frame_ms columns; use the timestamp diagnostic patch')
    groups, previous, initial_samples_without_interval = {}, -1, 0
    rows = list(reader)
    incomplete_tail_samples_excluded = 0
    for row_index, row in enumerate(rows):
        if None in row or any(value is None for value in row.values()):
            if allow_incomplete_tail and row_index == len(rows)-1 and None not in row:
                incomplete_tail_samples_excluded += 1
                continue
            raise ValueError('incomplete or oversized frame CSV row')
        stamp, duration = int(row['monotonic_us']), float(row['frame_ms'])
        if stamp < 0 or stamp < previous or not math.isfinite(duration):
            raise ValueError('invalid or non-monotonic frame sample')
        previous = stamp
        # The provider's first row initializes its previous-flip timestamp. It
        # has no preceding interval and prints 0.00 at t_s=0. Later zero or
        # negative durations remain errors rather than disappearing silently.
        if row_index == 0 and duration == 0 and float(row.get('t_s', 'nan')) == 0:
            initial_samples_without_interval += 1
            continue
        if duration <= 0:
            raise ValueError('invalid frame duration')
        index = bisect.bisect_right(times, stamp) - 1
        state = events[index] if index >= 0 else (0, 'unknown', 0, False)
        start, phase, fps, actuated = state
        key = phase, fps, actuated
        group = groups.setdefault(key, dict(all=[], settled=[], compiles=0))
        group['all'].append(duration)
        if index >= 0 and stamp - start >= settling_ms * 1000:
            group['settled'].append(duration)
        compiles = int(row.get('compiles') or 0)
        if compiles < 0:
            raise ValueError('negative compile count')
        group['compiles'] += compiles
    result = []
    for (phase, fps, actuated), values in sorted(groups.items()):
        # Retain all frames as well as the settled subset; transition hitches
        # remain visible rather than being silently excluded from the report.
        result.append(dict(phase=phase, policy_requested_fps=fps, automatic_actuated=actuated,
                           all_frames=distribution(values['all']),
                           settled_frames=distribution(values['settled']),
                           shader_pipeline_compiles=values['compiles']))
    return dict(phases=result, settling_ms=settling_ms,
                initial_samples_without_interval=initial_samples_without_interval,
                incomplete_tail_samples_excluded=incomplete_tail_samples_excluded,
                measurement='Software flip dispatch intervals; not display scanout or GPU completion.',
                comparison_limit='Match scene, cache state and diagnostics. No speedup or simulation-speed claim.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('runtime_log', type=Path)
    parser.add_argument('--settling-ms', type=float, default=1000)
    parser.add_argument('--allow-incomplete-tail', action='store_true',
                        help='explicitly exclude and count one truncated final CSV row')
    args = parser.parse_args()
    print(json.dumps(summarize(args.csv.read_text(), args.runtime_log.read_text(errors='replace'),
                               args.settling_ms, allow_incomplete_tail=args.allow_incomplete_tail), indent=2))


if __name__ == '__main__':
    main()

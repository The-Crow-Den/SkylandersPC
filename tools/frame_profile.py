#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Summarize a --profile session: where frame time goes, per game phase.

Joins the renderer's per-flip CSV (frames.csv), the host's per-guest-flip CSV
(frame-profile.csv) and the frame-policy phase events in runtime.log, all keyed
by CLOCK_MONOTONIC microseconds. Times are CPU-side: renderer frame intervals
are present-thread flips, not GPU completion or scanout. Compare sessions only
with matched scenes, settings and cache state.
"""
import argparse
import bisect
import csv
import io
import json
import math
from pathlib import Path

RENDERER = ('present_wait_ms', 'tick_wait_ms', 'stage_a_cpu_ms', 'protect_ms', 'resident_ms', 'create_ms',
            'refresh_ms', 'write_fault_ms', 'kernel_ms')
GUEST = ('main_cpu_ms', 'worker_cpu_ms', 'main_gpu_ms', 'main_sync_ms', 'main_clock_ms', 'main_file_ms',
         'main_other_ms', 'all_gpu_ms', 'all_sync_ms', 'all_clock_ms', 'all_file_ms', 'all_other_ms')
# Renderer columns that are CPU work on the frame's critical path, by cause.
CAUSES = (('pipeline-compile', 'compiles'), ('resource-create', 'create_ms'), ('cache-refresh', 'refresh_ms'),
          ('write-fault-tracking', 'write_fault_ms'), ('page-protection', 'protect_ms'),
          ('render-thread-cpu', 'stage_a_cpu_ms'))


def rows(text, required):
    reader = csv.DictReader(io.StringIO(text))
    missing = set(required) - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f'CSV lacks columns: {sorted(missing)}')
    result = []
    for row in reader:
        try:
            converted = {key: float(value) for key, value in row.items() if key is not None}
        except (TypeError, ValueError):
            continue  # A killed producer can leave a truncated final line.
        if len(converted) == len(reader.fieldnames) and converted['frame_ms'] > 0:
            result.append(converted)
    return result


def phases(runtime_text):
    events = []
    for line in runtime_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get('event') == 'trap-frame-policy-observation':
            events.append((int(event['observed_us']), str(event['phase']), int(event['wanted_fps'])))
    return sorted(events)


def percentile(values, p):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 3) if ordered else None


def mean(values):
    return round(sum(values) / len(values), 3) if values else None


def distribution(values):
    return dict(frames=len(values), median_ms=percentile(values, .5), p95_ms=percentile(values, .95),
                p99_ms=percentile(values, .99), worst_ms=round(max(values), 3) if values else None)


def label(events, stamp, settling_us):
    times = [event[0] for event in events]
    index = bisect.bisect_right(times, stamp) - 1
    if index < 0:
        return None
    start, phase, fps = events[index]
    return (phase, fps) if stamp - start >= settling_us else None


def nearest(guest, stamps, stamp, window_us):
    index = bisect.bisect_left(stamps, stamp)
    best = None
    for candidate in (index - 1, index):
        if 0 <= candidate < len(guest) and abs(stamps[candidate] - stamp) <= window_us:
            if best is None or abs(stamps[candidate] - stamp) < abs(stamps[best] - stamp):
                best = candidate
    return guest[best] if best is not None else None


def cause(row, guest, budget_ms):
    if row.get('compiles', 0) > 0:
        return 'pipeline-compile'
    costs = {name: row.get(column, 0) for name, column in CAUSES[1:]}
    if guest:
        costs['guest-main-cpu'] = guest['main_cpu_ms']
        costs['guest-main-waits'] = guest['main_sync_ms'] + guest['main_clock_ms']
        costs['guest-file-io'] = guest['main_file_ms']
    name, value = max(costs.items(), key=lambda item: item[1])
    # Nothing measured explains the frame: likely GPU-bound or outside these counters.
    return name if value >= 0.5 * budget_ms else 'unattributed'


def summarize(frames_text, guest_text, runtime_text, settling_ms=1000, long_factor=1.5):
    renderer = rows(frames_text, ('monotonic_us', 'frame_ms', 'compiles') + RENDERER)
    guest = rows(guest_text, ('monotonic_us', 'frame_ms') + GUEST) if guest_text else []
    guest.sort(key=lambda row: row['monotonic_us'])
    guest_stamps = [row['monotonic_us'] for row in guest]
    events = phases(runtime_text)
    settling_us = settling_ms * 1000
    groups = {}
    for row in renderer:
        key = label(events, row['monotonic_us'], settling_us)
        if key:
            groups.setdefault(key, dict(renderer=[], guest=[]))['renderer'].append(row)
    for row in guest:
        key = label(events, row['monotonic_us'], settling_us)
        if key:
            groups.setdefault(key, dict(renderer=[], guest=[]))['guest'].append(row)
    report = []
    for (phase, fps), group in sorted(groups.items(), key=lambda item: -len(item[1]['renderer'])):
        frame_times = [row['frame_ms'] for row in group['renderer']]
        median = percentile(frame_times, .5) or 0
        budget = 1000 / fps if fps else median
        long_frames, causes = [], {}
        for row in group['renderer']:
            if row['frame_ms'] > max(long_factor * median, long_factor * budget):
                match = nearest(guest, guest_stamps, row['monotonic_us'], row['frame_ms'] * 1000)
                reason = cause(row, match, budget)
                causes[reason] = causes.get(reason, 0) + 1
                long_frames.append(dict(monotonic_us=int(row['monotonic_us']), frame_ms=row['frame_ms'], cause=reason,
                    compiles=int(row['compiles']), create_ms=row['create_ms'], write_fault_ms=row['write_fault_ms'],
                    render_thread_cpu_ms=row['stage_a_cpu_ms'],
                    guest_main_cpu_ms=match['main_cpu_ms'] if match else None))
        long_frames.sort(key=lambda item: -item['frame_ms'])
        guest_rows = group['guest']
        report.append(dict(
            phase=phase, requested_fps=fps, budget_ms=round(budget, 3),
            renderer_frames=distribution(frame_times),
            renderer_mean_ms={column: mean([row[column] for row in group['renderer']]) for column in RENDERER},
            pipeline_compiles=int(sum(row['compiles'] for row in group['renderer'])),
            guest_frames=distribution([row['frame_ms'] for row in guest_rows]),
            guest_mean_ms={column: mean([row[column] for row in guest_rows]) for column in GUEST},
            guest_p95_main_cpu_ms=percentile([row['main_cpu_ms'] for row in guest_rows], .95),
            guest_main_cpu_budget_share=round(mean([row['main_cpu_ms'] for row in guest_rows]) / budget, 3)
                if guest_rows and budget else None,
            long_frames=dict(count=len(long_frames), by_cause=causes, worst=long_frames[:10])))
    return dict(phases=report, settling_ms=settling_ms, long_frame_rule=f'> {long_factor}x max(phase median, budget)',
                measurement='CPU-side times. Renderer frame_ms is the present-thread flip interval; GPU execution time is not measured.',
                comparison_limit='Match scene, settings and cold/warm cache state. Profiling itself adds small overhead.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path, help='session directory from run_session.py --profile')
    parser.add_argument('--settling-ms', type=float, default=1000)
    parser.add_argument('--json', action='store_true', help='print the full JSON report')
    args = parser.parse_args()
    frames = args.session/'frames.csv'
    if not frames.is_file():
        parser.error(f'{frames} is missing; run the session with --profile')
    guest = args.session/'frame-profile.csv'
    report = summarize(frames.read_text(), guest.read_text() if guest.is_file() else '',
                       (args.session/'runtime.log').read_text(errors='replace'), args.settling_ms)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    for phase in report['phases']:
        r, g = phase['renderer_frames'], phase['guest_mean_ms']
        print(f"{phase['phase']} @ {phase['requested_fps']} FPS (budget {phase['budget_ms']} ms): "
              f"{r['frames']} frames, median {r['median_ms']} / p95 {r['p95_ms']} / p99 {r['p99_ms']} / worst {r['worst_ms']} ms")
        m = phase['renderer_mean_ms']
        print(f"  renderer means: render-thread CPU {m['stage_a_cpu_ms']}, present wait {m['present_wait_ms']}, "
              f"tick wait {m['tick_wait_ms']}, write faults {m['write_fault_ms']}, create {m['create_ms']}, "
              f"compiles {phase['pipeline_compiles']}")
        if g['main_cpu_ms'] is not None:
            print(f"  guest means: main CPU {g['main_cpu_ms']} (p95 {phase['guest_p95_main_cpu_ms']}, "
                  f"{phase['guest_main_cpu_budget_share']} of budget), workers CPU {g['worker_cpu_ms']}; main in services: "
                  f"gpu {g['main_gpu_ms']}, sync {g['main_sync_ms']}, clock {g['main_clock_ms']}, file {g['main_file_ms']}")
        print(f"  long frames: {phase['long_frames']['count']} {phase['long_frames']['by_cause']}")
    print(report['measurement'])


if __name__ == '__main__':
    main()

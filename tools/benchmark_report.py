#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Summarize a selected tail of a private frame CSV, without asserting scene equivalence."""
import argparse
import csv
import io
import json
import statistics
from pathlib import Path


def summarize(text,last_seconds=15):
    rows=[]
    for row in csv.DictReader(io.StringIO(text)):
        try:
            converted={k:float(v) for k,v in row.items()}
            if converted['frame_ms']>0: rows.append(converted)
        except (ValueError,TypeError):
            continue  # A running producer may leave its last CSV line incomplete.
    if not rows:raise ValueError('no complete frame records')
    end=max(row['t_s'] for row in rows)
    rows=[r for r in rows if r['t_s']>=end-last_seconds]
    times=sorted(r['frame_ms'] for r in rows)
    def percentile(p):
        at=(len(times)-1)*p
        low=int(at);high=min(low+1,len(times)-1)
        return times[low]+(times[high]-times[low])*(at-low)
    result={'frames':len(rows),'start_s':min(r['t_s'] for r in rows),'end_s':end,
            'mean_fps':1000/statistics.mean(times),'median_ms':statistics.median(times),
            'p99_ms':percentile(.99),'worst_ms':max(times),
            'frames_over_25ms':sum(t>25 for t in times),
            'compiles':sum(r.get('compiles',0) for r in rows),
            'comparison_limit':'Use matching scene, cap and cache state. Effect changes are quality tradeoffs; CPU/driver measurements are not GPU timings.'}
    for key in ('draws','dispatches','stage_a_cpu_ms','image_mb','buffer_mb'):
        if all(key in r for r in rows):result['mean_'+key]=statistics.mean(r[key] for r in rows)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv',type=Path)
    parser.add_argument('--last-seconds',type=float,default=15)
    args=parser.parse_args()
    if not 0<args.last_seconds<float('inf'):parser.error('last-seconds must be positive and finite')
    print(json.dumps(summarize(args.csv.read_text(),args.last_seconds),indent=2))

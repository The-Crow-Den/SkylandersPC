#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only process CPU and optional NVIDIA board telemetry for matched trials.

No GPU timestamps, injected code, clock changes or graphics instrumentation.
NVIDIA figures describe the entire GPU, including other processes.
"""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time


def process_state(pid):
    # comm can contain spaces and parentheses; fields after its closing ')' start at 3.
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    return {'ticks':int(fields[11])+int(fields[12]), 'start':int(fields[19]),
            'rss_kib':int(fields[21])*os.sysconf('SC_PAGE_SIZE')/1024}


def nvidia_state(index):
    fields = ('utilization.gpu','power.draw','clocks.current.graphics','memory.used')
    result = subprocess.run(['nvidia-smi','-i',str(index),
                             '--query-gpu='+','.join(fields),'--format=csv,noheader,nounits'],
                            capture_output=True,text=True,timeout=3,check=True)
    values = result.stdout.strip().split(',')
    if len(values) != len(fields):
        raise ValueError('unexpected NVIDIA telemetry')
    sample = {}
    for key,value in zip(fields,values):
        try:
            number = float(value.strip())
            if math.isfinite(number): sample[key]=number
        except ValueError:
            pass  # An unsupported metric is unavailable, not zero.
    return sample


def sample(pid, seconds, gpu_index=None):
    before = process_state(pid)
    started = time.monotonic()
    gpu,errors = [],[]
    while time.monotonic()-started < seconds:
        if gpu_index is not None:
            try:
                gpu.append(nvidia_state(gpu_index))
            except (OSError,ValueError,subprocess.SubprocessError) as error:
                errors.append(str(error))
        remaining = seconds-(time.monotonic()-started)
        if remaining > 0: time.sleep(min(1,remaining))
    elapsed = time.monotonic()-started
    after = process_state(pid)
    if before['start'] != after['start']:
        raise ValueError('process identity changed during sample')
    result = {'pid':pid,'elapsed_s':elapsed,'nvidia_index':gpu_index,
              'cpu_percent_one_core_100':100*(after['ticks']-before['ticks'])/os.sysconf('SC_CLK_TCK')/elapsed,
              'rss_before_kib':before['rss_kib'],'rss_after_kib':after['rss_kib'],
              'gpu_samples':len(gpu),
              'limitation':'Match scene, cap, cache, power mode and other GPU activity. Board utilization/power are not per-process or GPU frame durations.'}
    for key in ('utilization.gpu','power.draw','clocks.current.graphics','memory.used'):
        values = [row[key] for row in gpu if key in row]
        if values: result['mean_'+key]=statistics.mean(values)
    if errors: result['telemetry_errors']=errors
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid',type=int)
    parser.add_argument('--seconds',type=float,default=20)
    parser.add_argument('--nvidia-index',type=int)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if args.pid <= 0 or not 0 < args.seconds <= 60:
        parser.error('positive PID and finite sample duration up to 60 seconds required')
    try:
        text = json.dumps(sample(args.pid,args.seconds,args.nvidia_index),indent=2)+'\n'
    except (OSError,ValueError) as error:
        parser.exit(1,f'Cannot measure runtime: {error}\n')
    if args.output: args.output.write_text(text)
    print(text,end='')

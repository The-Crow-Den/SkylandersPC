#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a short, redacted crash report for an abnormal game session exit.

The report never includes saves, figures, keys or game data: only build
identity, host description, chosen settings and the tail of runtime.log.
"""
import getpass
import json
import os
import platform
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_MARKER = 'Runtime log: '
TAIL_LINES = 200
FAULT_EVENTS = ('guest-fault', 'fault-host-owner', 'fault-registers')
SETTING_KEYS = ('variant', 'performance_profile', 'motion_blur', 'memory_mode', 'renderer_idle',
                'window_size', 'phase_policy', 'gameplay_mods', 'renderer_environment',
                'graphics_environment', 'diagnostic_environment')


def session_directory(output):
    """Session folder announced by run_session.py, or None before it was announced."""
    lines = output.splitlines()
    if lines and not output.endswith('\n'):
        lines.pop()  # The last line may still be arriving.
    for line in reversed(lines):
        if line.startswith(LOG_MARKER):
            return Path(line[len(LOG_MARKER):].strip()).parent
    return None


def redact(text, home=None, user=None):
    """Replace home-directory paths and the user name with placeholders."""
    home = home if home is not None else str(Path.home())
    if user is None:
        try:
            user = getpass.getuser()
        except (KeyError, OSError):
            user = ''
    if home and home not in ('/', ''):
        text = text.replace(home.rstrip('/'), '~')
    text = re.sub(r'/(home|Users)/[^/\s"\']+', r'/\1/<user>', text)
    if user and len(user) > 1:
        text = re.sub(r'(?<![\w-])' + re.escape(user) + r'(?![\w-])', '<user>', text)
    return text


def tail(path, lines=TAIL_LINES):
    try:
        data = Path(path).read_bytes()[-512 * 1024:]
    except OSError:
        return []
    return data.decode('utf-8', errors='replace').splitlines()[-lines:]


def fault_lines(lines):
    return [line for line in lines if any('"event":"%s"' % name in line for name in FAULT_EVENTS)]


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _run(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def git_revision(root=ROOT):
    revision = _run(['git', '-C', str(root), 'rev-parse', '--short=12', 'HEAD']).strip()
    if revision and _run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no']).strip():
        revision += '-dirty'
    return revision or 'unknown'


def gpu_description():
    summary = _run(['vulkaninfo', '--summary'])
    names = re.findall(r'deviceName\s*=\s*(.+)', summary)
    drivers = re.findall(r'driverInfo\s*=\s*(.+)', summary)
    ids = re.findall(r'driverID\s*=\s*(.+)', summary)
    if names:
        return '; '.join(' '.join(filter(None, (name.strip(),
                         ids[i].strip() if i < len(ids) else '', drivers[i].strip() if i < len(drivers) else '')))
                         for i, name in enumerate(names))
    return 'unknown (vulkaninfo unavailable)'


def distro_description(os_release='/etc/os-release'):
    values = {}
    try:
        for line in Path(os_release).read_text().splitlines():
            key, _, value = line.partition('=')
            values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values.get('PRETTY_NAME') or values.get('NAME') or 'unknown'


def host_description():
    return {'gpu': gpu_description(), 'distro': distro_description(),
            'kernel': platform.release(), 'machine': platform.machine()}


def exit_description(code, exit_info):
    if exit_info.get('signal'):
        return f"signal {exit_info['signal']} ({exit_info.get('stop_reason', 'process-exit')})"
    if 'returncode' in exit_info:
        return f"exit code {exit_info['returncode']} ({exit_info.get('stop_reason', 'process-exit')})"
    return f'launcher exit code {code} (runtime did not record an exit)'


def build_report(session, code, *, host=None, revision=None, home=None, user=None):
    """Plain-text report for the session folder (may be None when the runner failed early)."""
    session = Path(session) if session else None
    metadata = read_json(session / 'session.json') if session else {}
    exit_info = read_json(session / 'exit.json') if session else {}
    lines = tail(session / 'runtime.log') if session else []
    installation = metadata.get('installation', {})
    host = host if host is not None else host_description()
    settings = {key: metadata[key] for key in SETTING_KEYS if key in metadata}
    out = ['SkylandersPC crash report',
           f"Game: {installation.get('title_id', 'unknown')} version {installation.get('app_version', 'unknown')}",
           f"Executable SHA-256: {installation.get('executable_sha256', 'unknown')}",
           f"Launcher revision: {revision if revision is not None else git_revision()}",
           f"GPU / driver: {host.get('gpu', 'unknown')}",
           f"Distro: {host.get('distro', 'unknown')}",
           f"Kernel: {host.get('kernel', 'unknown')} {host.get('machine', '')}".rstrip(),
           f'Exit: {exit_description(code, exit_info)}']
    faults = fault_lines(lines)
    if faults:
        out += ['', 'Host fault:'] + faults
    out += ['', 'Settings:', json.dumps(settings, indent=2, sort_keys=True),
            '', f'Last {len(lines)} lines of runtime.log:'] + lines
    return redact('\n'.join(out) + '\n', home=home, user=user)

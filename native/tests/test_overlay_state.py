# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the real overlay worker without a window, Vulkan device or game."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from filesystem_fixtures import frame_permissions

binary = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='sky-overlay-state-') as temporary:
    root = Path(temporary)
    frame_permissions(root)
    environment = dict(os.environ, SKY_PC_OVERLAY_DIR=str(root),
                       SKY_PC_MENU_EMBEDDED='0')
    (root / 'heartbeat').write_bytes(b'1')
    process = subprocess.Popen([str(binary), '--overlay-state-probe'], env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    def wait_for(geometry):
        deadline = time.monotonic() + 8
        last = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                out, err = process.communicate()
                raise AssertionError(f'overlay worker exited: {out}\n{err}')
            (root / 'heartbeat').touch()
            try:
                last = json.loads((root / 'state.json').read_text(encoding='utf-8'))
            except FileNotFoundError:
                time.sleep(0.02)
                continue
            if last['geometry'] == geometry:
                assert last['pid'] == process.pid and last['version'] == 1, last
                return
            time.sleep(0.02)
        raise AssertionError(f'overlay state was not published: {last}')
    try:
        wait_for([0, 0, 1280, 720])
        process.stdin.write('publish\n')
        process.stdin.flush()
        wait_for([17, 29, 640, 480])
        out, err = process.communicate('stop\n', timeout=5)
        assert process.returncode == 0, (out, err)
        assert not list(root.glob('.pending-*'))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
print('Real overlay worker published and replaced a complete state snapshot')

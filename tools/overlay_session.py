# SPDX-License-Identifier: GPL-3.0-or-later
"""Manage the optional HTML overlay alongside one game process."""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


@contextmanager
def html_overlay(directory,root,environment):
    if environment is None or environment.get('SKY_PC_WEB_MENU')!='1':
        yield environment
        return
    directory=Path(directory).absolute();root=Path(root).absolute();runtime=dict(environment);process=None
    status={'requested':'web','active':'native'}
    try:
        if importlib.util.find_spec('PyQt6.QtWebEngineWidgets') is None:raise RuntimeError('PyQt6 WebEngine is unavailable')
        private=directory/'pc-overlay';private.mkdir(mode=0o700)
        ui_env=dict(environment);ui_env['MANGOHUD']='0';ui_env['DISABLE_MANGOHUD']='1'
        # The menu is a small 2D page: render it in software. On hybrid-GPU laptops the game's
        # Vulkan driver selection made Chromium draw on one GPU while Qt composited on the other
        # (Mesa), and the overlay crashed about 30 s in ("Compositor returned null texture"),
        # leaving only the renderer's fallback menu.
        flags=ui_env.get('QTWEBENGINE_CHROMIUM_FLAGS','').split()
        ui_env['QTWEBENGINE_CHROMIUM_FLAGS']=' '.join(flags+[flag for flag in ('--disable-gpu','--disable-gpu-compositing') if flag not in flags])
        ui_env['QT_QUICK_BACKEND']='software'
        if ui_env.get('SDL_VIDEO_DRIVER')=='x11':ui_env.setdefault('QT_QPA_PLATFORM','xcb')
        with (directory/'pc-overlay.log').open('x') as output:
            process=subprocess.Popen([sys.executable,str(root/'tools/pc_overlay.py'),'--directory',str(private)],cwd=root,env=ui_env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+12
        while process.poll() is None and time.monotonic()<deadline:
            if (private/'ready').is_file() and (private/'heartbeat').is_file():
                runtime['SKY_PC_OVERLAY_DIR']=str(private);status['active']='web';break
            time.sleep(0.05)
        if status['active']!='web':raise RuntimeError('HTML overlay did not become ready; using native menu')
    except (ImportError,ModuleNotFoundError,OSError,RuntimeError) as error:
        status['error']=str(error);print('PC menu:',error,file=sys.stderr,flush=True)
    (directory/'pc-overlay-status.json').write_text(json.dumps(status,indent=2)+'\n')
    try:
        yield runtime
    finally:
        if process is not None and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()

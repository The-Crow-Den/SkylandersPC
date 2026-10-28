# SPDX-License-Identifier: GPL-3.0-or-later
"""Manage the optional HTML overlay alongside one game process."""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time


# The launcher AppImage pins its own interpreter with these; a system Python
# must see its normal setup, including WebEngine installed with pip --user.
BUNDLE_PYTHON_KEYS = ('PYTHONHOME','PYTHONPATH','PYTHONNOUSERSITE','PYTHONSTARTUP',
                      'QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QML2_IMPORT_PATH')


def system_python_environment(environment):
    result=dict(environment)
    for key in BUNDLE_PYTHON_KEYS:result.pop(key,None)
    return result


def overlay_python(environment):
    """Use installed WebEngine when the small launcher image omits it."""
    try:
        if importlib.util.find_spec('PyQt6.QtWebEngineWidgets') is not None:
            return sys.executable
    except ModuleNotFoundError:
        pass
    checked={os.path.realpath(sys.executable)}
    for search_path in (environment.get('PATH',os.defpath),os.defpath):
        candidate=shutil.which('python3',path=search_path)
        if not candidate or os.path.realpath(candidate) in checked:continue
        checked.add(os.path.realpath(candidate))
        try:
            # Not -I: that would also hide user site-packages. A neutral cwd
            # keeps the working directory from shadowing the imports instead.
            probe=subprocess.run([candidate,'-c','import PyQt6.QtWebEngineWidgets, PyQt6.QtWebChannel'],
                                 env=system_python_environment(environment),cwd='/',
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=4)
            if probe.returncode==0:return candidate
        except (OSError,subprocess.TimeoutExpired):
            continue
    raise RuntimeError('PyQt6 WebEngine is unavailable in the launcher and system Python')


@contextmanager
def html_overlay(directory,root,environment):
    if environment is None or environment.get('SKY_PC_WEB_MENU')!='1':
        yield environment
        return
    directory=Path(directory).absolute();root=Path(root).absolute();runtime=dict(environment);process=None
    embedded=environment.get('SKY_PC_MENU_EMBEDDED','1')=='1'
    status={'requested':'web','active':'native','presentation':'embedded' if embedded else 'desktop'}
    try:
        python=overlay_python(environment)
        private=directory/'pc-overlay';private.mkdir(mode=0o700)
        ui_env=dict(environment);ui_env['MANGOHUD']='0';ui_env['DISABLE_MANGOHUD']='1'
        if os.path.realpath(python)!=os.path.realpath(sys.executable):
            ui_env=system_python_environment(ui_env)
        status['python']=python
        # The menu is a small 2D page: render it in software. On hybrid-GPU laptops the game's
        # Vulkan driver selection made Chromium draw on one GPU while Qt composited on the other
        # (Mesa), and the overlay crashed about 30 s in ("Compositor returned null texture"),
        # leaving only the renderer's fallback menu.
        flags=ui_env.get('QTWEBENGINE_CHROMIUM_FLAGS','').split()
        ui_env['QTWEBENGINE_CHROMIUM_FLAGS']=' '.join(flags+[flag for flag in ('--disable-gpu','--disable-gpu-compositing') if flag not in flags])
        ui_env['QT_QUICK_BACKEND']='software'
        if ui_env.get('SDL_VIDEO_DRIVER')=='x11':ui_env.setdefault('QT_QPA_PLATFORM','xcb')
        with (directory/'pc-overlay.log').open('x') as output:
            command=[python,str(root/'tools/pc_overlay.py'),'--directory',str(private)]
            if embedded:command.append('--embedded')
            process=subprocess.Popen(command,cwd=root,env=ui_env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+12
        while process.poll() is None and time.monotonic()<deadline:
            if (private/'ready').is_file() and (private/'heartbeat').is_file():
                runtime['SKY_PC_OVERLAY_DIR']=str(private)
                runtime['SKY_PC_MENU_EMBEDDED']='1' if embedded else '0'
                status['active']='web';break
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

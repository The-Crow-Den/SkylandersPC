# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point of the frozen Windows launcher (SkylandersPC.exe, PyInstaller).

The exe carries the Python runtime and PyQt6; the tools stay as source beside it.
With no script argument it runs tools/launcher.py. The launcher starts helpers as
`sys.executable [-u] script.py args`, so a .py first argument is run as that
script, exactly as python.exe would.
"""
from pathlib import Path
import runpy
import sys


def attach_streams():
    """A windowed exe starts with no sys streams; use pipes the parent passed, if any."""
    for name, fd, mode in (('stdin', 0, 'r'), ('stdout', 1, 'w'), ('stderr', 2, 'w')):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(fd, mode, encoding='utf-8', errors='replace', closefd=False))
            except OSError:
                pass


def main():
    attach_streams()
    root = Path(sys.executable).resolve().parent
    args = sys.argv[1:]
    while args and args[0] == '-u':
        args = args[1:]
        if sys.stdout is not None:
            sys.stdout.reconfigure(line_buffering=True)
    if args and args[0].endswith('.py'):
        script, rest = Path(args[0]).resolve(), args[1:]
    else:
        script, rest = root / 'tools' / 'launcher.py', args
    sys.argv = [str(script), *rest]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main()

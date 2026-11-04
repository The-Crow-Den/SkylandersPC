# SPDX-License-Identifier: GPL-3.0-or-later
"""Process groups, session locks and per-user data paths on Linux and Windows.

Linux keeps the existing behaviour: a new session per child and signals to its
process group. Windows has neither, so children start in a new process group and
are stopped as a tree with taskkill: first a close request to their windows (as
the user clicking close), then /F after a grace period.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess

WINDOWS = os.name == 'nt'
if WINDOWS:
    import msvcrt
else:
    import fcntl


def group_options():
    """Keyword arguments for subprocess.Popen that start a separately stoppable group."""
    if WINDOWS:
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def stop_group(pid, force=False):
    """Stops the group/tree rooted at pid. A group already gone is not an error."""
    if WINDOWS:
        command = ['taskkill', '/T', '/PID', str(int(pid))]
        if force:
            command.insert(1, '/F')
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return
    try:
        os.killpg(int(pid), signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        pass


def interrupt(pid):
    """Asks a runner to stop and clean up its own game group.

    Linux: SIGINT, which the runner turns into KeyboardInterrupt. Windows has no
    signal to deliver to a windowless child, and os.kill would terminate the
    runner alone and orphan the game, so the whole tree is asked to close.
    """
    if WINDOWS:
        stop_group(pid)
        return
    try:
        os.kill(int(pid), signal.SIGINT)
    except ProcessLookupError:
        pass


@contextmanager
def exclusive_lock(path):
    """Holds a nonblocking exclusive lock on path; raises BlockingIOError if held."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as guard:
        if WINDOWS:
            guard.seek(0)
            try:
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise BlockingIOError('lock is held') from None
            try:
                yield
            finally:
                guard.seek(0)
                msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield


def data_home(environment=None):
    """Per-user application data root: XDG_DATA_HOME on Linux, LOCALAPPDATA on Windows."""
    environment = os.environ if environment is None else environment
    if WINDOWS:
        local = environment.get('LOCALAPPDATA')
        if not local:
            raise OSError('LOCALAPPDATA is not set')
        return Path(local)
    return Path(environment.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))

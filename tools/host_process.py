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
import time

WINDOWS = os.name == 'nt'
if WINDOWS:
    import msvcrt
else:
    import fcntl


def group_options():
    """Keyword arguments for subprocess.Popen that start a separately stoppable group."""
    if WINDOWS:
        # CREATE_NO_WINDOW: the host and menu helper are console programs; started
        # from the windowless launcher, Windows would otherwise open a console
        # window for each. Their output is redirected to the session logs.
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
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


def private_directory(path):
    """Creates a directory only this user can access (POSIX 0700; Windows: protected DACL).

    On Windows mkdir's mode is ignored and the folder inherits its parent's
    permissions (often Authenticated Users), which the host's privacy check for
    the PC menu bridge refuses; it then fell back to the built-in menu.
    """
    path = Path(path)
    path.mkdir(mode=0o700)
    if not WINDOWS:
        return path
    try:
        identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True,
                                  check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        sid = identity.strip().split(',')[-1].strip('"')
        if not sid.startswith('S-1-'):
            raise OSError('could not read the current user SID')
        # Stop inheriting and grant this user full control. /inheritance:r keeps
        # explicit copies of the parent's SYSTEM, Administrators and OWNER RIGHTS
        # entries; the host accepts the first two but not OWNER RIGHTS (S-1-3-4).
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F',
                        '/remove:g', '*S-1-3-4'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        raise OSError(f'could not make {path} private: {error}') from error
    return path


@contextmanager
def exclusive_lock(path, blocking=False):
    """Holds an exclusive lock on path; unless blocking, raises BlockingIOError if held."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as guard:
        if WINDOWS:
            guard.seek(0)
            while True:
                try:
                    msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if not blocking:
                        raise BlockingIOError('lock is held') from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                guard.seek(0)
                msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(guard, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
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

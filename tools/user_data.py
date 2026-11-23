# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the player's own data lives: one SkylandersPC folder per user.

    Linux    $XDG_DATA_HOME/SkylandersPC   (normally ~/.local/share/SkylandersPC)
    Windows  Saved Games\\SkylandersPC     (the user's Saved Games folder)

Inside it: saves/, save-backups/, trophies/, figures/ (the collection, working
copies and backups), settings/ and portal-backups/. SKYLANDERS_DATA overrides
the location, for a portable copy or tests.

Older versions kept saves and trophies in a lower-case `skylanders-pc` folder
(LOCALAPPDATA on Windows) and figures and launcher settings inside the install
folder. `migrate` copies them across once, verified, and leaves the originals
where they were. An install folder uses the per-user figures and settings once
its marker (.local/user-data.json) exists; without one (an older copy, or a
test fixture) it keeps its own folders.
"""
import filecmp
import json
import os
from pathlib import Path
import shutil
import sys

NAME = 'SkylandersPC'
MARKER = '.local/user-data.json'
WINDOWS = os.name == 'nt'

# Install-folder paths of older versions -> place in the per-user folder.
INSTALL_LAYOUT = {
    'out/portal-library': 'figures/collection',
    'out/figures': 'figures/progress',
    'out/figure-backups': 'figures/backups',
    'out/pc-settings.json': 'settings/pc-settings.json',
    'out/play-profiles': 'settings/play-profiles',
    'out/mod-profiles': 'settings/mod-profiles',
    '.local/launcher-settings.json': 'settings/launcher-settings.json',
    '.local/launcher-library.json': 'settings/launcher-library.json',
    '.local/launcher-tips.json': 'settings/launcher-tips.json',
    '.local/removed-games.json': 'settings/removed-games.json',
}
# Per-user folders of older versions, inside the old `skylanders-pc` folder.
HOME_LAYOUT = ('saves', 'save-backups', 'trophies', 'portal-backups', 'pc-menu-preferences.json')


def _saved_games():
    """The Windows Saved Games known folder, or None."""
    try:
        import ctypes
        from ctypes import wintypes
        class GUID(ctypes.Structure):
            _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte*8)]
        saved_games = GUID(0x4C5C32FF, 0xBB9D, 0x43B0, (ctypes.c_ubyte*8)(0xB5, 0xB4, 0x2D, 0x72, 0xE5, 0x4E, 0xAA, 0xA4))
        result = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(saved_games), 0, None, ctypes.byref(result)):return None
        try:return Path(result.value)
        finally:ctypes.windll.ole32.CoTaskMemFree(result)
    except (OSError, AttributeError, ValueError):
        return None


def base(environment=None):
    """The per-user SkylandersPC folder (not created here)."""
    environment = os.environ if environment is None else environment
    override = environment.get('SKYLANDERS_DATA')
    if override:
        if not Path(override).is_absolute():raise OSError('SKYLANDERS_DATA must be an absolute path')
        return Path(override)
    if WINDOWS:
        folder = _saved_games() if environment is os.environ else None
        profile = environment.get('USERPROFILE')
        if folder is None:
            if not profile or not Path(profile).is_absolute():raise OSError('an absolute USERPROFILE is required for saves')
            folder = Path(profile)/'Saved Games'
        return folder/NAME
    data = environment.get('XDG_DATA_HOME')
    home = environment.get('HOME', str(Path.home()))
    if data and Path(data).is_absolute():return Path(data)/NAME
    if not Path(home).is_absolute():raise OSError('HOME or an absolute XDG_DATA_HOME is required for saves')
    return Path(home)/'.local/share'/NAME


def legacy_home(environment=None):
    """The `skylanders-pc` folder of older versions."""
    environment = os.environ if environment is None else environment
    if WINDOWS:
        local = environment.get('LOCALAPPDATA')
        return Path(local)/'skylanders-pc' if local and Path(local).is_absolute() else None
    data = environment.get('XDG_DATA_HOME')
    home = environment.get('HOME', str(Path.home()))
    if data and Path(data).is_absolute():return Path(data)/'skylanders-pc'
    return Path(home)/'.local/share/skylanders-pc' if Path(home).is_absolute() else None


def adopted(root):
    """Whether this install folder uses the per-user figures and settings."""
    marker = Path(root)/MARKER
    return marker.is_file() and not marker.is_symlink()


def path(root, legacy, environment=None):
    """Where an install-folder path of older versions lives now."""
    if legacy not in INSTALL_LAYOUT:raise KeyError(legacy)
    return base(environment)/INSTALL_LAYOUT[legacy] if adopted(root) else Path(root)/legacy


def _same(source, target):
    if source.is_file():return target.is_file() and filecmp.cmp(source, target, shallow=False)
    if not target.is_dir():return False
    for item in source.rglob('*'):
        other = target/item.relative_to(source)
        if item.is_file() and not (other.is_file() and filecmp.cmp(item, other, shallow=False)):return False
        if item.is_dir() and not other.is_dir():return False
    return True


def _copy(source, target):
    """Copy a file or folder to a target that doesn't exist yet, then check every byte."""
    if source.is_symlink() or target.exists() or target.is_symlink():return False
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name+'.copying')
    if staging.is_dir():shutil.rmtree(staging)
    elif staging.exists():staging.unlink()
    if source.is_dir():shutil.copytree(source, staging, symlinks=False)
    else:shutil.copy2(source, staging)
    if not _same(source, staging):
        shutil.rmtree(staging) if staging.is_dir() else staging.unlink()
        raise OSError(f'copy of {source} did not verify')
    staging.replace(target)
    return True


def migrate(root=None, environment=None):
    """Copy older data into the per-user folder once. Returns a report dict.

    Nothing is overwritten or deleted: a target that already holds different
    data is reported as a conflict and the old copy is left in place.
    """
    destination = base(environment)
    report = {'copied': [], 'conflicts': []}
    old = legacy_home(environment)
    done = destination/'.migrated-from-skylanders-pc'
    if old and old.is_dir() and not old.is_symlink() and not done.exists():
        for name in HOME_LAYOUT:
            source = old/name
            if not source.exists() or source.is_symlink():continue
            target = destination/name
            if target.exists():
                if not _same(source, target):report['conflicts'].append(str(source))
                continue
            if _copy(source, target):report['copied'].append(str(source))
        destination.mkdir(parents=True, exist_ok=True)
        done.write_text(json.dumps({'from': str(old), 'conflicts': report['conflicts']}, indent=2)+'\n')
    if root is not None:
        root = Path(root)
        if not adopted(root):
            for legacy, place in INSTALL_LAYOUT.items():
                source = root/legacy
                if not source.exists() or source.is_symlink():continue
                target = destination/place
                if target.exists():
                    if not _same(source, target):report['conflicts'].append(str(source))
                    continue
                if _copy(source, target):report['copied'].append(str(source))
            marker = root/MARKER
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({'version': 1, 'conflicts': report['conflicts']}, indent=2)+'\n')
    destination.mkdir(parents=True, exist_ok=True)
    readme = destination/'README.txt'
    if not readme.exists():
        readme.write_text('SkylandersPC keeps your saves, trophies, figures and settings here.\n'
                          'Back up this whole folder to keep your progress.\n')
    return report


if __name__ == '__main__':
    print(base())
    if sys.argv[1:] == ['--migrate']:
        print(json.dumps(migrate(Path(__file__).resolve().parents[1]), indent=2))

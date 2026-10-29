# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate extracted packages before publishing a complete local installation."""
from pathlib import Path
import struct
try:
    from .workspace import read_sfo
except ImportError:
    from workspace import read_sfo

BUILTIN_EXTRACTOR = Path(__file__).resolve().with_name('pkg_extract.py')


def extracted_root(directory):
    candidates = [p.parent.parent for p in Path(directory).rglob('sce_sys/param.sfo')]
    if len(candidates) != 1:
        raise ValueError('Extractor output must contain exactly one sce_sys/param.sfo')
    root = candidates[0]
    if any(p.is_symlink() for p in Path(directory).rglob('*')):
        raise ValueError('Extracted packages cannot contain symlinks')
    try:
        return root, read_sfo((root / 'sce_sys/param.sfo').read_bytes())
    except (struct.error, UnicodeError) as error:
        raise ValueError('Invalid extracted game metadata') from error


def publish(staging, destination, source_packages=()):
    """Validate extractor outputs and publish them into the versioned library."""
    try:
        from . import game_library
    except ImportError:
        import game_library
    staging = Path(staging)
    base = extracted_root(staging / 'base')[0] if (staging / 'base').exists() else None
    update = extracted_root(staging / 'update')[0] if (staging / 'update').exists() else None
    return game_library.publish(destination, base, update, source_packages)


def package_info(path):
    """Read the small PKG metadata entry before starting a lengthy extraction."""
    try:
        from .pkg_extract import Package
    except ImportError:
        from pkg_extract import Package
    try:
        with Path(path).open('rb') as stream:
            package = Package(stream)
            return read_sfo(package.entry_data(0x1000))
    except (OSError,ValueError,struct.error,UnicodeError) as error:
        raise ValueError('Could not read '+Path(path).name+'. Choose a complete PS4 PKG file.') from error


def check_packages(game_pkg=None, update_pkg=None, installed=()):
    """Explain mistaken package selections before unpacking either large file."""
    try:
        from .game_install import version
    except ImportError:
        from game_install import version
    base = package_info(game_pkg) if game_pkg else None
    update = package_info(update_pkg) if update_pkg else None
    if base and base.get('CATEGORY') != 'gd':
        raise ValueError('This looks like an update. Choose the game file first, then add the update in the next step.')
    if update and update.get('CATEGORY') != 'gp':
        raise ValueError('This looks like the game itself. Choose it in the first step, or choose an update file here.')
    if update and not base:
        matches = [e for e in installed if e['title_id'] == update.get('TITLE_ID') and e['content_id'] == update.get('CONTENT_ID')]
        if not matches:
            raise ValueError('Install the game first, or choose its game file as well as this update.')
        base = dict(TITLE_ID=matches[0]['title_id'], CONTENT_ID=matches[0]['content_id'], APP_VER=matches[0]['base_version'])
    if base:
        version(base.get('APP_VER'))
    if update and (update.get('TITLE_ID') != base.get('TITLE_ID') or update.get('CONTENT_ID') != base.get('CONTENT_ID') or version(update.get('APP_VER')) <= version(base.get('APP_VER'))):
        raise ValueError('This update does not match your game, or is older than your game file. Choose a newer update for the same game.')

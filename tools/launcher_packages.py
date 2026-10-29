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

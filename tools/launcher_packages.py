# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate extracted packages before publishing a complete local installation."""
from pathlib import Path
import shutil
import struct
try:
    from .workspace import read_sfo
    from .game_install import version
except ImportError:
    from workspace import read_sfo
    from game_install import version

DEFAULT_EXTRACTOR = Path('/home/temp/Downloads/ps4-pkg-tools-Linux/ps4-pkg-tool')


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


def publish(staging, destination, trap_team=False):
    """Move validated base/update together; rollback moves on a publication error."""
    staging, destination = Path(staging), Path(destination)
    base, meta = extracted_root(staging / 'base')
    if meta.get('CATEGORY') != 'gd' or not (base / 'eboot.bin').is_file():
        raise ValueError('Base package needs game metadata and eboot.bin')
    version(meta.get('APP_VER'))
    if trap_team and meta.get('TITLE_ID') not in ('CUSA00697','CUSA00626'):
        raise ValueError('This package is not a supported Trap Team title')
    roots = [('base', base)]
    if (staging / 'update').exists():
        update, patch = extracted_root(staging / 'update')
        if (patch.get('CATEGORY') != 'gp' or patch.get('TITLE_ID') != meta.get('TITLE_ID')
                or patch.get('CONTENT_ID') != meta.get('CONTENT_ID')
                or version(patch.get('APP_VER')) <= version(meta.get('APP_VER'))):
            raise ValueError('Update must match the base title/content ID and have a newer version')
        roots.append(('update',update))
    destination.mkdir(parents=True,exist_ok=True)
    if trap_team and any(destination.glob('*/sce_sys/param.sfo')):
        raise ValueError('Game/ already has an installation. Extracted files are retained in the import folder; existing files were kept.')
    moved = []
    try:
        for kind, source in roots:
            target = destination / (staging.name + '-' + kind)
            if target.exists(): raise ValueError('Installation destination already exists')
            shutil.move(str(source),str(target)); moved.append((source,target))
    except BaseException:
        for source,target in reversed(moved):
            source.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(target),str(source))
        raise
    return [str(target) for _,target in moved]

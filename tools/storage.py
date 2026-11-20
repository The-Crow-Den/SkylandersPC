# SPDX-License-Identifier: GPL-3.0-or-later
"""Disk space used by the launcher's folders, and clearing the rebuildable ones."""
import os
import shutil
from pathlib import Path

try:
    from . import game_library
except ImportError:
    import game_library

# key: (label, folders relative to the project, clearable, what clearing means)
AREAS = {
    'games': ('Installed games', None, False, ''),
    'saves': ('Saves', ('out/ps4-saves',), False, ''),
    'shaders': ('Saved shaders', ('out/native-gpu-user/cache',), True,
                'New areas compile shaders again on their first visit, which can stutter.'),
    'caches': ('Rebuildable caches', ('out/asset-mod-cache', 'out/movie-audio-cache'), True,
               'Mods and movie audio are prepared again on the next start, which takes longer once. Each is capped by the cache size limit above.'),
    'temporary': ('Temporary files', ('out/session-temp', '.local/pkg-imports', 'out/last-session'), True,
                  'Leftovers from earlier sessions and installs. The last crash report is removed too.'),
}


def folders(root, key):
    root = Path(root)
    if key == 'games':
        # Games installed elsewhere (registered in place) count where they are.
        found = [Path(game_library.directory(root))]
        try:
            for entry in game_library.entries(root):
                for name in ('base_path', 'update_path'):
                    if entry.get(name):found.append(Path(entry[name]))
        except (OSError, ValueError):
            pass
        unique = []
        for path in sorted(set(found), key=lambda p: len(p.parts)):
            if not any(path.is_relative_to(kept) for kept in unique):unique.append(path)
        return unique
    return [root / relative for relative in AREAS[key][1]]


def size(path):
    """Bytes on disk under path; hard links count once, symlinks are not followed."""
    total, seen, stack = 0, set(), [Path(path)]
    while stack:
        try:
            entries = os.scandir(stack.pop())
        except OSError:
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        info = entry.stat(follow_symlinks=False)
                        if (info.st_dev, info.st_ino) not in seen:
                            seen.add((info.st_dev, info.st_ino)); total += info.st_size
                except OSError:
                    pass
    return total


def usage(root):
    rows = [{'key': key, 'label': label, 'bytes': sum(size(f) for f in folders(root, key)),
             'clearable': clearable, 'note': note} for key, (label, _, clearable, note) in AREAS.items()]
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = None
    return rows, free


def clear(root, key):
    """Empty a clearable area's folders (the folders themselves stay). Returns bytes freed."""
    if not AREAS[key][2]:
        raise ValueError(AREAS[key][0] + ' cannot be cleared here')
    before = sum(size(folder) for folder in folders(root, key))
    for folder in folders(root, key):
        if folder.is_symlink() or not folder.is_dir():
            continue
        for child in folder.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    freed = before - sum(size(folder) for folder in folders(root, key))
    return freed


def human(count):
    for unit in ('bytes', 'KB', 'MB', 'GB', 'TB'):
        if count < 1024 or unit == 'TB':
            return f'{count:.0f} {unit}' if unit == 'bytes' else f'{count:.1f} {unit}'
        count /= 1024

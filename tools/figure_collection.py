# SPDX-License-Identifier: GPL-3.0-or-later
"""Virtual Skylander collection shared with the in-game portal drawer.

Library tags live in out/portal-library/characters. Once a tag has been placed,
the game writes progress to a private working copy in out/figures named by the
FNV-1a hash of the library file, so that copy is the one shown and edited.
"""
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil

try:
    from . import figure_data
except ImportError:
    import figure_data

NAME_PATTERN = re.compile(r'\{\{(\d+),\s*0x([0-9A-Fa-f]{1,4})\},\s*"([^"]+)"\}')


def fnv1a64(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


def creatable(identity, variant):
    """Characters, swapper halves and items the native portal can place (see portal_library_adapter.cpp)."""
    character = (identity <= 32 or 100 <= identity <= 115 or identity in (404, 416, 419, 430) or
                 450 <= identity <= 485 or 502 <= identity <= 543 or 3000 <= identity <= 3015 or
                 figure_data.swapper_half(identity) is not None)
    return (character or figure_data.kind(identity) == 'item') and variant < 0x4000


def source_root(root):
    cache = Path(root) / '.local/native-gpu-build/CMakeCache.txt'
    try:
        for line in cache.read_text().splitlines():
            if line.startswith('SKY_PORTAL_SOURCE_ROOT:PATH=') and line.split('=', 1)[1]:
                return Path(line.split('=', 1)[1])
    except OSError:
        pass
    return Path(root).resolve().parents[1]


def names(root):
    """Figure names from the portal sources the native build uses, cached privately."""
    cache = Path(root) / '.local/portal-assets/figure-names.json'
    try:
        return {tuple(map(int, key.split(':'))): name for key, name in json.loads(cache.read_text()).items()}
    except (OSError, ValueError):
        pass
    try:
        text = (source_root(root) / 'Cemu-main/src/Cafe/OS/libs/nsyshid/Skylander.cpp').read_text(errors='replace')
    except OSError:
        return {}
    found = {(int(i), int(v, 16)): name for i, v, name in NAME_PATTERN.findall(text)}
    if found:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({f'{i}:{v}': n for (i, v), n in sorted(found.items())}, indent=1) + '\n')
        except OSError:
            pass
    return found


class Entry:
    def __init__(self, collection, path):
        self.collection = collection
        self.path = Path(path)
        library = self.path.read_bytes()
        if len(library) != figure_data.SIZE:
            raise figure_data.FigureError('not a 1024-byte figure')
        self.working = collection.figures / f'import-{fnv1a64(library):016x}.sky'
        if self.working.is_symlink() or not self.working.is_file():
            self.working = None
        self.figure = figure_data.Figure((self.working or self.path).read_bytes(), collection.seed)

    @property
    def name(self):
        figure = self.figure
        return self.collection.names.get((figure.identity, figure.variant)) or \
            self.collection.names.get((figure.identity, 0)) or f'Skylander {figure.identity}'

    @property
    def created(self):
        return self.path.name.startswith('created-')


class Collection:
    def __init__(self, root):
        self.root = Path(root)
        self.characters = self.root / 'out/portal-library/characters'
        self.figures = self.root / 'out/figures'
        self.backups = self.root / 'out/figure-backups'
        self.removed = self.root / 'out/portal-library/removed'
        self.seed = figure_data.load_seed(root)
        self.names = names(root)

    def entries(self):
        found = {}
        if self.characters.is_dir():
            # Created tags first: an identical hash-named copy is the native
            # importer's duplicate of a created tag and shares its progress.
            for path in sorted(self.characters.glob('*.sky'), key=lambda p: (not p.name.startswith('created-'), p.name)):
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    entry = Entry(self, path)
                except (OSError, figure_data.FigureError):
                    continue
                if entry.figure.kind != 'trap':
                    found.setdefault(fnv1a64(path.read_bytes()), entry)
        return sorted(found.values(), key=lambda e: (e.figure.kind != 'character', e.name.lower(), e.path.name))

    def choices(self):
        return sorted(((name, i, v) for (i, v), name in self.names.items() if creatable(i, v)), key=lambda c: c[0].lower())

    def _publish(self, data, prefix='created-'):
        self.characters.mkdir(parents=True, exist_ok=True)
        for _ in range(16):
            path = self.characters / f'{prefix}{secrets.token_urlsafe(4)[:6]}.sky'
            try:
                with open(path, 'xb') as output:
                    output.write(data)
                return path
            except FileExistsError:
                continue
        raise OSError('Could not choose a new figure file name')

    def create(self, identity, variant):
        if not creatable(identity, variant):
            raise figure_data.FigureError('This Skylander cannot be created for the virtual portal.')
        return Entry(self, self._publish(figure_data.blank(identity, variant)))

    def import_dump(self, path):
        data = Path(path).read_bytes()
        figure = figure_data.Figure(data, self.seed)
        if figure.kind == 'trap':
            raise figure_data.FigureError('Traps are managed in the game’s trap drawer.')
        self.characters.mkdir(parents=True, exist_ok=True)
        # Same content-addressed name the native importer uses, so a later
        # in-game import of this dump finds the existing entry.
        destination = self.characters / f'{fnv1a64(data):016x}.sky'
        if not destination.exists():
            with open(destination, 'xb') as output:
                output.write(data)
        return Entry(self, destination)

    def duplicate(self, entry):
        return Entry(self, self._publish(figure_data.rekey(entry.figure.raw, self.seed)))

    def backup(self, entry):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.backups.mkdir(parents=True, exist_ok=True)
        target = self.backups / f'{entry.path.stem}-{stamp}.sky'
        shutil.copyfile(entry.working or entry.path, target)
        return target

    def save(self, entry, data):
        """Write edited progress where the game will read it, after a backup."""
        check = figure_data.Figure(data, self.seed)
        if check.raw[:0x20] != entry.figure.raw[:0x20]:
            raise figure_data.FigureError('Edited data does not belong to this figure.')
        self.backup(entry)
        target = entry.working or entry.path
        temporary = target.with_name(target.name + '.tmp')
        with open(temporary, 'xb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        if entry.working is None:
            # Never placed: the library file itself is the save. Its content
            # hash changes, so nothing is left pointing at a stale copy.
            return Entry(self, target)
        return Entry(self, entry.path)

    def remove(self, entry):
        """Move a figure and its progress aside instead of deleting it."""
        folder = self.removed / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        folder.mkdir(parents=True)
        if entry.working is not None:
            shutil.move(str(entry.working), folder / ('progress-' + entry.path.name))
        library = entry.path.read_bytes()
        twins = [p for p in self.characters.glob('*.sky') if p != entry.path and not p.is_symlink() and p.read_bytes() == library]
        for path in [entry.path, *twins]:
            shutil.move(str(path), folder / path.name)
        return folder

    def export(self, entry, destination):
        shutil.copyfile(entry.working or entry.path, destination)

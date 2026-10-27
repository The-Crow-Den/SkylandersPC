# SPDX-License-Identifier: GPL-3.0-or-later
"""Select a title-specific save directory without copying or rewriting saves."""
import hashlib
import shutil
import tempfile
import json
import os
from pathlib import Path
import re


def home_root(environment=None):
    environment = os.environ if environment is None else environment
    data = environment.get('XDG_DATA_HOME')
    base = Path(data) if data and Path(data).is_absolute() else Path(environment.get('HOME', str(Path.home())))/'.local/share'
    return base/'skylanders-pc/saves'


def _manifest(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError('save migration refuses links or special files')
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            result[str(path.relative_to(directory))] = digest.hexdigest()
    return result


def migrate(source, destination, title_id):
    """Copy one title without overwriting an existing save or removing originals.

    Caller must hold the game session lock; saves must not be mounted while
    taking this snapshot. A conflicting destination is an error, never merged.
    """
    if not isinstance(title_id, str) or not re.fullmatch(r'CUSA\d{5}', title_id):
        raise ValueError('invalid save profile title identity')
    source, destination = Path(source), Path(destination)
    origin, target = source/title_id, destination/title_id
    if origin.is_symlink() or not origin.is_dir() or origin.resolve() != origin:
        raise ValueError('invalid source save directory')
    expected = _manifest(origin)
    if not expected:
        raise ValueError('source save is empty')
    if destination.is_symlink() or destination.resolve() != destination:
        raise ValueError('redirected destination save directory')
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir() or _manifest(target) != expected:
            raise ValueError('destination already contains different saves; nothing overwritten')
        return expected
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.save-migration-', dir=destination) as temporary:
        staged = Path(temporary)/title_id
        shutil.copytree(origin, staged, symlinks=True)
        if _manifest(staged) != expected or _manifest(origin) != expected:
            raise ValueError('save changed during migration')
        # mkdir reserves the final name without replacing an existing directory.
        target.mkdir()
        try:
            # Publish the complete tree in one rename over our empty reserved
            # directory. An interrupted migration cannot expose partial files.
            os.replace(staged,target)
        except BaseException:
            # Only remove an empty reservation; never delete another writer's
            # files if the destination changed unexpectedly.
            try:
                target.rmdir()
            except OSError:
                pass
            raise
    return expected


def select(root, title_id, explicit=None, environment=None):
    root = Path(root).resolve()
    environment = os.environ if environment is None else environment
    if not isinstance(title_id, str) or not re.fullmatch(r'CUSA\d{5}', title_id):
        raise ValueError('invalid save profile title identity')
    if explicit is not None:
        return Path(explicit).expanduser().resolve(), 'command-line'
    if environment.get('SKY_SAVE_DATA_ROOT'):
        return Path(environment['SKY_SAVE_DATA_ROOT']).expanduser().resolve(), 'environment'
    profile = root/'out/play-profiles'/f'{title_id}.json'
    if not profile.exists():
        if profile.is_symlink():raise ValueError('redirected save profile')
        return home_root(environment), 'home-default'
    if profile.is_symlink() or profile.resolve() != profile or profile.stat().st_size > 16384:
        raise ValueError('invalid or redirected save profile')
    record = json.loads(profile.read_text())
    if (not isinstance(record, dict) or type(record.get('schema_version')) is not int or
            record['schema_version'] != 1 or
            record.get('title_id') != title_id or
            not isinstance(record.get('save_root'), str) or not record['save_root']):
        raise ValueError('invalid save profile')
    path = Path(record['save_root'])
    if (not path.is_absolute() or path.is_symlink() or path.resolve() != path or
            not (path.is_relative_to(root/'out') or path == home_root(environment)) or not (path/title_id).is_dir() or
            (path/title_id).is_symlink() or (path/title_id).resolve() != path/title_id):
        raise ValueError('save profile must select an existing private title directory')
    return path, 'saved-profile'

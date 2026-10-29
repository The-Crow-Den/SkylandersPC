# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned installation manifests; game data and user preferences stay separate."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

try:
    from . import game_install
    from .workspace import read_sfo
except ImportError:
    import game_install
    from workspace import read_sfo


def directory(project):
    return Path(project) / 'Games'


def selector(title_id, app_version):
    if not isinstance(title_id, str) or not re.fullmatch(r'CUSA\d{5}', title_id):
        raise ValueError('Invalid library title ID')
    game_install.version(app_version)
    return title_id + '@' + app_version


def split_selector(value):
    parts = value.split('@') if isinstance(value, str) else []
    if len(parts) not in (1, 2) or not re.fullmatch(r'CUSA\d{5}', parts[0]):
        raise ValueError('Choose a game as TITLE_ID[@APP_VER]')
    if len(parts) == 2:
        game_install.version(parts[1])
    return parts[0], parts[1] if len(parts) == 2 else None


def metadata(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Game installation refuses symlinks')
    sfo = path / 'sce_sys/param.sfo'
    if sfo.is_symlink() or sfo.parent.is_symlink():
        raise ValueError('Game metadata refuses symlinks')
    value = read_sfo(sfo.read_bytes())
    selector(value.get('TITLE_ID'), value.get('APP_VER'))
    if not isinstance(value.get('CONTENT_ID'), str) or not value['CONTENT_ID']:
        raise ValueError('Game metadata needs a content ID')
    if value.get('CATEGORY') not in ('gd', 'gp'):
        raise ValueError('Expected a base game or update package')
    return value


def profiles(project):
    """Only validated_builds associate console title IDs with a launcher profile."""
    result = []
    for path in sorted((Path(project) / 'profiles').glob('*.json')):
        value = json.loads(path.read_text())
        if 'validated_builds' in value:
            result.append(value)
    return result


def profile_for(project, entry):
    for profile in profiles(project):
        if any(build.get('title_id') == entry['title_id'] for build in profile['validated_builds']):
            return profile
    return None


def supported(project, entry):
    profile = profile_for(project, entry)
    return bool(profile and any((b.get('title_id'), b.get('app_version'), b.get('executable_sha256')) ==
        (entry['title_id'], entry['app_version'], entry['executable_sha256']) for b in profile['validated_builds']))


def manifest_path(library, entry):
    selector(entry['title_id'], entry['app_version'])
    return Path(library) / entry['title_id'] / entry['app_version'] / 'manifest.json'


def write_json(path, value):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Library metadata path refuses symlinks')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(library):
    library = Path(library)
    if any(p.is_symlink() for p in (library, *library.parents)):
        raise ValueError('Library path refuses symlinks')
    library.mkdir(parents=True, exist_ok=True)
    with (library / '.library.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def make_entry(base, update=None, source_packages=()):
    identity = metadata(base)
    base = Path(base).resolve()
    if identity['CATEGORY'] != 'gd' or not (base / 'eboot.bin').is_file():
        raise ValueError('Base package needs game metadata and eboot.bin')
    patch = None
    if update:
        patch = metadata(update)
        update = Path(update).resolve()
        if (patch['CATEGORY'] != 'gp' or patch['TITLE_ID'] != identity['TITLE_ID'] or
                patch['CONTENT_ID'] != identity['CONTENT_ID'] or
                game_install.version(patch['APP_VER']) <= game_install.version(identity['APP_VER'])):
            raise ValueError('Update must match the base title/content ID and have a newer version')
    executable = (update / 'eboot.bin') if update and (update / 'eboot.bin').is_file() else base / 'eboot.bin'
    if executable.is_symlink():
        raise ValueError('Game executable refuses symlinks')
    with executable.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(schema_version=1, title=identity.get('TITLE', identity['TITLE_ID']),
        title_id=identity['TITLE_ID'], content_id=identity['CONTENT_ID'],
        app_version=patch['APP_VER'] if patch else identity['APP_VER'], base_version=identity['APP_VER'],
        update_version=patch['APP_VER'] if patch else None, base_path=str(base),
        update_path=str(update) if update else None, executable_sha256=digest,
        install_date=datetime.now(timezone.utc).isoformat(),
        source_packages=[Path(name).name for name in source_packages if name])


def validate_entry(entry):
    if not isinstance(entry, dict) or entry.get('schema_version') != 1:
        raise ValueError('Invalid installation manifest schema')
    try:
        selector(entry['title_id'], entry['app_version'])
        game_install.version(entry['base_version'])
        if entry['update_version'] is not None:
            game_install.version(entry['update_version'])
        if entry['app_version'] != (entry['update_version'] or entry['base_version']):
            raise ValueError('Installation manifest version mismatch')
        if entry['update_version'] and game_install.version(entry['update_version']) <= game_install.version(entry['base_version']):
            raise ValueError('Installation manifest update must be newer')
        for key in ('title', 'content_id', 'install_date'):
            if not isinstance(entry[key], str) or not entry[key]:
                raise ValueError('Invalid manifest field ' + key)
        datetime.fromisoformat(entry['install_date'])
        if not re.fullmatch(r'[a-f0-9]{64}', entry['executable_sha256']):
            raise ValueError('Invalid manifest executable hash')
        if not Path(entry['base_path']).is_absolute() or (entry['update_path'] is not None and not Path(entry['update_path']).is_absolute()):
            raise ValueError('Manifest game paths must be absolute')
        if bool(entry['update_path']) != bool(entry['update_version']):
            raise ValueError('Manifest update path/version mismatch')
        if not isinstance(entry['source_packages'], list) or any(not isinstance(p, str) or '/' in p or '\\' in p for p in entry['source_packages']):
            raise ValueError('Invalid source package names')
    except (KeyError, TypeError) as error:
        raise ValueError('Invalid installation manifest fields') from error
    return entry


def load_entry(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Installation manifest refuses symlinks')
    return validate_entry(json.loads(path.read_text()))


def read_entries(library):
    result = []
    for path in sorted(Path(library).glob('CUSA*/*/manifest.json')):
        entry = load_entry(path)
        if manifest_path(library, entry) != path:
            raise ValueError('Manifest location does not match its title/version')
        result.append(entry)
    return result


def discover(entry):
    """Validate current metadata as well as the manifest before exposing its paths."""
    if not isinstance(entry, dict):
        path = Path(entry)
        entry = load_entry(path / 'manifest.json' if path.is_dir() else path)
    validate_entry(entry)
    base = Path(entry['base_path'])
    update = Path(entry['update_path']) if entry['update_path'] else None
    identity = metadata(base)
    if (identity['TITLE_ID'], identity['APP_VER'], identity['CONTENT_ID'], identity['CATEGORY']) != (
            entry['title_id'], entry['base_version'], entry['content_id'], 'gd'):
        raise ValueError('Installation manifest does not match base metadata')
    if (base / 'eboot.bin').is_symlink() or (update and (update / 'eboot.bin').is_symlink()):
        raise ValueError('Game executable refuses symlinks')
    if not (base / 'eboot.bin').is_file():
        raise ValueError('Installation base executable is missing')
    if update:
        patch = metadata(update)
        if (patch['TITLE_ID'], patch['APP_VER'], patch['CONTENT_ID'], patch['CATEGORY']) != (
                entry['title_id'], entry['update_version'], entry['content_id'], 'gp'):
            raise ValueError('Installation manifest does not match update metadata')
    return game_install.Install(base, update, entry['title_id'], entry['app_version'])


def register(project):
    """Idempotently reference old Game/ and earlier launcher imports, without moving them."""
    project = Path(project)
    folders = [project / 'Game']
    folders += sorted((project / '.local/library-games').glob('*'))
    candidates = []
    for folder in folders:
        for sfo in sorted(folder.glob('*/sce_sys/param.sfo')):
            path = sfo.parent.parent
            candidates.append((path, metadata(path)))
    legacy_entries = read_entries(project / '.local/game-library')
    if not candidates and not legacy_entries:
        return
    library = directory(project)
    with locked(library):
        existing = {selector(e['title_id'], e['app_version']): e for e in read_entries(library)}
        for entry in legacy_entries:
            key = selector(entry['title_id'], entry['app_version'])
            previous = existing.get(key)
            if previous:
                if (previous['base_path'], previous['update_path']) != (entry['base_path'], entry['update_path']):
                    raise ValueError('Ambiguous existing installation ' + key)
                continue
            write_json(manifest_path(library, entry), entry)
            existing[key] = entry
        for base, identity in candidates:
            if identity['CATEGORY'] != 'gd':
                continue
            updates = [(p, m) for p, m in candidates if m['CATEGORY'] == 'gp' and m['TITLE_ID'] == identity['TITLE_ID']]
            if any(m['CONTENT_ID'] != identity['CONTENT_ID'] for _, m in updates):
                raise ValueError('Game update content ID differs from its base')
            versions = [m['APP_VER'] for _, m in updates]
            if len(set(versions)) != len(versions):
                raise ValueError('Ambiguous game update version')
            for update in [None, *(p for p, _ in updates)]:
                app_version = metadata(update)['APP_VER'] if update else identity['APP_VER']
                key = selector(identity['TITLE_ID'], app_version)
                previous = existing.get(key)
                if previous:
                    paths = (str(base.resolve()), str(update.resolve()) if update else None)
                    if (previous['base_path'], previous['update_path']) != paths:
                        raise ValueError('Ambiguous existing installation ' + key)
                    continue
                entry = make_entry(base, update)
                write_json(manifest_path(library, entry), entry)
                existing[key] = entry


def entries(project):
    register(project)
    return read_entries(directory(project))


def for_game(project, game):
    result = []
    for entry in entries(project):
        profile = profile_for(project, entry)
        if (profile and profile['id'] == game['id']) or game.get('title_id') == entry['title_id']:
            result.append(entry)
    return result


def resolve_entry(project, choice=None, game=None):
    available = for_game(project, game) if game is not None else entries(project)
    if choice is None and game is not None:
        choice = game.get('installation')
    if choice is None and game is None:
        saved = directory(project) / 'selection.json'
        if saved.exists():
            choice = json.loads(saved.read_text()).get('selected')
        else:
            # Read the launcher's per-game selection, including a deliberately empty one.
            launcher = Path(project) / '.local/launcher-library.json'
            if launcher.exists():
                value = json.loads(launcher.read_text())
                selected = next((g for g in value.get('games', []) if g['id'] == value.get('selected')), None)
                if selected and for_game(project, selected):
                    return resolve_entry(project, game=selected)
    if choice:
        title, ver = split_selector(choice)
        available = [e for e in available if e['title_id'] == title and (ver is None or e['app_version'] == ver)]
    titles = {e['title_id'] for e in available}
    if not available:
        raise ValueError('No matching game installation in the library')
    if len(titles) != 1:
        raise ValueError('Multiple titles installed; select --game TITLE_ID[@APP_VER]')
    return max(available, key=lambda e: game_install.version(e['app_version']))


def resolve(project, choice=None, game=None):
    return game_install.discover(resolve_entry(project, choice, game))


def select(project, choice):
    if choice is not None:
        entry = resolve_entry(project, choice)
        choice = selector(entry['title_id'], entry['app_version'])
    write_json(directory(project) / 'selection.json', {'selected': choice})


def publish(library, base=None, update=None, source_packages=()):
    """Publish a base and/or attach an update, rolling back only this transaction's files."""
    library = Path(library)
    if base is None and update is None:
        raise ValueError('Choose a game package or an update package')
    # Inspect all input before moving anything or creating manifests.
    for source in (base, update):
        if source and any(p.is_symlink() for p in Path(source).rglob('*')):
            raise ValueError('Extracted packages cannot contain symlinks')
    if base and update:
        make_entry(base, update, source_packages)
    identity = metadata(base) if base else metadata(update)
    if base and identity['CATEGORY'] != 'gd':
        raise ValueError('Base package needs game metadata and eboot.bin')
    with locked(library):
        existing = read_entries(library)
        if base is None:
            candidates = [e for e in existing if e['title_id'] == identity['TITLE_ID'] and
                          e['content_id'] == identity['CONTENT_ID'] and
                          game_install.version(e['base_version']) < game_install.version(identity['APP_VER'])]
            if not candidates:
                raise ValueError('Update needs an installed base with matching title/content ID')
            best = max(candidates, key=lambda e: game_install.version(e['base_version']))
            source_base = Path(best['base_path'])
        else:
            source_base = Path(base)
        initial = make_entry(source_base, update, source_packages)
        base_entry = make_entry(source_base, source_packages=source_packages)
        base_key = selector(base_entry['title_id'], base_entry['app_version'])
        previous = next((e for e in existing if selector(e['title_id'], e['app_version']) == base_key), None)
        moves = []
        if previous:
            if previous['content_id'] != base_entry['content_id'] or previous['executable_sha256'] != base_entry['executable_sha256']:
                raise ValueError('A different base already exists for this title/version')
            target_base = Path(previous['base_path'])
        elif base:
            target_base = manifest_path(library, base_entry).parent / 'base'
            moves.append((Path(base), target_base))
        else:
            target_base = source_base
        target_update = None
        if update:
            target_update = manifest_path(library, initial).parent / 'update'
            if any(e['title_id'] == initial['title_id'] and e['app_version'] == initial['app_version'] for e in existing):
                raise ValueError('Installation destination already exists for this title/version')
            moves.append((Path(update), target_update))
        elif previous:
            raise ValueError('Installation destination already exists for this title/version')
        new_entries = []
        if previous is None:
            new_entries.append({**base_entry, 'base_path': str(target_base.resolve())})
        if update:
            sources = list(dict.fromkeys((previous or base_entry)['source_packages'] + initial['source_packages']))
            new_entries.append({**initial, 'base_path': str(target_base.resolve()),
                                'update_path': str(target_update.resolve()), 'source_packages': sources})
        for _, target in moves:
            if target.exists() or any(p.is_symlink() for p in (target, *target.parents)):
                raise ValueError('Installation destination already exists or contains symlinks')
        moved, written = [], []
        try:
            for source, target in moves:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                moved.append((source, target))
            for entry in new_entries:
                path = manifest_path(library, entry)
                if path.exists():
                    raise ValueError('Installation manifest already exists')
                write_json(path, entry)
                written.append(path)
        except BaseException:
            for path in reversed(written):
                path.unlink()
            for source, target in reversed(moved):
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
            raise
        return new_entries[-1]

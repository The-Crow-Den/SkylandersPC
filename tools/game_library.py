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
import warnings

try:
    from . import game_install
    from .workspace import read_sfo
except ImportError:
    import game_install
    from workspace import read_sfo


def directory(project):
    try:
        from .library_preferences import locations
    except ImportError:
        from library_preferences import locations
    return locations(project)[0]


def libraries(project):
    try:
        from .library_preferences import locations
    except ImportError:
        from library_preferences import locations
    return locations(project)[1]


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
        for key in ('base_path','update_path'):
            if entry[key] is not None:
                path = Path(entry[key])
                if not str(path) or '..' in path.parts or (not path.is_absolute() and ('\\' in str(path) or ':' in str(path))):
                    raise ValueError('Invalid manifest game path')
        if bool(entry['update_path']) != bool(entry['update_version']):
            raise ValueError('Manifest update path/version mismatch')
        if not isinstance(entry['source_packages'], list) or any(not isinstance(p, str) or '/' in p or '\\' in p for p in entry['source_packages']):
            raise ValueError('Invalid source package names')
    except (KeyError, TypeError) as error:
        raise ValueError('Invalid installation manifest fields') from error
    return entry


def store_entry(library, entry):
    """On disk, managed paths are relative to the library, never the checkout."""
    library = Path(library).resolve()
    stored = dict(entry)
    for key in ('base_path','update_path'):
        if stored[key]:
            path = Path(stored[key])
            try:stored[key] = path.relative_to(library).as_posix()
            except ValueError:stored[key] = str(path)
    validate_entry(stored)
    path = manifest_path(library,stored)
    content = json.dumps(stored,indent=2)+'\n'
    if path.is_file() and not path.is_symlink() and path.read_text()==content:return
    write_json(path,stored)


def load_entry(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Installation manifest refuses symlinks')
    entry = validate_entry(json.loads(path.read_text()))
    library = path.parents[2]
    for key,kind,version_key in (('base_path','base','base_version'),('update_path','update','update_version')):
        if not entry[key]:continue
        location = Path(entry[key])
        if not location.is_absolute():location = library/location
        elif not location.exists():
            # Upgrade old absolute managed manifests after a checkout relocation.
            tail = Path(entry['title_id'])/entry[version_key]/kind
            if tuple(location.parts[-3:])==tail.parts and (library/tail).is_dir():location = library/tail
        if any(p.is_symlink() for p in (location,*location.parents)):
            raise ValueError('Installation path refuses symlinks')
        entry[key] = str(location)
    return entry


def report(issues, path, error, title_id=None, app_version=None):
    issue = dict(path=str(path), message=str(error), state='Needs repair')
    if title_id:issue['title_id'] = title_id
    if app_version:issue['app_version'] = app_version
    if issues is None:warnings.warn(f'{path}: {error}', RuntimeWarning, stacklevel=2)
    elif issue not in issues:issues.append(issue)


def read_entries(library, issues=None):
    result = []
    for path in sorted(Path(library).glob('CUSA*/*/manifest.json')):
        try:
            entry = load_entry(path)
            if manifest_path(Path(library).absolute(), entry) != path.absolute():
                raise ValueError('Manifest location does not match its title/version')
            result.append(entry)
        except (OSError,ValueError,KeyError,TypeError) as error:
            report(issues,path,error,path.parent.parent.name,path.parent.name)
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


def register(project, issues=None):
    """Reference old installs in place. A bad source never blocks unrelated titles."""
    project = Path(project).absolute();library = directory(project)
    candidates = []
    for folder in [project/'Game',*sorted((project/'.local/library-games').glob('*'))]:
        for sfo in sorted(folder.glob('*/sce_sys/param.sfo')):
            try:candidates.append((sfo.parent.parent,metadata(sfo.parent.parent)))
            except (OSError,ValueError) as error:report(issues,sfo,error)
    legacy = read_entries(project/'.local/game-library',issues)
    for previous in libraries(project):
        if previous!=library:legacy.extend(read_entries(previous,issues))
    if not candidates and not legacy:
        for entry in read_entries(library,issues):
            try:store_entry(library,entry)
            except (OSError,ValueError) as error:report(issues,manifest_path(library,entry),error,entry['title_id'],entry['app_version'])
        return
    with locked(library):
        existing = {selector(e['title_id'],e['app_version']):e for e in read_entries(library,issues)}
        def add(entry):
            key = selector(entry['title_id'],entry['app_version']);previous = existing.get(key)
            if previous:
                if (previous['base_path'],previous['update_path']) != (entry['base_path'],entry['update_path']):
                    # External Game/ references move with the project: re-register only
                    # when old sources are gone and the new executable/identity agree.
                    old_missing = not Path(previous['base_path']).exists() or (previous['update_path'] and not Path(previous['update_path']).exists())
                    if not old_missing or any(previous[k]!=entry[k] for k in ('content_id','executable_sha256','base_version','update_version')):
                        raise ValueError('Ambiguous existing installation '+key)
                    entry = {**entry,'install_date':previous['install_date'],'source_packages':previous['source_packages']}
                else:return
            target = manifest_path(library,entry)
            if previous is None and target.exists():raise ValueError('Existing manifest needs repair; it was kept')
            store_entry(library,entry);existing[key] = entry
        for entry in legacy:
            try:add(entry)
            except (OSError,ValueError) as error:report(issues,manifest_path(library,entry),error,entry['title_id'],entry['app_version'])
        for base,identity in candidates:
            if identity['CATEGORY']!='gd':continue
            updates = [(p,m) for p,m in candidates if m['CATEGORY']=='gp' and m['TITLE_ID']==identity['TITLE_ID']]
            sources = [None]
            for update,meta in updates:
                if meta['CONTENT_ID']!=identity['CONTENT_ID']:
                    report(issues,update,'Game update content ID differs from its base',meta['TITLE_ID'],meta['APP_VER']);continue
                if sum(m['APP_VER']==meta['APP_VER'] for _,m in updates)!=1:
                    report(issues,update,'Ambiguous game update version',meta['TITLE_ID'],meta['APP_VER']);continue
                sources.append(update)
            for update in sources:
                try:
                    app_version = metadata(update)['APP_VER'] if update else identity['APP_VER']
                    previous = existing.get(selector(identity['TITLE_ID'],app_version))
                    paths = (str(base.resolve()),str(update.resolve()) if update else None)
                    if previous and (previous['base_path'],previous['update_path'])==paths:continue
                    add(make_entry(base,update))
                except (OSError,ValueError) as error:report(issues,update or base,error,identity['TITLE_ID'])


def entries(project, issues=None):
    register(project,issues)
    result = [];seen = {}
    for library in libraries(project):
        for entry in read_entries(library,issues):
            try:
                discover(entry)
                key = selector(entry['title_id'],entry['app_version'])
                if key in seen:
                    if (seen[key]['base_path'],seen[key]['update_path'])!=(entry['base_path'],entry['update_path']):
                        report(issues,manifest_path(library,entry),'Another installation has this title and version',entry['title_id'],entry['app_version'])
                    continue
                seen[key] = entry;result.append(entry)
            except (OSError,ValueError) as error:
                report(issues,manifest_path(library,entry),error,entry['title_id'],entry['app_version'])
    return result


def for_game(project, game, issues=None):
    result = []
    for entry in entries(project,issues):
        profile = profile_for(project, entry)
        if (profile and profile['id'] == game['id']) or game.get('title_id') == entry['title_id']:
            result.append(entry)
    return result


def resolve_entry(project, choice=None, game=None):
    issues = []
    available = for_game(project, game,issues) if game is not None else entries(project,issues)
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
        relevant = [i for i in issues if (not choice or i.get('title_id')==split_selector(choice)[0]) and
            (game is None or game.get('title_id')==i.get('title_id') or (profile_for(project,{'title_id':i.get('title_id','')}) or {}).get('id')==game['id'])]
        if relevant:raise ValueError('Needs repair: '+relevant[0]['message'])
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
                store_entry(library, entry)
                written.append(path)
        except BaseException:
            for path in reversed(written):
                path.unlink()
            for source, target in reversed(moved):
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
            raise
        return new_entries[-1]

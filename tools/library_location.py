# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit Games-folder changes, with per-install rollback and no save/cache cleanup."""
from contextlib import ExitStack
import os
import errno
from pathlib import Path
import shutil
import stat
import uuid
try:
    from . import game_library as library, library_preferences
except ImportError:
    import game_library as library
    import library_preferences


def writable(path):
    path = Path(path)
    existing = path
    while not existing.exists():existing = existing.parent
    if not existing.is_dir() or not existing.stat().st_mode & (stat.S_IWUSR|stat.S_IWGRP|stat.S_IWOTH) or not os.access(existing,os.W_OK|os.X_OK):
        raise ValueError('Choose a Games folder you can write to.')
    if hasattr(os,'ST_RDONLY') and os.statvfs(existing).f_flag & os.ST_RDONLY:
        raise ValueError('The selected Games folder is on a read-only drive.')
    return existing


def tree_size(folder):
    total = 0
    for path in [folder,*folder.rglob('*')]:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError('A game folder contains a link or special file. It was kept in place.')
        if stat.S_ISREG(mode):total += path.stat().st_size
    return total


def managed(path, roots, project):
    path = Path(path).resolve()
    if path.is_relative_to((project/'Game').resolve()):return False
    return any(path.is_relative_to(root.resolve()) for root in roots)


def validate_destination(project, destination, entries, roots, move):
    destination = Path(destination).absolute()
    if destination.is_relative_to(project/'.local') or destination.is_relative_to(project/'out'):
        raise ValueError('Choose a Games folder outside the launcher’s working files.')
    if any(p.is_symlink() for p in (destination,*destination.parents)):
        raise ValueError('Choose a Games folder without symbolic links.')
    existing = writable(destination)
    sources = set()
    for entry in entries:
        for name in ('base_path','update_path'):
            if not entry[name]:continue
            source = Path(entry[name]).resolve()
            if destination.resolve().is_relative_to(source):
                raise ValueError('Choose a folder outside the installed game folders.')
            if move and managed(source,roots,project):sources.add(source)
        for root in roots:
            manifest = library.manifest_path(root,entry)
            if manifest.exists() and destination.resolve().is_relative_to(manifest.parent.resolve()) and destination.resolve()!=root.resolve():
                raise ValueError('Choose a folder outside the installed game folders.')
    required = 65536*(len(entries)+1)
    for source in sources:
        size = tree_size(source)
        if source.stat().st_dev!=existing.stat().st_dev:required += size
    if shutil.disk_usage(existing).free < required:
        raise ValueError('There is not enough free space in the selected Games folder.')
    return destination.resolve()


def redirected(entry, moves):
    result = dict(entry)
    for key in ('base_path','update_path'):
        if entry[key]:result[key] = str(moves.get(Path(entry[key]),Path(entry[key])))
    return result


def restore(path, content):
    if content is None:
        path.unlink(missing_ok=True) # Only a manifest created by this transaction.
    else:
        temporary = path.with_name('.restore-'+uuid.uuid4().hex)
        try:temporary.write_bytes(content);temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)


def transfer(source, target):
    try:
        os.rename(source,target)
        return 'renamed'
    except OSError as error:
        if error.errno!=errno.EXDEV:raise
    # Retain the complete source until every manifest has been committed.
    shutil.copytree(source,target)
    return 'copied'


def change(project, destination, *, move=False, progress=lambda value:None):
    project = Path(project).absolute();issues = []
    installed = library.entries(project,issues)
    roots = library.libraries(project)
    destination = validate_destination(project,destination,installed,roots,move)
    if destination==library.directory(project).resolve():return dict(moved=[],linked=[],errors=[],folder=str(destination))
    result = dict(moved=[],linked=[],errors=[],folder=str(destination))
    all_moves = {};blocked = set()
    # A change is an explicit user action. History is saved before transferring
    # data so interrupted moves never make earlier libraries disappear.
    with library.locked(project/'.local/library-location-change'):
        destination.mkdir(parents=True,exist_ok=True)
        library_preferences.save_location(project,destination,roots)
        if not move:
            library.register(project,issues)
            progress(dict(fraction=1,message='Games folder changed. Existing games were kept in place.'))
            return result
        with ExitStack() as stack:
            for root in sorted(set([destination,*[p for p in roots if p.is_dir()]])):
                stack.enter_context(library.locked(root))
            # Updates own their shared base transfer; don't move a base again
            # after the corresponding updated entry failed and rolled back.
            ordered = sorted(installed,key=lambda e:(bool(e['update_path']),e['app_version']),reverse=True)
            for index,original in enumerate(ordered):
                entry = redirected(original,all_moves)
                key = library.selector(entry['title_id'],entry['app_version'])
                progress(dict(fraction=index/max(1,len(ordered)),message=f'Moving game {index+1} of {len(ordered)}…'))
                if Path(original['base_path']) in blocked:
                    result['errors'].append(key+': kept with its related installation');continue
                transfers = []
                for name,kind,version in (('base_path','base',entry['base_version']),('update_path','update',entry['update_version'])):
                    if not entry[name]:continue
                    source = Path(entry[name]);target = destination/entry['title_id']/version/kind
                    if source!=target and managed(source,roots,project):transfers.append((source,target))
                moved = [];backups = {};own_partial = None;copied = set()
                try:
                    for source,target in transfers:
                        if target.exists():raise ValueError('A different game folder already exists at the destination.')
                        writable(source.parent)
                    target_manifest = library.manifest_path(destination,entry)
                    if target_manifest.exists():
                        previous = library.load_entry(target_manifest)
                        if any(previous[field]!=entry[field] for field in ('content_id','base_path','update_path','executable_sha256')):
                            raise ValueError('An installation with this title and version already exists at the destination.')
                    for source,target in transfers:
                        target.parent.mkdir(parents=True,exist_ok=True);own_partial = (source,target)
                        kind = transfer(source,target)
                        moved.append((source,target))
                        if kind=='copied':copied.add(source)
                        own_partial = None
                    mapping = dict(moved);updated = redirected(entry,mapping)
                    # Rewrite all manifests sharing a transferred base, not only
                    # the selected update, before publishing this entry.
                    for root in dict.fromkeys([*roots,destination]):
                        for related in library.read_entries(root,[]):
                            rewritten = redirected(related,mapping)
                            if rewritten!=related:
                                path = library.manifest_path(root,related)
                                backups.setdefault(path,path.read_bytes());library.store_entry(root,rewritten)
                    path = library.manifest_path(destination,updated)
                    backups.setdefault(path,path.read_bytes() if path.exists() else None)
                    library.store_entry(destination,updated)
                    all_moves.update(mapping);result['moved' if moved else 'linked'].append(key)
                    for source in copied:
                        try:shutil.rmtree(source)
                        except OSError as cleanup:result['errors'].append(key+': moved successfully; an old copy remains: '+str(cleanup))
                except (OSError,ValueError) as error:
                    if own_partial:
                        source,target = own_partial
                        if source.exists() and target.exists():
                            # shutil.move may leave a partial cross-drive copy.
                            # It cannot predate this transaction (checked above).
                            if target.is_dir():shutil.rmtree(target)
                            else:target.unlink()
                    rollback_errors = []
                    for source,target in reversed(moved):
                        try:
                            if source in copied:shutil.rmtree(target)
                            else:os.rename(target,source)
                        except OSError as rollback:rollback_errors.append(str(rollback))
                    if not rollback_errors:
                        for path,content in reversed(list(backups.items())):restore(path,content)
                    else:
                        # Keep recoverable copies and report their locations.
                        error = OSError(str(error)+'; rollback needs attention: '+'; '.join(rollback_errors))
                    blocked.add(Path(original['base_path']));result['errors'].append(key+': '+str(error))
            progress(dict(fraction=1,message='Checking the moved games…'))
        if all_moves:
            try:
                from . import game_prepare
            except ImportError:
                import game_prepare
            for entry in library.entries(project,[]):
                try:game_prepare.relocate_inputs(project,entry,all_moves)
                except (OSError,ValueError) as error:result['errors'].append(library.selector(entry['title_id'],entry['app_version'])+': setup needs Repair: '+str(error))
        progress(dict(fraction=1,message='Games folder updated.'))
    return result

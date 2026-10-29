# SPDX-License-Identifier: GPL-3.0-or-later
"""Player-facing library state and reversible removal of owned installation data."""
import os
from pathlib import Path
import uuid
try:
    from . import game_library,game_prepare
except ImportError:
    import game_library,game_prepare


def snapshot(root,game,active=None):
    if active:return dict(state=active['state'],message=active.get('message',''),entry=None,size=None,version='',fraction=active.get('fraction'))
    try:entry=game_library.resolve_entry(root,game=game)
    except (OSError,ValueError):
        issue=game.get('installation_issue','')
        return dict(state='Needs repair' if issue else 'Not installed',message='Choose Repair to check the installed files.' if issue else 'Install your game to get started.',entry=None,size=None,version='')
    seen=set();size=0
    for name in ('base_path','update_path'):
        if not entry[name]:continue
        for path in Path(entry[name]).rglob('*'):
            if path.is_symlink():continue
            if path.is_file():
                info=path.stat();key=(info.st_dev,info.st_ino)
                if key not in seen:size+=info.st_size;seen.add(key)
    state='Not supported';message='Your files are installed. This game is not supported yet.'
    if game_library.supported(root,entry):
        try:game_prepare.require_ready(root,entry,deep=False);state='Ready';message='Ready to play.'
        except (OSError,ValueError):state='Needs repair';message='Setup needs attention. Choose Repair to check and finish it.'
    version='Base '+entry['base_version']+(' · Update '+entry['update_version'] if entry['update_version'] else '')
    return dict(state=state,message=message,entry=entry,size=size,version=version)


def remove(root,game):
    """Hide this title's versions and move unshared managed files into recovery.

    Never delete originals, prepared packs, saves, figures or settings. Recovery
    files are deliberately excluded from automatic session/cache retention.
    """
    root=Path(root);choices=game_library.for_game(root,game,[])
    if not choices:raise ValueError('No installed game could be found.')
    others=[e for e in game_library.entries(root,[]) if e not in choices]
    shared={e[k] for e in others for k in ('base_path','update_path') if e[k]}
    owned=[]
    for entry in choices:
        for key in ('base_path','update_path'):
            if not entry[key] or entry[key] in shared:continue
            path=Path(entry[key])
            if path.is_relative_to(root/'Game'):continue
            if any(path.is_relative_to(folder) for folder in game_library.libraries(root)) and path not in owned:
                if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Cannot remove redirected installation files.')
                owned.append(path)
    recovery=root/'.local/removed-games'/uuid.uuid4().hex
    if any(p.is_symlink() for p in (recovery,*recovery.parents)):raise ValueError('Recovery folder cannot contain links.')
    moved=[];manifests=[]
    tombstones=game_library.removed(root)
    try:
        recovery.mkdir(parents=True)
        for index,path in enumerate(owned):
            target=recovery/str(index)
            # An atomic rename avoids blocking copies across drives. External
            # libraries retain their files and are only unregistered.
            if path.stat().st_dev!=recovery.stat().st_dev:continue
            os.rename(path,target);moved.append((path,target))
        for folder in game_library.libraries(root):
            for entry in choices:
                path=game_library.manifest_path(folder,entry)
                if path.is_file():
                    target=path.with_name('.removed-'+uuid.uuid4().hex+'.json')
                    os.rename(path,target);manifests.append((path,target))
        game_library.write_json(recovery/'recovery.json',dict(paths=[dict(original=str(a),recovery=str(b)) for a,b in moved],entries=choices))
        game_library.write_json(root/'.local/removed-games.json',list(dict.fromkeys([*tombstones,*[game_library.selector(e['title_id'],e['app_version']) for e in choices]])))
    except BaseException:
        for source,target in reversed(manifests):os.rename(target,source)
        for source,target in reversed(moved):os.rename(target,source)
        raise
    return recovery

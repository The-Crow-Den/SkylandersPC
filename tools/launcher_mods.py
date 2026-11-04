# SPDX-License-Identifier: GPL-3.0-or-later
"""Launcher view of mod.json mods: what is installed, whether it fits a game, and choices."""
import json
try:
    from .gameplay_mods import NAMES
    from . import mod_manifest
except ImportError:
    from gameplay_mods import NAMES
    import mod_manifest

# Built-in mods driven by their own option rather than a Mods page switch.
CONTROLLED = {
    'nightmare': 'Turned on by “Nightmare available by default” in Tweaks.',
    'level-events': 'Turned on by automatic FPS or “Record level events” in Performance.',
    'controller-glyphs': 'Follows the controller in use when Steam controller artwork has been imported.',
    'movie-audio': 'Used automatically on the US update.',
}


def validate(value):
    if (not isinstance(value,dict) or any(not isinstance(k,str) or not mod_manifest.IDENTIFIER.fullmatch(k) for k in value)
            or any(type(v) is not bool for v in value.values())):
        raise ValueError('Invalid per-game mods')
    return dict(value)


def validate_settings(value):
    if not isinstance(value,dict):raise ValueError('Invalid per-game mod settings')
    for ident,chosen in value.items():
        if (not isinstance(ident,str) or not mod_manifest.IDENTIFIER.fullmatch(ident) or not isinstance(chosen,dict) or
                any(not isinstance(k,str) or not mod_manifest.IDENTIFIER.fullmatch(k) or type(v) not in (bool,str,int,float)
                    for k,v in chosen.items())):
            raise ValueError('Invalid per-game mod settings')
    return {ident:dict(chosen) for ident,chosen in value.items()}


def build(root,game):
    """(title_id, app_version, executable_sha256) of the game's installed build, or None."""
    try:
        from . import game_library
    except ImportError:
        import game_library
    try:
        entry=game_library.resolve_entry(root,game=game)
        return entry['title_id'],entry['app_version'],entry['executable_sha256']
    except (OSError,ValueError,KeyError,TypeError):
        return None


def available(manifest,digest):
    """Whether every recipe file the mod needs for this build is present."""
    for operation in manifest['operations']:
        if operation.get('target',digest)==digest and 'profile' in operation:
            try:
                if not mod_manifest.locate(manifest,operation['profile']).is_file():return False
            except mod_manifest.ModError:
                return False
    return True


def catalogue(root,game):
    """Rows for the Mods page. status: ready, other-build, not-installed or unavailable."""
    try:
        mods=mod_manifest.discover(root)
    except mod_manifest.ModError as error:
        return [],str(error)
    current=build(root,game)
    rows=[]
    for ident,manifest in sorted(mods.items(),key=lambda item:(not item[1]['builtin'],item[1]['name'].lower())):
        if current is None:status='not-installed'
        elif not mod_manifest.supports(mods,ident,current[2]):status='other-build'
        elif not available(manifest,current[2]):status='unavailable'
        else:status='ready'
        rows.append(dict(id=ident,name=manifest['name'],description=manifest.get('description',''),
                         version=manifest['version'],author=manifest['author'],builtin=manifest['builtin'],
                         status=status,controlled=CONTROLLED.get(ident) if manifest['builtin'] else None,
                         settings=manifest.get('settings',{}),
                         targets=[f"{t['title_id']} {t['app_version']}" for t in manifest['targets']]))
    return rows,None


def selection(root,game):
    try:
        from . import gameplay_mods, game_library
    except ImportError:
        import gameplay_mods, game_library
    selected=dict.fromkeys(NAMES,False)
    if game['id']=='trap-team':
        try:
            title=game_library.resolve(root, game=game).title_id
            current=gameplay_mods.selection(root,title)
            selected.update({name:current[name] for name in NAMES})
        except (OSError,ValueError):pass
    selected.update(validate(game.get('mods',{})))
    return selected


def arguments(mods,settings=None):
    """run_session options for saved choices; the gameplay mods keep their own switches."""
    argv=[]
    for ident,enabled in validate(mods).items():
        if ident in NAMES:argv.append(('--' if enabled else '--no-')+ident)
        elif enabled:argv+=['--mod',ident]
    for ident,chosen in validate_settings(settings or {}).items():
        if not mods.get(ident,False):continue
        for name,value in sorted(chosen.items()):
            argv+=['--mod-setting',f'{ident}.{name}={json.dumps(value)}']
    return argv

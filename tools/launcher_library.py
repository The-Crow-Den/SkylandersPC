# SPDX-License-Identifier: GPL-3.0-or-later
"""Local library metadata. Package selections never imply extraction or playability."""
import json
try:
    from . import launcher_model
except ImportError:
    import launcher_model
from pathlib import Path

GAMES = [('swap-force', 'Swap Force', '#246bd8', '#ffaf83'),
         ('trap-team', 'Trap Team', '#087f9d', '#92dbc7'),
         ('superchargers', 'SuperChargers', '#572e9b', '#ef965d'),
         ('imaginators', 'Imaginators', '#263da2', '#e3a2ed')]


def defaults():
    return {'selected': 'swap-force', 'games': [dict(id=i, name=n, top=t, bottom=b,
            background='', logo='', game_pkg='', update_pkg='', settings={})
            for i, n, t, b in GAMES], 'figures': [], 'portal': None, 'portal_bottom': None}


def load(path):
    if not Path(path).exists():
        return defaults()
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not isinstance(value.get('games'), list) or not value['games']:
        raise ValueError('Invalid launcher library')
    ids = set()
    for game in value['games']:
        if not isinstance(game, dict) or not all(isinstance(game.get(k), str) for k in
                ('id', 'name', 'top', 'bottom', 'background', 'logo', 'game_pkg', 'update_pkg')):
            raise ValueError('Invalid library game')
        if game['id'] in ids or not isinstance(game.get('settings'), dict):
            raise ValueError('Invalid game settings or duplicate game')
        launcher_model.validate({**launcher_model.DEFAULTS, **game['settings']})
        if not game['id'] or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in game['id']):
            raise ValueError('Invalid library game identifier')
        try:
            from .launcher_mods import validate as validate_mods
        except ImportError:
            from launcher_mods import validate as validate_mods
        validate_mods(game.get('mods',{}))
        if 'installation' in game:
            try:
                from .game_library import split_selector
            except ImportError:
                from game_library import split_selector
            split_selector(game['installation'])
        ids.add(game['id'])
    if value.get('selected') not in ids:
        value['selected'] = value['games'][0]['id']
    if not isinstance(value.get('figures'), list) or any(not isinstance(p, str) for p in value['figures']):
        raise ValueError('Invalid figure collection')
    # The starting figure is any collection tag; a missing file is forgotten.
    portal = value.get('portal')
    if not isinstance(portal, str) or not portal or not Path(portal).is_file():
        value['portal'] = None
    # A swapper's bottom half starts under the starting top half.
    bottom = value.get('portal_bottom')
    if not value['portal'] or not isinstance(bottom, str) or not bottom or not Path(bottom).is_file():
        value['portal_bottom'] = None
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    stored={**value,'games':[{k:v for k,v in game.items() if k!='operation'} for game in value['games']]}
    temporary.write_text(json.dumps(stored, indent=2) + '\n')
    temporary.replace(path)


def sync_installations(root, value):
    """Add installed titles to the rail without replacing saves, figures or overrides."""
    try:
        from . import game_library
    except ImportError:
        import game_library
    issues = []
    installed = game_library.entries(root,issues)
    value['installation_issues'] = issues
    for entry in installed:
        profile = game_library.profile_for(root, entry)
        key = profile['id'] if profile else 'title-' + entry['title_id'].lower()
        game = next((g for g in value['games'] if g['id'] == key), None)
        if game is None:
            game = dict(id=key, name=profile['title'] if profile else entry['title'],
                        title_id=entry['title_id'], top='#263da2', bottom='#a9a9b1',
                        background='', logo='', game_pkg='', update_pkg='', settings={})
            value['games'].append(game)
    for issue in issues:
        title = issue.get('title_id','')
        import re
        if not re.fullmatch(r'CUSA\d{5}',title):continue
        profile = game_library.profile_for(root,{'title_id':title})
        key = profile['id'] if profile else 'title-'+title.lower()
        if not any(g['id']==key for g in value['games']):
            value['games'].append(dict(id=key,name=profile['title'] if profile else title,title_id=title,
                top='#263da2',bottom='#a9a9b1',background='',logo='',game_pkg='',update_pkg='',settings={}))
    for game in value['games']:
        related = [i['message'] for i in issues if i.get('title_id') and
            ((game_library.profile_for(root,{'title_id':i['title_id']}) or {}).get('id')==game['id'] or game.get('title_id')==i.get('title_id'))]
        game['installation_issue'] = '\n'.join(related)
        choices = [e for e in installed if
            (game_library.profile_for(root, e) or {}).get('id') == game['id'] or
            game.get('title_id') == e['title_id']]
        if not choices:
            game.pop('installation',None);game.pop('installed_paths',None)
            continue
        try:
            from .game_install import version
        except ImportError:
            from game_install import version
        chosen = max(choices, key=lambda e: version(e['app_version']))
        game['installation'] = game_library.selector(chosen['title_id'], chosen['app_version'])
        game['installed_paths'] = [p for p in (chosen['base_path'], chosen['update_path']) if p]
    return value


def open_games_folder(root):
    """Open the visible installation folder using the desktop's file manager."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    try:
        from . import game_library
    except ImportError:
        import game_library
    folder = game_library.directory(root)
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise ValueError('Games folder cannot be a symlink')
    folder.mkdir(parents=True, exist_ok=True)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))):
        raise OSError('The file manager could not open the Games folder.')

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
            for i, n, t, b in GAMES], 'figures': [], 'portal': None}


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
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def sync_installations(root, value):
    """Add installed titles to the rail without replacing saves, figures or overrides."""
    try:
        from . import game_library
    except ImportError:
        import game_library
    installed = game_library.entries(root)
    for entry in installed:
        profile = game_library.profile_for(root, entry)
        key = profile['id'] if profile else 'title-' + entry['title_id'].lower()
        game = next((g for g in value['games'] if g['id'] == key), None)
        if game is None:
            game = dict(id=key, name=profile['title'] if profile else entry['title'],
                        title_id=entry['title_id'], top='#263da2', bottom='#a9a9b1',
                        background='', logo='', game_pkg='', update_pkg='', settings={})
            value['games'].append(game)
    for game in value['games']:
        choices = [e for e in installed if
            (game_library.profile_for(root, e) or {}).get('id') == game['id'] or
            game.get('title_id') == e['title_id']]
        if not choices:
            continue
        if not any(game.get('installation') == game_library.selector(e['title_id'], e['app_version']) for e in choices):
            try:
                from .game_install import version
            except ImportError:
                from game_install import version
            chosen = max(choices, key=lambda e: version(e['app_version']))
            game['installation'] = game_library.selector(chosen['title_id'], chosen['app_version'])
        chosen = next(e for e in choices if game['installation'] == game_library.selector(e['title_id'], e['app_version']))
        game['installed_paths'] = [p for p in (chosen['base_path'], chosen['update_path']) if p]
    return value

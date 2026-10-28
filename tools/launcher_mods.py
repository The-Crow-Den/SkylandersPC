# SPDX-License-Identifier: GPL-3.0-or-later
"""Launcher controls for existing guarded Trap Team gameplay recipes."""
try:
    from .gameplay_mods import NAMES
except ImportError:
    from gameplay_mods import NAMES


def validate(value):
    if not isinstance(value,dict) or set(value)-set(NAMES) or any(type(v) is not bool for v in value.values()):
        raise ValueError('Invalid per-game gameplay mods')
    return dict(value)


def selection(root,game):
    try:
        from . import gameplay_mods, game_install
    except ImportError:
        import gameplay_mods, game_install
    selected=dict.fromkeys(NAMES,False)
    if game['id']=='trap-team':
        try:
            title=game_install.discover(root/'Game').title_id
            current=gameplay_mods.selection(root,title)
            selected.update({name:current[name] for name in NAMES})
        except (OSError,ValueError):pass
    selected.update(validate(game.get('mods',{})))
    return selected

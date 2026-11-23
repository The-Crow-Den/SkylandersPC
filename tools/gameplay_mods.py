# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved per-title choice of the experimental gameplay mods.

Each name is a built-in mod in profiles/mods; tools/mod_manifest.py loads its recipe."""
import json
from pathlib import Path
import re

NAMES = ('unlock-expansions',)
# Folded into unlock-expansions; older saved choices still read.
LEGACY = {'replay-expansion-intros': 'unlock-expansions',
          'element-gates': 'trap-master', 'traptanium': 'trap-master'}


def fold(choices):
    """Merge retired mod names into the mod that now carries them."""
    result = {name: value for name, value in choices.items() if name not in LEGACY}
    for old, new in LEGACY.items():
        if choices.get(old):result[new] = True
    return result


def fold_settings(mods, settings):
    """Settings the merged mods take from the separate mods they replaced."""
    settings = dict(settings)
    if ('element-gates' in mods or 'traptanium' in mods) and 'trap-master' not in settings:
        settings['trap-master'] = {'elemental-gates': mods.get('element-gates') is True,
                                   'traptanium': mods.get('traptanium') is True}
    if 'replay-expansion-intros' in mods and 'unlock-expansions' not in settings:
        settings['unlock-expansions'] = {'unlock-adventure-packs': mods.get('unlock-expansions') is True,
                                         'replay-introductions': mods.get('replay-expansion-intros') is True}
    return settings


def selection(root, title_id, overrides=None):
    if not isinstance(title_id,str) or not re.fullmatch(r'CUSA\d{5}',title_id):
        raise ValueError('invalid gameplay mod title')
    selected = dict.fromkeys(NAMES,False)  # may also gain folded ids such as trap-master
    path = Path(root).resolve()/'out/mod-profiles'/f'{title_id}.json'
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.resolve()!=path or path.stat().st_size>16384:
            raise ValueError('redirected or oversized gameplay mod selection')
        record=json.loads(path.read_text())
        if (not isinstance(record,dict) or set(record)!={'schema_version','title_id','enabled'} or
                type(record['schema_version']) is not int or record['schema_version']!=1 or
                record['title_id']!=title_id or not isinstance(record['enabled'],dict) or
                not set(record['enabled']).issubset(set(NAMES)|set(LEGACY)) or
                any(type(value) is not bool for value in record['enabled'].values())):
            raise ValueError('invalid gameplay mod selection')
        selected.update(fold(record['enabled']))
    for name,value in fold(overrides or {}).items():
        if name not in NAMES+tuple(LEGACY.values()) or (value is not None and type(value) is not bool):
            raise ValueError('invalid gameplay mod override')
        if value is not None:selected[name]=value
    return selected


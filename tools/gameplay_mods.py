# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved per-title choice of the experimental gameplay mods.

Each name is a built-in mod in profiles/mods; tools/mod_manifest.py loads its recipe."""
import json
from pathlib import Path
import re

NAMES = ('element-gates', 'traptanium', 'unlock-expansions', 'replay-expansion-intros')


def selection(root, title_id, overrides=None):
    if not isinstance(title_id,str) or not re.fullmatch(r'CUSA\d{5}',title_id):
        raise ValueError('invalid gameplay mod title')
    selected = dict.fromkeys(NAMES,False)
    path = Path(root).resolve()/'out/mod-profiles'/f'{title_id}.json'
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.resolve()!=path or path.stat().st_size>16384:
            raise ValueError('redirected or oversized gameplay mod selection')
        record=json.loads(path.read_text())
        if (not isinstance(record,dict) or set(record)!={'schema_version','title_id','enabled'} or
                type(record['schema_version']) is not int or record['schema_version']!=1 or
                record['title_id']!=title_id or not isinstance(record['enabled'],dict) or
                not {'element-gates','traptanium'}.issubset(record['enabled']) or
                not set(record['enabled']).issubset(NAMES) or
                any(type(value) is not bool for value in record['enabled'].values())):
            raise ValueError('invalid gameplay mod selection')
        selected.update(record['enabled'])
    for name,value in (overrides or {}).items():
        if name not in NAMES or (value is not None and type(value) is not bool):
            raise ValueError('invalid gameplay mod override')
        if value is not None:selected[name]=value
    return selected


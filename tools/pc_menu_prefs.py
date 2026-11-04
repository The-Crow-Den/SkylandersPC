# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-user PC menu preferences: favourite and recently placed figures.

Stored beside the save folder (outside the repository); figures are keyed by
collection and display name, never by figure contents.
"""
import json
import os
from pathlib import Path
import re
try:
    from . import save_profile
except ImportError:
    import save_profile

KINDS=('0','2','9')  # Skylanders, items, vehicles; traps have their own page
RECENT=8
FAVOURITES=64


def path(environment=None):
    return save_profile.home_root(environment).parent/'pc-menu-preferences.json'


def _clean(value):
    result={}
    for title,entry in (value.items() if isinstance(value,dict) else ()):
        if not isinstance(title,str) or not re.fullmatch(r'[a-z0-9-]{1,32}',title) or not isinstance(entry,dict):continue
        clean={}
        for field,limit in (('favourites',FAVOURITES),('recent',RECENT)):
            groups=entry.get(field) if isinstance(entry.get(field),dict) else {}
            clean[field]={kind:[name for name in groups.get(kind,[]) if isinstance(name,str) and 0<len(name)<=96][:limit]
                          for kind in KINDS if isinstance(groups.get(kind),list)}
        result[title]=clean
    return result


def load(file=None):
    file=Path(file) if file else path()
    try:
        if file.is_symlink() or file.stat().st_size>256*1024:return {}
        return _clean(json.loads(file.read_text()))
    except (OSError,ValueError):
        return {}


def _write(file,value):
    file.parent.mkdir(parents=True,exist_ok=True)
    if file.is_symlink():raise ValueError('redirected preferences file')
    temporary=file.with_name(file.name+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    os.replace(temporary,file)


def _check(title,kind,name):
    if not re.fullmatch(r'[a-z0-9-]{1,32}',title or '') or str(kind) not in KINDS or not isinstance(name,str) or not 0<len(name)<=96:
        raise ValueError('invalid figure preference')


def record_recent(title,kind,name,file=None):
    _check(title,kind,name);file=Path(file) if file else path();value=load(file)
    entry=value.setdefault(title,{'favourites':{},'recent':{}});recent=entry['recent'].setdefault(str(kind),[])
    if recent[:1]==[name]:return value
    recent[:]=([name]+[other for other in recent if other!=name])[:RECENT]
    _write(file,value);return value


def toggle_favourite(title,kind,name,file=None):
    _check(title,kind,name);file=Path(file) if file else path();value=load(file)
    entry=value.setdefault(title,{'favourites':{},'recent':{}});favourites=entry['favourites'].setdefault(str(kind),[])
    if name in favourites:favourites.remove(name)
    elif len(favourites)<FAVOURITES:favourites.append(name)
    _write(file,value);return value

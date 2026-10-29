# SPDX-License-Identifier: GPL-3.0-or-later
"""Games-folder metadata shares universal preferences without becoming a game override."""
import json
from pathlib import Path
import uuid

KEYS = ('games_folder','previous_games_folders')


def raw(path):
    path = Path(path)
    if not path.exists():return {}
    if any(p.is_symlink() for p in (path,*path.parents)) or path.stat().st_size>1024*1024:raise ValueError('Invalid launcher preferences file')
    value = json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('Invalid launcher preferences')
    return value


def resolve(project, value):
    if not isinstance(value,str) or '\0' in value or '\\' in value or '..' in Path(value).parts:
        raise ValueError('Invalid games folder preference')
    if not value:return Path(project).absolute()/'Games'
    path = Path(value)
    return path if path.is_absolute() else Path(project).absolute()/path


def locations(project):
    project = Path(project).absolute()
    try:
        value = raw(project/'.local/launcher-settings.json')
        current = resolve(project,value.get('games_folder',''))
        previous = value.get('previous_games_folders',[])
        if not isinstance(previous,list):raise ValueError('Invalid library history')
        previous = [resolve(project,p) for p in previous]
    except (OSError,ValueError):current,previous = project/'Games',[]
    return current,list(dict.fromkeys([current,*previous,project/'Games']))


def save_location(project, current, previous):
    project = Path(project).absolute();path = project/'.local/launcher-settings.json'
    try:
        from .launcher_model import DEFAULTS
    except ImportError:
        from launcher_model import DEFAULTS
    value = {**DEFAULTS,**raw(path)}
    def stored(folder):
        folder = Path(folder).absolute()
        try:return folder.relative_to(project).as_posix()
        except ValueError:return str(folder)
    value['games_folder'] = stored(current)
    value['previous_games_folders'] = [stored(p) for p in dict.fromkeys(previous) if Path(p)!=Path(current)]
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name('.launcher-settings-'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)

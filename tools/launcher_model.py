# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI-independent launch configuration; the session runner remains authoritative."""
import json
from pathlib import Path

try:
    from .pc_settings import validate_settings
    from .run_session import PACKS
    from . import game_install, game_build, game_library, game_prepare
except ImportError:
    from pc_settings import validate_settings
    from run_session import PACKS
    import game_install, game_build, game_library, game_prepare

DEFAULTS = dict(resolution='1080p', quality='balanced', fullscreen=False,
                fps_counter=True, frame_limit=30, portal_volume=30,
                motion_blur=True, nvidia=True, mangohud=False,
                unlock_nightmare=True, level_events=False, frame_policy='auto', figure='')
FLAGS = ('motion_blur', 'nvidia', 'mangohud', 'unlock_nightmare', 'level_events')
PC_KEYS = ('resolution', 'quality', 'fullscreen', 'fps_counter', 'frame_limit', 'portal_volume', 'frame_policy')


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Unknown or missing launcher settings')
    validate_settings({key: value[key] for key in PC_KEYS})
    if any(type(value[key]) is not bool for key in FLAGS):
        raise ValueError('Invalid launcher switch')
    if value['frame_policy'] not in ('auto','manual'):
        raise ValueError('Invalid frame policy')
    if not isinstance(value['figure'], str) or '\0' in value['figure']:
        raise ValueError('Invalid figure path')
    return dict(value)


def load(path):
    path = Path(path)
    if not path.exists(): return dict(DEFAULTS)
    value=json.loads(path.read_text())
    if isinstance(value,dict):
        value = {k:v for k,v in value.items() if k not in ('games_folder','previous_games_folders')}
    if isinstance(value,dict) and set(value)==set(DEFAULTS)-{'frame_policy'}:
        value['frame_policy']='auto'
    return validate(value)


def save(path, value):
    value = validate(value)
    path = Path(path)
    try:
        from .library_preferences import raw, KEYS
    except ImportError:
        from library_preferences import raw, KEYS
    existing = raw(path)
    value = {**value,**{key:existing[key] for key in KEYS if key in existing}}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def command(root, python, value, mods=None, game=None):
    value = validate(value)
    # The exact-build mod gates 60 on engine loading, cutscene and UI state.
    argv = [str(python), str(Path(root) / 'tools/run_session.py'),
            '--variant', '60-delta', '--performance-profile', 'standard',
            '--memory-mode', 'standard', '--renderer-idle', 'adaptive',
            '--frame-policy', value['frame_policy']]
    if game is not None:
        entry = game_library.resolve_entry(root, game=game)
        argv += ['--game', game_library.selector(entry['title_id'], entry['app_version'])]
    for key in ('resolution', 'quality', 'frame_limit', 'portal_volume', 'frame_policy'):
        argv += ['--' + key.replace('_', '-'), str(value[key])]
    for key in ('fullscreen', 'fps_counter', 'motion_blur', 'nvidia', 'mangohud', 'unlock_nightmare'):
        argv.append('--' + ('' if value[key] else 'no-') + key.replace('_', '-'))
    if mods is not None:
        try:
            from .launcher_mods import validate as validate_mods
        except ImportError:
            from launcher_mods import validate as validate_mods
        for name, enabled in validate_mods(mods).items():
            argv.append(('--' if enabled else '--no-')+name)
    if value['level_events']:
        argv.append('--level-events')
    if value['figure']:
        argv += ['--figure', value['figure']]
    return argv


def missing_files(root, game=None):
    root = Path(root)
    try:
        entry = game_library.resolve_entry(root, game=game)
        if not game_library.supported(root, entry):
            raise ValueError('This title/version is not supported yet')
        game_prepare.require_ready(root,entry,deep=False)
        installation = game_install.discover(entry)
        pack = game_build.configuration(root,installation,'60-delta')['pack']
        executable = installation.source('eboot.bin')
    except (OSError,ValueError) as error:
        return [str(error), '.local/native-gpu-build/skylanders-native-host',
                'prepared game image.pack', 'prepared imports.types', 'prepared boot.plan']
    paths = [root / '.local/native-gpu-build/skylanders-native-host',
             executable,
             *(pack / name for name in ('image.pack', 'imports.types', 'boot.plan'))]
    return [str(path.relative_to(root)) for path in paths if not path.is_file()]


def controllers(sysfs=Path('/sys/class/input')):
    """Enumerated joystick names, not a claim that guest mappings were tested."""
    result = []
    for path in sorted(Path(sysfs).glob('js*/device/name')):
        try:
            name = path.read_text().strip()
        except OSError:
            continue
        if name:
            result.append(name)
    return result

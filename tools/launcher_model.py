# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI-independent launch configuration; the session runner remains authoritative."""
import json
from pathlib import Path

try:
    from .pc_settings import validate_settings
    from .run_session import PACKS
    from . import game_install, game_build, game_library, game_prepare, game_language, portal_devices
except ImportError:
    from pc_settings import validate_settings
    from run_session import PACKS
    import game_install, game_build, game_library, game_prepare, game_language, portal_devices

DEFAULTS = dict(resolution='1080p', quality='balanced', fullscreen=False,
                fps_counter=True, frame_limit=30, portal_volume=30,
                motion_blur=True, anti_aliasing=True, nvidia=True, mangohud=False,
                unlock_nightmare=True, level_events=False, trophy_popups=True, frame_policy='auto', figure='', figure_bottom='', language='en-US',
                portal_device='virtual')
FLAGS = ('motion_blur', 'anti_aliasing', 'nvidia', 'mangohud', 'unlock_nightmare', 'level_events')
PC_KEYS = ('resolution', 'quality', 'fullscreen', 'fps_counter', 'frame_limit', 'portal_volume', 'frame_policy')


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Unknown or missing launcher settings')
    validate_settings({key: value[key] for key in PC_KEYS})
    if any(type(value[key]) is not bool for key in FLAGS):
        raise ValueError('Invalid launcher switch')
    if value['language'] not in game_language.CODES:
        raise ValueError('Invalid game language')
    if value['frame_policy'] not in ('auto','manual'):
        raise ValueError('Invalid frame policy')
    if any(not isinstance(value[key], str) or '\0' in value[key] for key in ('figure', 'figure_bottom')):
        raise ValueError('Invalid figure path')
    if not portal_devices.valid_choice(value['portal_device']):
        raise ValueError('Invalid portal device')
    return dict(value)


def languages(root):
    """Every language some title profile offers, English (US) first."""
    found=[game_language.DEFAULT]
    for path in sorted(Path(root,'profiles').glob('*.json')):
        try:found+=[code for code in game_language.offered(root,path.stem) if code not in found]
        except ValueError:pass
    return found


def load(path):
    path = Path(path)
    if not path.exists(): return dict(DEFAULTS)
    value=json.loads(path.read_text())
    if isinstance(value,dict):
        value = {k:v for k,v in value.items() if k not in ('games_folder','previous_games_folders')}
    if isinstance(value,dict) and 'figure_bottom' not in value:
        value['figure_bottom']=''
    if isinstance(value,dict) and 'portal_device' not in value:
        value['portal_device']='virtual'
    if isinstance(value,dict) and 'language' not in value:
        value['language']='en-US'
    if isinstance(value,dict) and 'anti_aliasing' not in value:
        value['anti_aliasing']=True
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


def command(root, python, value, mods=None, game=None, mod_settings=None):
    value = validate(value)
    # The exact-build mod gates 60 on engine loading, cutscene and UI state.
    argv = [str(python), str(Path(root) / 'tools/run_session.py'),
            '--variant', '60-delta', '--performance-profile', 'standard',
            '--memory-mode', 'standard', '--renderer-idle', 'adaptive',
            '--frame-policy', value['frame_policy']]
    if game is not None:
        entry = game_library.resolve_entry(root, game=game)
        argv += ['--game', game_library.selector(entry['title_id'], entry['app_version'])]
    for key in ('resolution', 'quality', 'frame_limit', 'portal_volume', 'frame_policy', 'language'):
        argv += ['--' + key.replace('_', '-'), str(value[key])]
    for key in ('fullscreen', 'fps_counter', 'trophy_popups', 'motion_blur', 'anti_aliasing', 'nvidia', 'mangohud', 'unlock_nightmare'):
        argv.append('--' + ('' if value[key] else 'no-') + key.replace('_', '-'))
    if mods is not None:
        try:
            from .launcher_mods import arguments as mod_arguments
        except ImportError:
            from launcher_mods import arguments as mod_arguments
        argv += mod_arguments(mods, mod_settings)
    if value['level_events']:
        argv.append('--level-events')
    if value['portal_device'] != portal_devices.VIRTUAL:
        argv += ['--portal-device', value['portal_device']]
    elif value['figure']:
        argv += ['--figure', value['figure']]
        if value['figure_bottom']:
            argv += ['--figure-bottom', value['figure_bottom']]
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

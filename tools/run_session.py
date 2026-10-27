#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a prepared local build with persistent logs and explicit exit reporting."""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import lzma
import os
import re
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid
import sys
import shutil
try:
    from .overlay_session import html_overlay
    from .resolution import PRESETS, SHADOWS, prepare_resolution, prepare_assets
    from .pc_settings import QUALITY, load_settings, save_settings
    from . import level_events_mod, trophy_store
    from . import nightmare_mod
    from . import game_install, game_build, save_profile, gameplay_mods, asset_mod, movie_audio, save_backup, controller_glyphs, controller_art
except ImportError:
    from overlay_session import html_overlay
    from resolution import PRESETS, SHADOWS, prepare_resolution, prepare_assets
    from pc_settings import QUALITY, load_settings, save_settings
    import level_events_mod, trophy_store
    import nightmare_mod
    import game_install, game_build, save_profile, gameplay_mods, asset_mod, movie_audio, save_backup, controller_glyphs, controller_art

ROOT = Path(__file__).resolve().parents[1]
PACKS = {'original': 'native-linked-boot-weak',
         '60': 'native-linked-one-vblank-experimental',
         '60-delta': 'native-linked-60-delta-experimental'}


@contextmanager
def exclusive_session(path):
    """Do not let two launched games write the same save/portal library."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another Trap Team session is running. Close it before starting a new one.') from None
        # The file stays in place: deleting it could create two independent locks.
        yield


def overlay_environment(environment, enabled=True, phase_switch=False):
    result = dict(environment)
    result['MANGOHUD'] = '1' if enabled else '0'
    if enabled:
        result.pop('DISABLE_MANGOHUD', None)
        result.setdefault('MANGOHUD_CONFIG',
                          'fps,frametime,frame_timing,cpu_stats,gpu_stats,gpu_name,resolution,show_fps_limit')
        if phase_switch:
            # First cap is active at startup. Explicit testing mode overrides a
            # user's cap list, retaining their other display preferences.
            text = re.sub(r'(^|,)fps_limit=\d+(?:[,+]\d+)*(?=,|$)', '', result['MANGOHUD_CONFIG'])
            config = [item for item in text.split(',') if item and not item.startswith('toggle_fps_limit=')]
            # Waiting after present produced alternating ~20/47 ms frames at
            # a 30 FPS cap in the matched Trap Team trial. Keep an explicit
            # user method for comparisons; otherwise wait before present.
            if not any(item.startswith('fps_limit_method=') for item in config):
                config.append('fps_limit_method=early')
            result['MANGOHUD_CONFIG'] = ','.join(config + ['fps_limit=30+60', 'toggle_fps_limit=Shift_L+F1'])
    return result


def overlay_pci_configuration(directory, pci_device):
    # Colons are option separators in MANGOHUD_CONFIG. Use a session-local
    # config file for a PCI address instead of embedding it in that string.
    if not re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]', pci_device):
        raise ValueError('GPU PCI address must have the form 0000:c5:00.0')
    path = directory / 'MangoHud.conf'
    with path.open('x') as output:
        output.write('pci_dev=' + pci_device.lower() + '\n')
    return path


def renderer_environment(environment, idle='adaptive'):
    """Keep guest filtering unless requested; sleeping preserves work/notifications."""
    result = dict(environment)
    result.setdefault('BB_ANISO','0')
    # The native host already paces guest submissions. Avoid re-quantizing
    # completed frames to an independent software vblank phase. Hardware FIFO
    # retains tear-free output; nonzero guest flip intervals remain honored.
    result.setdefault('BB_PRESENT_AS_READY','1')
    result.setdefault('BB_PRESENT_MODE','Fifo')
    if idle == 'sleep':
        result['BB_GPU_SPIN_US'] = '0'
        result['BB_PIPE_SPIN_US'] = '0'
    elif idle != 'adaptive':
        raise ValueError('unknown renderer idle policy')
    return result


WINDOW_READY = b'Window backend:'


def announce_window(log_path, process, marker=WINDOW_READY, interval=0.1):
    """Tell the launcher the game is visible once the runtime opens its window."""
    seen = b''
    with open(log_path, 'rb') as log:
        while True:
            chunk = log.read()
            if chunk:
                seen = (seen + chunk)[-4096:]
                if marker in seen:
                    print('SKYLANDERS_RUNTIME_STARTED', flush=True)
                    return True
            elif process.poll() is not None:
                return False
            else:
                time.sleep(interval)


def run_logged(command, directory, *, cwd, env=None, seconds=0):
    started = time.monotonic()
    reason = 'process-exit'
    with (directory / 'runtime.log').open('xb') as output, html_overlay(directory,cwd,env) as runtime_environment:
        process = subprocess.Popen(command, cwd=cwd, env=runtime_environment, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            print('SKYLANDERS_RUNTIME_LAUNCHED', flush=True)
            threading.Thread(target=announce_window, args=(directory / 'runtime.log', process), daemon=True).start()
            code = process.wait(timeout=seconds if seconds else None)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            reason = 'requested-time-limit' if isinstance(error, subprocess.TimeoutExpired) else 'user-interrupt'
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass  # The child may finish between wait timing out and signaling.
            try:
                code = process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
        result = {'returncode': code, 'stop_reason': reason,
                  'elapsed_seconds': round(time.monotonic() - started, 3),
                  'signal': -code if code < 0 else None}
        (directory / 'exit.json').write_text(json.dumps(result, indent=2) + '\n')
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=PACKS, default='original')
    parser.add_argument('--figure', type=Path)
    parser.add_argument('--trophy-config',type=Path,help='private shadPS4 config or trophy-key file; never copied into logs')
    parser.add_argument('--pc-menu',choices=('web','native'),default='web',help='HTML desktop overlay or native fallback menu')
    parser.add_argument('--save-root', type=Path, help='explicit save directory; overrides the selected play profile')
    parser.add_argument('--save-backups',action=argparse.BooleanOptionalAction,default=True,
                        help='verified rotating save snapshots before launch and after normal exit')
    parser.add_argument('--resolution', choices=PRESETS,
                        help='experimental internal render size; restart required')
    parser.add_argument('--movie-audio',choices=('auto','original','english'),default='auto',
                        help='select English movie narration for the verified US update; original retains all tracks')
    parser.add_argument('--window-resolution', choices=PRESETS,
                        help='presentation window size, independent of internal rendering')
    parser.add_argument('--shadows', choices=SHADOWS, default=None,
                        help='experimental independent shadow atlas quality (default native)')
    parser.add_argument('--timing', action='store_true')
    parser.add_argument('--profile', action='store_true',
                        help='write per-frame renderer (frames.csv) and guest (frame-profile.csv) profiles; '
                             'summarize with tools/frame_profile.py')
    parser.add_argument('--cold-cache', action='store_true',
                        help='start from empty renderer and driver shader caches inside the session')
    parser.add_argument('--level-events', action='store_true',
                        help='enable the exact-build engine lifecycle mod')
    parser.add_argument('--frame-policy', choices=('manual','auto'), default='manual',
                        help='auto follows mod loading, UI visibility and cutscene state (30/60)')
    parser.add_argument('--unlock-nightmare', action=argparse.BooleanOptionalAction, default=True,
                        help='make Nightmare available in fresh-save difficulty selection')
    for name in gameplay_mods.NAMES:
        parser.add_argument('--'+name,action=argparse.BooleanOptionalAction,default=None,
                            help='exact-build gameplay mod; defaults to the selected title mod profile')
    overlay = parser.add_mutually_exclusive_group()
    overlay.add_argument('--mangohud', action='store_true', help='opt into the separately installed MangoHud overlay')
    overlay.add_argument('--no-mangohud', dest='mangohud', action='store_false')
    parser.set_defaults(mangohud=os.environ.get('MANGOHUD') == '1')
    parser.add_argument('--performance-profile', choices=('standard','low-end'), default='standard',
                        help='low-end targets 1080p/60 gameplay with lighter shadows and no motion blur')
    parser.add_argument('--motion-blur', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--memory-mode', choices=('standard','compact'), default='standard')
    parser.add_argument('--renderer-idle', choices=('adaptive','sleep'), default='adaptive',
                        help='sleep avoids speculative renderer idle spinning; experimental')
    parser.add_argument('--quality', choices=QUALITY, default='balanced', help='shadow-detail quality preset')
    parser.add_argument('--controller-glyphs',choices=controller_glyphs.MODES,default='auto',
                        help='shared in-game button font; auto detects the first mapped controller at launch; restart to change')
    parser.add_argument('--controller-layout',choices=('auto','keyboard-and-pad'),default='auto',
                        help='keyboard-and-pad reserves player one for the keyboard and assigns a single pad to player two')
    parser.add_argument('--frame-limit', choices=(0,30,60), type=int, default=30,
                        help='built-in FPS cap; zero is an uncapped diagnostic')
    parser.add_argument('--portal-volume', type=int, default=30, help='portal speaker volume, 0 to 100 (default 30)')
    parser.add_argument('--fullscreen', action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--fps-counter', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--nvidia', action=argparse.BooleanOptionalAction,
                        default=Path('/usr/share/vulkan/icd.d/nvidia_icd.json').is_file(),
                        help='restrict Vulkan to the installed NVIDIA driver')
    parser.add_argument('--hud-pci-device', help='PCI GPU address for MangoHud statistics')
    parser.add_argument('--manual-phase-cap', action='store_true',
                        help='MangoHud starts at 30; Shift+F1 toggles 30/60 manually')
    parser.add_argument('--present-limit', choices=('0', '60'),
                        help='diagnostic renderer pacing comparison; does not alter vblank frequency')
    parser.add_argument('--seconds', type=float, default=0,
                        help='explicit test duration; default has no time limit')
    preferences = ROOT / 'out/pc-settings.json'
    try:
        saved = load_settings(preferences)
    except (OSError,ValueError,TypeError) as error:
        print(f'Ignoring invalid saved PC settings: {error}',file=sys.stderr)
        saved = {}
    parser.set_defaults(**saved)
    arguments = list(sys.argv[1:] if argv is None else argv)
    preliminary,_ = parser.parse_known_args(arguments)
    if preliminary.performance_profile == 'low-end':
        parser.set_defaults(resolution='1080p',quality='performance',motion_blur=False,memory_mode='compact')
    args = parser.parse_args(arguments)
    if not 0 <= args.portal_volume <= 100: parser.error('portal volume must be between 0 and 100')
    if args.seconds < 0 or not args.seconds < float('inf'):
        parser.error('seconds must be finite and nonnegative')
    if args.hud_pci_device and not args.mangohud:
        parser.error('HUD PCI selection requires MangoHud')
    if args.manual_phase_cap and not args.mangohud:
        parser.error('manual phase cap requires MangoHud')
    if args.mangohud and shutil.which('mangohud') is None:
        parser.error('MangoHud was requested but is not installed; omit --mangohud to run normally')
    if args.frame_policy == 'auto':
        if args.variant != '60-delta' or args.manual_phase_cap or args.present_limit is not None:
            parser.error('automatic FPS requires 60-delta and the built-in limiter')
        args.level_events = True
    if args.variant == 'original' and args.frame_limit == 60:
        args.frame_limit = 30
    shadows = args.shadows if args.shadows is not None else QUALITY[args.quality]
    try:
        installation = game_install.discover(ROOT/'Game')
        build = game_build.configuration(ROOT, installation, args.variant)
        selected_save, save_source = save_profile.select(ROOT, installation.title_id, args.save_root)
        selected_mods=gameplay_mods.selection(ROOT,installation.title_id,{name:getattr(args,name.replace('-','_')) for name in gameplay_mods.NAMES})
        recipes=gameplay_mods.recipes(ROOT,installation.title_id,installation.app_version,selected_mods)
        movie_profile=ROOT/'profiles/patches/trap-team-us-01.01-movie-audio.json' if (installation.title_id,installation.app_version,build['executable_sha256'])==('CUSA00626','01.01',game_build.US_UPDATE_SHA256) else None
        if args.movie_audio=='english' and movie_profile is None:
            raise ValueError('English movie localization requires the verified US update')
        selected_movie_audio='english' if args.movie_audio!='original' and movie_profile else 'original'
        glyph_mode,glyph_detection=controller_glyphs.detect() if args.controller_glyphs=='auto' else (args.controller_glyphs,'manual')
        glyph_profile=ROOT/'profiles/patches/trap-team-us-01.01-controller-glyphs.json'
        if glyph_mode!='playstation' and not controller_art.available():
            if args.controller_glyphs!='auto':raise ValueError('Import local Steam controller artwork with tools/import_controller_glyphs.py first')
            glyph_mode,glyph_detection='playstation','no imported artwork: original prompts retained'

        if glyph_mode!='playstation' and movie_profile is None:
            if args.controller_glyphs!='auto':raise ValueError('Controller glyph packs require the verified US update')
            glyph_mode,glyph_detection='playstation','unsupported build: original prompts retained'

    except (OSError,ValueError) as error:
        parser.error(str(error))
    pack = build['pack']
    host = ROOT / '.local/native-gpu-build/skylanders-native-host'
    files = [pack / name for name in ('image.pack', 'imports.types', 'boot.plan')]
    if not host.is_file() or not all(path.is_file() for path in files):
        parser.error('prepared local build is missing')
    if args.figure and not args.figure.is_file():
        parser.error('figure file is missing')
    session = ROOT / 'out/sessions' / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    session.mkdir(parents=True)
    preparation_started=time.monotonic()
    preparation_phases={}
    phase_started=preparation_started
    def preparation_checkpoint(name):
        nonlocal phase_started
        now=time.monotonic()
        preparation_phases[name]=round(now-phase_started,3)
        phase_started=now
    resolution_metadata = None
    asset_metadata = None
    level_metadata = None
    nightmare_metadata = None
    game_root = installation.materialize(session/'install') if installation.update else installation.base
    preparation_checkpoint("install_overlay")
    original_game = game_root
    if args.resolution:
        try:
            files[0], resolution_metadata = prepare_resolution(pack, session,
                build['executable'], args.resolution, args.variant, build['resolution'])
        except (OSError, ValueError) as error:
            parser.error(str(error))
    preparation_checkpoint('resolution_pack')
    if args.resolution or shadows != 'native' or not args.motion_blur or args.unlock_nightmare or recipes or selected_movie_audio=='english' or glyph_mode!='playstation':
        try:
            game_root, asset_metadata = prepare_assets(game_root, session,
                PRESETS[args.resolution] if args.resolution else None, shadows, args.motion_blur, build['resolution'])
        except (OSError, ValueError) as error:
            parser.error(str(error))
    preparation_checkpoint('renderer_assets')
    if args.unlock_nightmare:
        try:
            nightmare_metadata=nightmare_mod.prepare(original_game,game_root,session,build['nightmare'])
        except (OSError,ValueError,lzma.LZMAError) as error:
            parser.error(str(error))
    preparation_checkpoint('nightmare')
    movie_metadata=None
    if selected_movie_audio=='english':
        try:
            movie_metadata=movie_audio.prepare(original_game,game_root,session,movie_profile)
        except (OSError,ValueError) as error:
            parser.error(str(error))
    preparation_checkpoint('movie_localization')
    glyph_metadata={'mode':glyph_mode,'requested':args.controller_glyphs,'detection':glyph_detection}
    if glyph_mode!='playstation':
        try:
            recipes.append(controller_glyphs.build_profile(original_game,glyph_profile,glyph_mode,build['executable_sha256']))
            glyph_metadata.update(coverage='shared font and animated mash prompts',assets=[item['asset'] for item in recipes[-1]['assets']])
        except (OSError,ValueError,lzma.LZMAError) as error:
            parser.error(str(error))
    preparation_checkpoint('glyph_recipe')
    gameplay_metadata=None
    if recipes:
        try:
            gameplay_metadata=asset_mod.prepare(original_game,game_root,session,asset_mod.combine_profiles(recipes),enabled=True,cache_directory=ROOT/'out/asset-mod-cache')
        except (OSError,ValueError,lzma.LZMAError) as error:
            parser.error(str(error))
    preparation_checkpoint('gameplay_and_glyph_assets')
    try:
        trophy_metadata=trophy_store.prepare(ROOT,installation,session,key_config=args.trophy_config)
    except (OSError,ValueError,ImportError) as error:
        trophy_metadata={'available':False,'reason':str(error)}
        print('Trophy setup unavailable: '+str(error),file=sys.stderr)
    preparation_checkpoint('trophies')
    env = overlay_environment(os.environ, args.mangohud, args.manual_phase_cap)
    icon=ROOT/'.local/app-icon/crystal.rgba'
    if icon.is_file():env['SKY_WINDOW_ICON_RGBA']=str(icon)
    env.setdefault('SDL_APP_ID','org.skylanders.TrapTeam')
    for key in ('SKY_TROPHY_STORE','SKY_TROPHY_CATALOGUES','SKY_TROPHY_ICONS'):env.pop(key,None)
    if trophy_metadata.get('available'):
        env.update(SKY_TROPHY_STORE=trophy_metadata['store'],SKY_TROPHY_CATALOGUES=trophy_metadata['catalogues'],SKY_TROPHY_ICONS=trophy_metadata['icons'])
    env.pop('SKY_CONTROLLER_GLYPH_ATLAS',None)
    if controller_art.available():
        env['SKY_CONTROLLER_GLYPH_ATLAS']=str(controller_art.atlas_path())
    glyph_metadata['artwork_provider']='Steam client' if controller_art.available() else 'original game'

    if selected_save is not None:
        env['SKY_SAVE_DATA_ROOT'] = str(selected_save)
    env = renderer_environment(env, args.renderer_idle)
    if args.level_events:
        try:
            files[0],level_metadata = level_events_mod.prepare(pack,session,
                build['executable'],args.variant,args.resolution,build['level-events'],build['resolution'])
        except (OSError,ValueError) as error:
            parser.error(str(error))
        env['SKY_LEVEL_EVENT_MAILBOX'] = str(level_metadata['mailbox_address'])
    else:
        for key in ('SKY_LEVEL_EVENT_MAILBOX','SKY_FRAME_POLICY','SKY_MANUAL_FRAME_LIMIT','SKY_AUTO_FRAME_POLICY_AVAILABLE'):
            env.pop(key,None)
    env['SKY_PC_WEB_MENU']='1' if args.pc_menu=='web' else '0'
    env.update({'SKY_PC_SETTINGS_REQUEST': str(session / 'pc-settings-request.json'),
                'SKY_PC_RESOLUTION': str(list(PRESETS).index(args.resolution or '1080p')),
                'SKY_PC_QUALITY': str(list(QUALITY.values()).index(shadows)),
                'SKY_PORTAL_VOLUME': str(args.portal_volume),
                'SKY_CONTROLLER_LAYOUT':args.controller_layout,
                'SKY_CONTROLLER_GLYPHS':args.controller_glyphs,
                'SKY_ACTIVE_CONTROLLER_GLYPHS':glyph_mode,
                'SKY_FRAME_LIMIT': str(0 if args.manual_phase_cap else 30 if args.frame_policy=='auto' else args.frame_limit),
                'SKY_MANUAL_FRAME_LIMIT': str(args.frame_limit),
                'SKY_AUTO_FRAME_POLICY_AVAILABLE': '1' if args.variant=='60-delta' and level_metadata else '0',
                'SKY_FRAME_POLICY': args.frame_policy,
                'SKY_ALLOW_60': '0' if args.variant == 'original' else '1',
                'SKY_FULLSCREEN': '1' if args.fullscreen else '0',
                'SKY_FPS_COUNTER': '1' if args.fps_counter else '0'})
    if args.manual_phase_cap: env['SKY_EXTERNAL_FRAME_CAP'] = '1'
    else: env.pop('SKY_EXTERNAL_FRAME_CAP',None)
    env.setdefault('BB_FPS_LIMIT','0')
    if args.memory_mode == 'compact':
        env.setdefault('MALLOC_ARENA_MAX','4')
        env.setdefault('MALLOC_TRIM_THRESHOLD_','262144')
        env['BB_TRIM_SHADER_WARMUP']='1'
    window = args.window_resolution or args.resolution
    if window:
        env['SKY_WINDOW_SIZE'] = 'x'.join(map(str, PRESETS[window]))
    if args.nvidia:
        icd = Path('/usr/share/vulkan/icd.d/nvidia_icd.json')
        if not icd.is_file():
            parser.error('NVIDIA Vulkan driver manifest is missing')
        env['VK_DRIVER_FILES'] = str(icd)
    if args.hud_pci_device:
        try:
            env['MANGOHUD_CONFIGFILE'] = str(overlay_pci_configuration(session, args.hud_pci_device))
            env['MANGOHUD_CONFIG'] = 'read_cfg,' + env['MANGOHUD_CONFIG']
        except ValueError as error:
            parser.error(str(error))
    env.setdefault('SDL_VIDEO_DRIVER', 'x11')
    env.setdefault('SKY_SUSPEND_UNSUPPORTED_NET_WORKERS', '0')
    env.setdefault('SKY_VIRTUAL_PORTAL', '1')
    if args.figure:
        env['SKY_PORTAL_FIGURE'] = str(args.figure.resolve())
    if args.timing:
        env['SKY_TIMING_TRACE'] = '1'
    if args.profile:
        env['SKY_FRAME_PROFILE'] = str(session/'frame-profile.csv')
        env['BB_FRAME_STATS'] = '1'
        env['BB_FRAME_LOG'] = str(session/'frames.csv')
    if args.cold_cache:
        # Renderer settings are kept; only compiled shader/pipeline caches start empty.
        cold = session/'gpu-user'
        cold.mkdir()
        settings = ROOT/'out/native-gpu-user/bbport.ini'
        if settings.is_file():
            (cold/'bbport.ini').write_bytes(settings.read_bytes())
        env['SKY_GPU_USER_DIR'] = str(cold)
        env['__GL_SHADER_DISK_CACHE_PATH'] = str(session/'driver-shader-cache')
        env['MESA_SHADER_CACHE_DIR'] = str(session/'driver-shader-cache')
    if args.present_limit is not None:
        env['BB_FPS_LIMIT'] = args.present_limit
    command = [str(host), '--trace-start', *map(str, files),
               str(game_root)]
    if args.mangohud:
        command.insert(0, 'mangohud')
    keys = ('SDL_VIDEO_DRIVER', 'SKY_SUSPEND_UNSUPPORTED_NET_WORKERS', 'SKY_SAVE_DATA_ROOT',
            'SKY_TLS_BRIDGE',
            'SKY_LEVEL_EVENT_MAILBOX','SKY_FRAME_POLICY','SKY_MANUAL_FRAME_LIMIT','SKY_AUTO_FRAME_POLICY_AVAILABLE',
            'SKY_VIRTUAL_PORTAL', 'SKY_TIMING_TRACE', 'SKY_WAIT_TRACE',
            'SKY_FRAME_PROFILE', 'BB_FRAME_STATS', 'BB_FRAME_LOG', 'SKY_GPU_USER_DIR',
            '__GL_SHADER_DISK_CACHE_PATH', 'MESA_SHADER_CACHE_DIR',
            'SKY_ALLOW_INCOMPLETE_PIPELINES', 'SKY_TRAP_PHASE_PROBE', 'SKY_TRAP_CLOCK_PROBE',
            'SKY_PORTAL_VOLUME','SKY_CONTROLLER_LAYOUT','SKY_FRAME_LIMIT','SKY_FULLSCREEN','SKY_FPS_COUNTER','SKY_PC_RESOLUTION','SKY_PC_QUALITY')
    preparation_checkpoint('runtime_configuration')
    metadata = {'preparation_phases':preparation_phases,'trophies':trophy_metadata,'preparation_seconds':round(time.monotonic()-preparation_started,3),'variant': args.variant, 'seconds': args.seconds,
                'save_backups': {'enabled':args.save_backups},
                'save_selection': {'source': save_source,
                                   'root': str(selected_save or ROOT/'out/ps4-saves')},
                'installation': {'title_id':installation.title_id,'app_version':installation.app_version,
                                 'base':str(installation.base),'update':str(installation.update) if installation.update else None,
                                 'executable_sha256':build['executable_sha256']},
                'performance_profile': args.performance_profile, 'motion_blur': args.motion_blur,
                'memory_mode': args.memory_mode,
                'renderer_idle': args.renderer_idle,
                'level_events': level_metadata,
                'nightmare_unlock': nightmare_metadata,
                'allocator_environment': {k: env[k] for k in ('MALLOC_ARENA_MAX','MALLOC_TRIM_THRESHOLD_') if k in env},
                'resolution': resolution_metadata,
                'graphics_assets': asset_metadata,
                'gameplay_mods': {'enabled':selected_mods,'assets':gameplay_metadata},
                'controller_glyphs':glyph_metadata,
                'movie_audio': {'mode':selected_movie_audio,'assets':movie_metadata},
                'window_size': env.get('SKY_WINDOW_SIZE', '1280x720'),
                'sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in [host, *files]},
                'diagnostic_environment': {k: env[k] for k in keys if k in env},
                'renderer_environment': {k: v for k, v in env.items() if k.startswith('BB_')},
                'overlay_environment': {k: env[k] for k in ('MANGOHUD', 'MANGOHUD_CONFIG', 'MANGOHUD_CONFIGFILE', 'DISABLE_MANGOHUD') if k in env},
                'graphics_environment': {k: env[k] for k in ('VK_DRIVER_FILES', 'VK_ICD_FILENAMES') if k in env},
                'overlay_configuration': {'path': env['MANGOHUD_CONFIGFILE'],
                    'sha256': hashlib.sha256(Path(env['MANGOHUD_CONFIGFILE']).read_bytes()).hexdigest()}
                    if env.get('MANGOHUD_CONFIGFILE') and Path(env['MANGOHUD_CONFIGFILE']).is_file() else None,
                'phase_policy': 'mod-auto-30-60' if args.frame_policy=='auto' else 'external-manual-30-60' if args.manual_phase_cap else 'native-manual-30-60'}
    (session / 'session.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Runtime log: {session / "runtime.log"}', flush=True)
    try:
        with exclusive_session(ROOT / 'out/active-session.lock'):
            if save_source == 'home-default' and not (selected_save/installation.title_id).exists():
                legacy = ROOT/'out/ps4-saves'
                if (legacy/installation.title_id).is_dir():
                    save_profile.migrate(legacy,selected_save,installation.title_id)
            if args.save_backups:
                try:
                    metadata['save_backups']['before']=save_backup.snapshot(selected_save,installation.title_id,reason='before-launch')
                except OSError as error:
                    metadata['save_backups']['before_error']=str(error)
                    print(f'Save backup unavailable; existing saves preserved: {error}',file=sys.stderr)
                (session/'session.json').write_text(json.dumps(metadata,indent=2)+'\n')
            result = run_logged(command, session, cwd=ROOT, env=env, seconds=args.seconds)
            if args.save_backups and result['stop_reason']=='process-exit' and result['returncode']==0:
                try:
                    metadata['save_backups']['after']=save_backup.snapshot(selected_save,installation.title_id,reason='after-exit')
                except (OSError,ValueError) as error:
                    metadata['save_backups']['after_error']=str(error)
                    print(f'Save backup unavailable; existing saves preserved: {error}',file=sys.stderr)
                (session/'session.json').write_text(json.dumps(metadata,indent=2)+'\n')
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result), flush=True)
    request = session / 'pc-settings-request.json'
    if result['stop_reason'] == 'process-exit' and result['returncode'] == 0 and request.is_file():
        try:
            chosen = load_settings(request)
            save_settings(preferences,chosen)
        except (OSError,ValueError,TypeError) as error:
            print(f'PC restart request rejected: {error}',file=sys.stderr)
            return 2
        restart = [sys.executable,str(Path(__file__).resolve()),'--pc-menu',args.pc_menu,'--variant',args.variant,
                   '--performance-profile',args.performance_profile,
                   '--motion-blur' if args.motion_blur else '--no-motion-blur',
                   '--memory-mode',args.memory_mode,
                   '--renderer-idle',args.renderer_idle,
                   '--movie-audio',selected_movie_audio,
                   '--resolution',chosen['resolution'],'--quality',chosen['quality'],
                   '--frame-limit',str(chosen['frame_limit']),
                   '--portal-volume',str(chosen.get('portal_volume',30)),
                   '--controller-layout',chosen.get('controller_layout',args.controller_layout),
                   '--controller-glyphs',chosen.get('controller_glyphs',args.controller_glyphs),
                   '--fullscreen' if chosen['fullscreen'] else '--no-fullscreen',
                   '--fps-counter' if chosen['fps_counter'] else '--no-fps-counter',
                   '--mangohud' if args.mangohud else '--no-mangohud']
        for flag,value in (('--trophy-config',args.trophy_config),('--figure',args.figure),('--hud-pci-device',args.hud_pci_device),
                           ('--present-limit',args.present_limit),('--save-root',selected_save)):
            if value is not None: restart += [flag,str(value)]
        restart.append('--save-backups' if args.save_backups else '--no-save-backups')
        restart.append('--nvidia' if args.nvidia else '--no-nvidia')
        restart += ['--frame-policy',chosen.get('frame_policy',args.frame_policy)]
        if args.level_events: restart.append('--level-events')
        restart.append('--unlock-nightmare' if args.unlock_nightmare else '--no-unlock-nightmare')
        for name,enabled in selected_mods.items():restart.append(('--' if enabled else '--no-')+name)
        print('Restarting with saved PC settings.',flush=True)
        os.execv(sys.executable,restart)
    return 0 if result['stop_reason'] != 'process-exit' else (result['returncode'] if result['returncode'] >= 0 else 128 - result['returncode'])


if __name__ == '__main__':
    raise SystemExit(main())

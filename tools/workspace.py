#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Local inventory, runtime probing and bounded session launch tools."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

try:
    from tools import profiles as build_profiles
    from tools import executable as executable_inspector
except ModuleNotFoundError:
    import profiles as build_profiles
    import executable as executable_inspector

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    text = json.dumps(value, indent=2) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix=f'.{path.name}-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def span(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError('metadata range outside file')
    return data[offset:offset + size]


def read_sfo(data):
    magic, version, keys, values, count = struct.unpack('<4s4I', span(data, 0, 20))
    if magic != b'\0PSF' or version != 0x101:
        raise ValueError('unsupported SFO header')
    table_end = 20 + count * 16
    if not table_end <= keys <= values <= len(data):
        raise ValueError('invalid SFO table boundaries')
    result = {}
    for i in range(count):
        key, fmt, size, capacity, offset = struct.unpack('<HHIII', span(data, 20 + i * 16, 16))
        start = keys + key
        if not keys <= start < values or size > capacity:
            raise ValueError('invalid SFO entry')
        end = data.find(b'\0', start, values)
        if end < 0:
            raise ValueError('unterminated SFO key')
        name = data[start:end].decode('utf-8')
        if name in result:
            raise ValueError('duplicate SFO key')
        raw = span(data, values + offset, size)
        span(data, values + offset, capacity)
        if fmt == 0x404:
            if size != 4:
                raise ValueError('invalid SFO integer size')
            result[name] = struct.unpack('<I', raw)[0]
        elif fmt == 0x204:
            result[name] = raw.rstrip(b'\0').decode('utf-8')
    return result


def executable_header(path):
    with path.open('rb') as stream:
        data = stream.read(64)
    if data[:4] == b'\x7fELF':
        if len(data) < 64 or data[4:7] != b'\x02\x01\x01':
            raise ValueError('expected ELF64 little-endian header')
        machine = struct.unpack_from('<H', data, 18)[0]
        if machine != 62:
            raise ValueError('expected x86-64 executable')
        return {'container': 'ELF64', 'machine': 'x86-64',
                'validation': 'header only; imports/segments not validated'}
    if data[:4] == b'O\x15=\x1d':
        return {'container': 'PS4 SELF', 'validation':
                'container signature only; plaintext/encryption status unknown'}
    raise ValueError('unrecognized executable container')


def inventory(game):
    game = game.resolve(strict=True)
    eboot = game / 'eboot.bin'
    sfo = game / 'sce_sys' / 'param.sfo'
    for path in (eboot, sfo):
        path.resolve(strict=True).relative_to(game)
    metadata = read_sfo(sfo.read_bytes())
    header = executable_header(eboot)
    try:
        inspected = executable_inspector.inspect_path(eboot)
        header.update(container=inspected['container'], entry=inspected['entry'],
                      program_headers=inspected['program_headers'], inspection_status='inspected',
                      validation='ELF metadata/import declarations inspected; relocation and runtime behavior unverified')
        imports = inspected['imports']
    except executable_inspector.UnsupportedExecutable as error:
        header.update(inspection_status='unsupported', inspection_reason=str(error))
        imports = {'status': 'unavailable for unsupported payload', 'count': None,
                   'symbols': [], 'libraries': [], 'runtime_resolution': 'not checked'}
    modules = []
    for path in sorted(game.rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.prx', '.sprx'):
            # Do not inventory symlink targets outside the supplied dump.
            path.resolve(strict=True).relative_to(game)
            modules.append({'path': str(path.relative_to(game)),
                            'bytes': path.stat().st_size, 'sha256': digest(path)})
    return {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'metadata': {k: metadata[k] for k in ('TITLE', 'TITLE_ID', 'APP_VER', 'VERSION', 'CONTENT_ID') if k in metadata},
            'executable': {'bytes': eboot.stat().st_size, 'sha256': digest(eboot), **header},
            'modules': modules, 'status': 'inventory only; not a supported-build or playability claim',
            'imports': imports}


def stage_runtime(archive, lock, destination):
    runtime = lock['runtime']
    if digest(archive) != runtime['archive_sha256']:
        raise ValueError('runtime archive hash mismatch')
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / Path(runtime['member']).name
    with zipfile.ZipFile(archive) as bundle:
        info = bundle.getinfo(runtime['member'])
        # Read exactly the locked member; never extract arbitrary archive paths.
        if info.file_size > 256 * 1024 * 1024:
            raise ValueError('runtime exceeds staging size limit')
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temp:
            temporary = Path(temp.name)
            try:
                with bundle.open(info) as source:
                    shutil.copyfileobj(source, temp)
                temp.flush()
                if digest(temporary) != runtime['member_sha256']:
                    raise ValueError('runtime member hash mismatch')
                temporary.chmod(0o755)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    return target


def prepare_session(game, profile_id, figure=None):
    profile = build_profiles.load_profile(ROOT / 'profiles', profile_id)
    report = inventory(game)
    identification = build_profiles.identify_build(profile, report)
    runtime = read_json(ROOT / 'references.lock.json')['runtime']
    binary = ROOT / '.local' / 'runtime' / Path(runtime['member']).name
    if not binary.is_file() or digest(binary) != runtime['member_sha256']:
        raise ValueError('stage the pinned runtime before preparing a session')
    if figure and figure.stat().st_size != 1024:
        raise ValueError('expected a 1024-byte figure dump; other formats are not supported by this tool')
    parent = ROOT / 'out' / 'sessions'
    parent.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix=f'{profile_id}-', dir=parent))
    for name in ('figures', 'saves', 'captures', 'logs', 'config'):
        (session / name).mkdir()
    write_json(session / 'inventory.json', report)
    manifest = {'schema_version': 1, 'profile': profile['id'],
                'game_root': str(game.resolve()), 'runtime_sha256': digest(binary),
                'runtime_path': str(binary), 'status': 'prepared; not launched',
                'profile_build_match': identification['status'] + '; no patches applied',
                'build_identification': identification,
                'profile_sha256': digest(ROOT / 'profiles' / f'{profile_id}.json'),
                'configuration': 'not connected to shadPS4; directories alone do not isolate its saves/config',
                'acceptance_cases': profile['acceptance_cases'], 'figure': None}
    if figure:
        source_hash = digest(figure)
        copied = session / 'figures' / 'working.sky'
        shutil.copyfile(figure, copied)
        if digest(copied) != source_hash or digest(figure) != source_hash:
            raise ValueError('figure changed while preparing the session')
        manifest['figure'] = {'working_copy': str(copied.relative_to(session)),
                              'initial_sha256': source_hash}
    write_json(session / 'session.json', manifest)
    return session


def runtime_environment(directory):
    """XDG routing was observed during CLI probing; do not change HOME."""
    env = os.environ.copy()
    for variable, folder in (('XDG_DATA_HOME', 'data'), ('XDG_CONFIG_HOME', 'config'),
                             ('XDG_CACHE_HOME', 'cache'), ('TMPDIR', 'tmp')):
        path = directory / folder
        path.mkdir(parents=True, exist_ok=True)
        env[variable] = str(path.resolve())
    # shadPS4 asks to migrate desktop saves when default home/1000 is absent.
    # Seed only empty session-owned homes; never inspect or migrate old saves.
    home = Path(env['XDG_DATA_HOME']) / 'shadPS4/home'
    for user in ('1000', '1001', '1002', '1003'):
        for folder in ('savedata', 'trophy', 'inputs'):
            (home / user / folder).mkdir(parents=True, exist_ok=True)
    return env


def execute(command, directory, timeout):
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError('timeout must be an integer between 1 and 86400 seconds')
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    command = [str(value) for value in command]
    if not command:
        raise ValueError('command must not be empty')
    outcome = {'command': command, 'timeout_seconds': timeout,
               'started_utc': datetime.now(timezone.utc).isoformat(),
               'gameplay_verified': False, 'returncode': None}
    environment = runtime_environment(directory)
    recorded_variables = ('SDL_VIDEO_DRIVER', 'SDL_VIDEODRIVER', 'VK_DRIVER_FILES',
                          'VK_ICD_FILENAMES', 'VK_LOADER_LAYERS_DISABLE',
                          'XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'TMPDIR')
    outcome['environment'] = {key: environment[key] for key in recorded_variables if key in environment}
    with (directory / 'runtime.log').open('wb') as log:
        try:
            process = subprocess.Popen(command, cwd=directory, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            outcome.update(reason='spawn-error', error=str(error),
                           elapsed_seconds=time.monotonic() - started)
            write_json(directory / 'result.json', outcome)
            return outcome
        reason = 'exited'
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            reason = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else 'interrupted'
        finally:
            # The child owns a new session/process group. Never kill by name or
            # traverse unrelated processes. A launcher may exit before its children.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                pass
            finally:
                # Always remove remaining descendants, even if the leader exited
                # already or cleanup was interrupted. Reap the direct child too.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        outcome.update(reason=reason, returncode=process.returncode,
                       elapsed_seconds=time.monotonic() - started)
    write_json(directory / 'result.json', outcome)
    return outcome


def pinned_runtime():
    lock = read_json(ROOT / 'references.lock.json')['runtime']
    binary = ROOT / '.local/runtime' / Path(lock['member']).name
    if not binary.is_file() or digest(binary) != lock['member_sha256']:
        raise ValueError('pinned runtime missing or hash mismatch; run stage-runtime')
    return binary.resolve()


def probe_runtime():
    binary = pinned_runtime()
    parent = ROOT / '.local/probes'
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='cli-', dir=parent))
    result = execute([str(binary), '--appimage-extract-and-run', '--help'], directory, 20)
    help_text = (directory / 'runtime.log').read_text(errors='replace')
    required = ('--game', '--override-root', '--ignore-game-patch')
    result['required_options_present'] = all(option in help_text for option in required)
    result['runtime_sha256'] = digest(binary)
    write_json(directory / 'result.json', result)
    if result['reason'] != 'exited' or result['returncode'] != 0 or not result['required_options_present']:
        raise ValueError(f'CLI probe failed; inspect {directory}')
    return directory


def launch_session(directory, timeout):
    directory = directory.resolve(strict=True)
    directory.relative_to((ROOT / 'out/sessions').resolve())
    manifest = read_json(directory / 'session.json')
    if manifest['status'] != 'prepared; not launched':
        raise ValueError('session already attempted; prepare a fresh session')
    binary = pinned_runtime()
    if digest(binary) != manifest['runtime_sha256']:
        raise ValueError('session runtime differs from current pinned runtime')
    expected = read_json(directory / 'inventory.json')
    game = Path(manifest['game_root'])
    current = inventory(game)
    for key in ('metadata', 'executable', 'modules'):
        if current[key] != expected[key]:
            raise ValueError(f'game {key} changed after session preparation')
    if 'profile_sha256' in manifest:
        build_profiles.load_profile(ROOT / 'profiles', manifest['profile'])
        if digest(ROOT / 'profiles' / f'{manifest["profile"]}.json') != manifest['profile_sha256']:
            raise ValueError('profile changed after session preparation')
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError('timeout must be an integer between 1 and 86400 seconds')
    # Exclusive creation claims the attempt even if two callers both read the
    # prepared manifest before either updates it. Keep the marker for audit.
    try:
        with (directory / 'launch.claim').open('x') as claim:
            claim.write(datetime.now(timezone.utc).isoformat() + '\n')
    except FileExistsError as error:
        raise ValueError('session already claimed; prepare a fresh session') from error
    manifest['status'] = 'launch attempted; gameplay unverified'
    manifest['configuration'] = ('XDG data/config/cache/temp paths set inside session logs; '
                                 'game content root inferred from executable; save behavior unverified')
    manifest['automatic_patches'] = 'disabled'
    manifest['figure_attachment'] = 'not automated; load figures/working.sky manually in runtime'
    write_json(directory / 'session.json', manifest)
    command = [str(binary), '--appimage-extract-and-run', '--game', str(game / 'eboot.bin'),
               '--ignore-game-patch']
    result = execute(command, directory / 'logs', timeout)
    result['playability'] = 'unverified regardless of exit status'
    write_json(directory / 'logs/result.json', result)
    manifest['status'] = 'launch finished; gameplay unverified'
    manifest['launch_outcome'] = {'reason': result['reason'], 'returncode': result['returncode']}
    write_json(directory / 'session.json', manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('probe-runtime')
    launch = sub.add_parser('launch-session')
    launch.add_argument('session', type=Path)
    launch.add_argument('--timeout', type=int, default=300)
    stage = sub.add_parser('stage-runtime')
    stage.add_argument('--archive', type=Path, default=ROOT.parent / 'shadps4-linux-sdl-0.20.0.zip')
    inspect = sub.add_parser('inventory')
    inspect.add_argument('game', type=Path)
    executable = sub.add_parser('inspect-executable')
    executable.add_argument('executable', type=Path)
    session = sub.add_parser('prepare-session')
    session.add_argument('game', type=Path)
    session.add_argument('--profile', required=True, choices=('trap-team', 'swap-force'))
    session.add_argument('--figure', type=Path)
    args = parser.parse_args()
    if args.command == 'doctor':
        binary = ROOT / '.local/runtime/Shadps4-sdl.AppImage'
        lock = read_json(ROOT / 'references.lock.json')['runtime']
        print(json.dumps({'python': platform.python_version(), 'host': platform.system(),
                          'architecture': platform.machine(),
                          'runtime_staged': binary.is_file(),
                          'runtime_hash_matches': binary.is_file() and digest(binary) == lock['member_sha256'],
                          'source_commit': lock['source_commit'],
                          'tools': {name: shutil.which(name) for name in ('git', 'cmake', 'ninja', 'vulkaninfo')},
                          'scope': 'environment inventory, not a runtime/GPU compatibility test'}, indent=2))
    elif args.command == 'stage-runtime':
        print(stage_runtime(args.archive, read_json(ROOT / 'references.lock.json'), ROOT / '.local/runtime'))
    elif args.command == 'inventory':
        print(json.dumps(inventory(args.game), indent=2))
    elif args.command == 'inspect-executable':
        print(json.dumps(executable_inspector.inspect_path(args.executable), indent=2))
    elif args.command == 'probe-runtime':
        print(probe_runtime())
    elif args.command == 'launch-session':
        result = launch_session(args.session, args.timeout)
        print(json.dumps(result, indent=2))
        return 124 if result['reason'] == 'timeout' else (130 if result['reason'] == 'interrupted' else (0 if result['returncode'] == 0 else 1))
    else:
        print(prepare_session(args.game, args.profile, args.figure))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, struct.error, zipfile.BadZipFile) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact executable/profile selection; preparation policy belongs in profiles."""
import hashlib
import json
from pathlib import Path
try:
    from . import game_library
except ImportError:
    import game_library

US_UPDATE_SHA256 = 'de464fa2c734dd06b1e957098e8d0a20a1acb8599f073811c4a89c09986a4e56'
ORIGINAL_SHA256 = 'bd5c0433860287599824adb3660964ae623c0505c1300e86cd17e65d5315d3bd'
LEGACY_PACKS = {'original':'native-linked-boot-weak', '60':'native-linked-one-vblank-experimental',
                '60-delta':'native-linked-60-delta-experimental'}


def relative(root, value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or '\\' in str(path):
        raise ValueError('Preparation profile paths must stay inside the project')
    result = Path(root)/path
    if any(p.is_symlink() for p in (result,*result.parents)):
        raise ValueError('Preparation paths refuse symlinks')
    return result


def identity(root, install):
    executable = install.source('eboot.bin')
    if executable.is_symlink():raise ValueError('Game executable refuses symlinks')
    if executable.stat().st_size>512*1024*1024:raise ValueError('Game executable exceeds the inspection limit')
    checksum = hashlib.sha256()
    with executable.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):checksum.update(block)
    digest = checksum.hexdigest()
    for profile in game_library.profiles(root):
        for build in profile['validated_builds']:
            if (build.get('title_id'),build.get('app_version'),build.get('executable_sha256')) == (install.title_id,install.app_version,digest):
                if not isinstance(build.get('preparation'),dict):
                    raise ValueError('No preparation instructions for this verified build')
                return profile,build,digest
    raise ValueError('No verified executable profile for this title/version/hash')


def configuration(root, install, variant):
    root = Path(root)
    profile,build,digest = identity(root,install)
    prep = build['preparation']
    if variant not in prep.get('variants',{}):raise ValueError('This profile does not allow the requested variant')
    record = prep['variants'][variant]
    pack = relative(root,'out/'+record['pack'])
    state = root/'.local/game-preparation'/install.title_id/install.app_version/'state.json'
    if state.is_file() and not state.is_symlink():
        try:
            marker = json.loads(state.read_text())['steps']['pack.'+variant]
            candidate = relative(root,next(p for p in marker['outputs'] if Path(p).name=='image.pack'))
            if candidate.is_relative_to(root/'out'):pack = candidate.parent
        except (ValueError,KeyError,StopIteration,TypeError):pass
    return dict(pack=pack,executable=install.source('eboot.bin'),executable_sha256=digest,
                profile_id=profile['id'],build=build,preparation=prep,
                **{name:relative(root,path) for name,path in prep['recipes'].items()})

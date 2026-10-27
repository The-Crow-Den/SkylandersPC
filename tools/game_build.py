# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact supported executable/profile selection, separate from install discovery."""
import hashlib
from pathlib import Path

US_UPDATE_SHA256 = 'de464fa2c734dd06b1e957098e8d0a20a1acb8599f073811c4a89c09986a4e56'
ORIGINAL_SHA256 = 'bd5c0433860287599824adb3660964ae623c0505c1300e86cd17e65d5315d3bd'
LEGACY_PACKS = {'original':'native-linked-boot-weak', '60':'native-linked-one-vblank-experimental',
                '60-delta':'native-linked-60-delta-experimental'}


def configuration(root, install, variant):
    digest = hashlib.sha256(install.source('eboot.bin').read_bytes()).hexdigest()
    if (install.title_id, install.app_version, digest)==('CUSA00626','01.01',US_UPDATE_SHA256):
        prefix = 'trap-team-us-01.01-'
        pack = f'native-us-01.01-{variant}'
    elif install.app_version=='01.00' and digest==ORIGINAL_SHA256:
        prefix = 'trap-team-'
        pack = LEGACY_PACKS[variant]
    else:
        raise ValueError('No verified executable profile for this title/version/hash')
    return dict(pack=Path(root)/'out'/pack, executable=install.source('eboot.bin'),
                executable_sha256=digest,
                **{key:Path(root)/'profiles/patches'/f'{prefix}{key}.json'
                   for key in ('resolution','level-events','nightmare')})

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only exact-build Trap Team timing evidence; never patches or launches."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from tools.executable import Image
from tools.game_build import US_UPDATE_SHA256
from tools.patches import validate


def source_address(image, source_offset, size):
    """Translate physical SELF bytes through ELF file offsets to load addresses."""
    matches = []
    regions = image.regions
    if regions is None:
        regions = [(0, len(image.data), 0)]
    for elf, length, source in regions:
        if source <= source_offset and source_offset + size <= source + length:
            offset = elf + source_offset - source
            for segment in image.programs:
                if (segment['type'] == 1 and segment['offset'] <= offset and
                        offset + size <= segment['offset'] + segment['filesz']):
                    matches.append(segment['vaddr'] + offset - segment['offset'])
    if len(matches) != 1:
        raise ValueError('patch must map to exactly one load segment')
    return matches[0]


def audit(data, manifest):
    if hashlib.sha256(data).hexdigest() != US_UPDATE_SHA256:
        raise ValueError('timing audit supports only exact US 01.01 executable')
    if (manifest.get('title_id'), manifest.get('app_version')) != ('CUSA00626', '01.01'):
        raise ValueError('timing audit requires US 01.01 manifest')
    patches = validate(data, manifest)
    image = Image(data)
    sites = [dict(id=ident, file_offset=offset,
                  guest_address=source_address(image, offset, len(before)))
             for offset, before, after, ident in patches]
    lower, upper = (struct.unpack('<f', image.virtual(address, 4))[0]
                    for address in (0xcf2444, 0xcf2440))
    if (lower, upper) != (0.5, 3.0):
        raise ValueError('timing clamp constants mismatch')
    return dict(schema_version=1, executable_sha256=US_UPDATE_SHA256,
                sites=sites, lower_nominal_multiplier=lower,
                upper_nominal_multiplier=upper,
                status='static identity and mapping verified; gameplay speed unverified',
                cautions=['Main and renderer clocks must not be globally halved.',
                          'Nominal interval and individual subsystem consumers require measurement.',
                          'Existing minimum-clamp bypass is not a simulation/render separation.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--manifest', type=Path,
                        default=Path('patches/trap-team-CUSA00626-01.01-60-delta.experimental.json'))
    args = parser.parse_args()
    print(json.dumps(audit(args.executable.read_bytes(), json.loads(args.manifest.read_text())), indent=2))


if __name__ == '__main__':
    main()

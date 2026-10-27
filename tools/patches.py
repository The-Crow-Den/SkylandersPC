#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate exact-build byte patches; optionally write a new private working copy."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def validate(data, manifest):
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('unsupported patch schema')
    actual = hashlib.sha256(data).hexdigest()
    if manifest.get('executable_sha256') != actual:
        raise ValueError('executable hash mismatch')
    if not all(isinstance(manifest.get(key), str) and manifest[key].strip()
               for key in ('title_id', 'app_version')):
        raise ValueError('patch must declare title ID and app version')
    entries = manifest.get('patches')
    if not isinstance(entries, list) or not entries or len(entries) > 4096:
        raise ValueError('patch list must contain 1..4096 entries')
    checked, identifiers = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('patch entries must be objects')
        ident = entry.get('id')
        if not isinstance(ident, str) or not ident or ident in identifiers:
            raise ValueError('patch IDs must be nonempty and unique')
        identifiers.add(ident)
        if entry.get('kind') not in ('compatibility', 'enhancement') or not isinstance(entry.get('reason'), str) or not entry['reason'].strip():
            raise ValueError('patch must declare kind and reason')
        offset = entry.get('file_offset')
        if type(offset) is not int or offset < 0:
            raise ValueError('file_offset must be a nonnegative integer (not a virtual address)')
        if not all(isinstance(entry.get(key), str) for key in ('expected_hex', 'replacement_hex')):
            raise ValueError('patch bytes must be hex strings')
        before, after = bytes.fromhex(entry['expected_hex']), bytes.fromhex(entry['replacement_hex'])
        if not before or len(before) != len(after):
            raise ValueError('patch must preserve byte length')
        if offset + len(before) > len(data):
            raise ValueError('patch range outside executable')
        if data[offset:offset + len(before)] != before:
            raise ValueError(f'original bytes mismatch: {ident}')
        checked.append((offset, before, after, ident))
    checked.sort()
    for previous, current in zip(checked, checked[1:]):
        if previous[0] + len(previous[1]) > current[0]:
            raise ValueError('overlapping patch ranges')
    return checked


def patch_copy(source, manifest, output=None):
    data = source.read_bytes()
    checked = validate(data, manifest)
    patched = bytearray(data)
    for offset, before, after, ident in checked:
        patched[offset:offset + len(before)] = after
    result = {'status': 'validated; not applied', 'patches': [p[3] for p in checked],
              'input_sha256': hashlib.sha256(data).hexdigest(),
              'output_sha256': hashlib.sha256(patched).hexdigest(),
              'scope': 'file-byte validation only; title metadata and gameplay not verified'}
    if output:
        if output.resolve() == source.resolve():
            raise ValueError('output must not be the original executable')
        # Exclusive creation also refuses aliases/hard links and existing game files.
        with output.open('xb') as stream:
            try:
                stream.write(patched)
                if hashlib.sha256(source.read_bytes()).hexdigest() != result['input_sha256']:
                    raise ValueError('source changed during patch preparation')
            except BaseException:
                output.unlink(missing_ok=True)
                raise
        result['status'] = 'written to separate working copy; gameplay unverified'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, help='new private file; existing files are refused')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    print(json.dumps(patch_copy(args.executable, manifest, args.output), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact-build profile identification and explicitly selected patch manifests.

This module identifies recorded builds; it does not certify runtime behavior,
apply patches, or make unknown dumps unsuitable for unpatched investigation.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

ID = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
TITLE_ID = re.compile(r'CUSA[0-9]{5}\Z')
VERSION = re.compile(r'[0-9]{2}\.[0-9]{2}\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def _text(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f'invalid {label}')
    return value


def _identity(build):
    return (_text(build.get('title_id'), TITLE_ID, 'title_id'),
            _text(build.get('app_version'), VERSION, 'app_version'),
            _text(build.get('executable_sha256'), SHA256, 'executable_sha256'))


def validate_profile(profile, expected_id=None):
    """Validate a schema-v1 profile; return an independent copy, never mutate it."""
    if not isinstance(profile, dict) or type(profile.get('schema_version')) is not int or profile['schema_version'] != 1:
        raise ValueError('unsupported profile schema')
    ident = _text(profile.get('id'), ID, 'profile id')
    if expected_id is not None and ident != expected_id:
        raise ValueError('profile ID differs from requested ID')
    if not isinstance(profile.get('title'), str) or not profile['title'].strip():
        raise ValueError('profile title must be nonempty')
    builds, patches = profile.get('validated_builds'), profile.get('patches')
    if not isinstance(builds, list) or not isinstance(patches, list):
        raise ValueError('validated_builds and patches must be lists')
    build_ids, identities = set(), set()
    for build in builds:
        if not isinstance(build, dict):
            raise ValueError('build must be an object')
        build_id = _text(build.get('id'), ID, 'build id')
        identity = _identity(build)
        if build_id in build_ids or identity in identities:
            raise ValueError('duplicate build ID or executable identity')
        build_ids.add(build_id)
        identities.add(identity)
    patch_ids = set()
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError('patch reference must be an object')
        patch_id = _text(patch.get('id'), ID, 'patch id')
        if patch_id in patch_ids:
            raise ValueError('duplicate patch ID')
        patch_ids.add(patch_id)
        if patch.get('build_id') not in build_ids:
            raise ValueError('patch references an unknown build')
        if patch.get('kind') not in ('compatibility', 'enhancement'):
            raise ValueError('invalid patch kind')
        _text(patch.get('manifest_sha256'), SHA256, 'manifest_sha256')
        path = patch.get('manifest')
        if not isinstance(path, str) or not path or '\\' in path or '\x00' in path:
            raise ValueError('invalid patch manifest path')
        parts = PurePosixPath(path)
        if parts.is_absolute() or '..' in parts.parts or ':' in path or parts.suffix != '.json':
            raise ValueError('patch manifest must be a relative JSON path without traversal')
    cases = profile.get('acceptance_cases', [])
    if not isinstance(cases, list) or any(not isinstance(case, str) or not case.strip() for case in cases):
        raise ValueError('acceptance_cases must contain nonempty strings')
    return copy.deepcopy(profile)


def load_profile(directory, profile_id):
    """Load <directory>/<stable-id>.json and verify filename/declared ID agree."""
    _text(profile_id, ID, 'profile id')
    root = Path(directory).resolve(strict=True)
    path = (root / f'{profile_id}.json').resolve(strict=True)
    path.relative_to(root)
    return validate_profile(json.loads(path.read_text(encoding='utf-8')), profile_id)


def identify_build(profile, inventory):
    """Match TITLE_ID + APP_VER + exact file SHA-256, with no hash-only fallback."""
    profile = validate_profile(profile)
    if not isinstance(inventory, dict):
        raise ValueError('inventory must be an object')
    metadata, executable = inventory.get('metadata', {}), inventory.get('executable', {})
    if not isinstance(metadata, dict) or not isinstance(executable, dict):
        raise ValueError('inventory metadata/executable must be objects')
    candidate = {'title_id': metadata.get('TITLE_ID'), 'app_version': metadata.get('APP_VER'),
                 'executable_sha256': executable.get('sha256')}
    try:
        identity = _identity(candidate)
    except ValueError:
        return {'profile_id': profile['id'], 'status': 'unverified', 'build_id': None,
                'reason': 'missing or invalid exact build identity', 'patches_allowed': False}
    for build in profile['validated_builds']:
        if _identity(build) == identity:
            return {'profile_id': profile['id'], 'status': 'matched', 'build_id': build['id'],
                    'reason': 'metadata and executable hash match profile record',
                    'patches_allowed': True,
                    'gameplay_verified': False}
    known_title = any(build['title_id'] == identity[0] for build in profile['validated_builds'])
    return {'profile_id': profile['id'], 'status': 'mismatch' if known_title else 'unverified', 'build_id': None,
            'reason': 'no exact metadata and executable hash match', 'patches_allowed': False}


def select_patches(profile, inventory, requested_ids=()):
    """Return only explicitly requested patch references for an exact build.

    Unknown builds are allowed to have an empty selection for baseline testing;
    requesting any patch for them is an error. This never applies a patch.
    """
    profile = validate_profile(profile)
    if not isinstance(requested_ids, (list, tuple)):
        raise ValueError('requested patch IDs must be a list or tuple')
    requested = list(requested_ids)
    if any(not isinstance(value, str) or not ID.fullmatch(value) for value in requested):
        raise ValueError('invalid requested patch ID')
    if len(set(requested)) != len(requested):
        raise ValueError('duplicate requested patch ID')
    match = identify_build(profile, inventory)
    if not requested:
        return []
    if not match['patches_allowed']:
        raise ValueError('patches refused for unknown build')
    available = {patch['id']: patch for patch in profile['patches'] if patch['build_id'] == match['build_id']}
    if any(ident not in available for ident in requested):
        raise ValueError('requested patch not registered for this exact build')
    return [copy.deepcopy(available[ident]) for ident in requested]


def load_selected_patches(profile, inventory, requested_ids, manifest_root):
    """Resolve selected manifests inside root and verify hash and build metadata.

    Byte-level expected/replacement checks remain the patch writer's job.
    """
    references = select_patches(profile, inventory, requested_ids)
    if not references:
        return []
    root = Path(manifest_root).resolve(strict=True)
    result = []
    for reference in references:
        path = (root / reference['manifest']).resolve(strict=True)
        path.relative_to(root)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != reference['manifest_sha256']:
            raise ValueError('patch manifest hash mismatch')
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            raise ValueError('patch manifest must be an object')
        expected = (inventory['metadata']['TITLE_ID'], inventory['metadata']['APP_VER'], inventory['executable']['sha256'])
        if _identity(manifest) != expected:
            raise ValueError('patch manifest identity differs from selected build')
        entries = manifest.get('patches')
        if not isinstance(entries, list) or not entries:
            raise ValueError('selected patch manifest must contain patch entries')
        if any(not isinstance(entry, dict) or entry.get('kind') != reference['kind'] for entry in entries):
            raise ValueError('patch entry kind differs from profile declaration')
        result.append({'reference': reference, 'manifest': manifest})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', help='stable profile ID, e.g. trap-team')
    parser.add_argument('inventory', type=Path)
    parser.add_argument('--profiles', type=Path, default=Path(__file__).resolve().parents[1] / 'profiles')
    args = parser.parse_args()
    profile = load_profile(args.profiles, args.profile)
    report = identify_build(profile, json.loads(args.inventory.read_text(encoding='utf-8')))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)

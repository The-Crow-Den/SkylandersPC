# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact-build Trap Team graphics-device resolution experiment, never in-place."""
import hashlib
import json
import struct
import os
import re
import shutil
from pathlib import Path

try:
    from . import prepare_native
except ImportError:
    import prepare_native

PRESETS = {'720p': (1280, 720), '900p': (1600, 900),
           '1080p': (1920, 1080), '1440p': (2560, 1440), '1600p': (2560, 1600), '2160p': (3840, 2160)}
PROFILE = Path(__file__).resolve().parents[1] / 'profiles/patches/trap-team-resolution.json'
SHADOWS = {'low': (512, 2048), 'native': (1024, 4096), 'high': (2048, 8192)}


def renderer_options(data, dimensions=None, shadows='native', motion_blur=True):
    """Edit named targets only, preserving all parent/scale relationships."""
    def target(data, name, original, replacement):
        pattern = rb'(<object\s+refname="' + re.escape(name.encode()) + rb'"[^>]*>)(.*?)(</object>)'
        matches = list(re.finditer(pattern, data, re.DOTALL))
        if len(matches) != 1:
            raise ValueError('renderer target missing or ambiguous: ' + name)
        match = matches[0]
        body = match[2]
        for field, before, after in zip(('_width', '_height'), original, replacement):
            pattern = rb'(<var\s+name="' + field.encode() + rb'"\s+value=")' + str(before).encode() + rb'("\s*/>)'
            body, count = re.subn(pattern, lambda m: m[1] + str(after).encode() + m[2], body)
            if count != 1:
                raise ValueError('renderer target dimensions mismatch: ' + name)
        return data[:match.start(2)] + body + data[match.end(2):]
    if dimensions:
        data = target(data, 'mainScene', (1920, 1080), dimensions)
    if shadows != 'native':
        data = target(data, 'cascadeShadowsDepth', SHADOWS['native'], SHADOWS[shadows])
    if not motion_blur:
        # Bypass the complete blur graph, including its otherwise-unused velocity
        # reduction passes. FXAA must consume the preceding scene, never stale blur.
        pattern = rb'(<object\s+refname="defRenderer_igRenderPassList"[^>]*count=")49("[^>]*>)(.*?)(</object>)'
        matches = list(re.finditer(pattern,data,re.DOTALL))
        if len(matches) != 1:
            raise ValueError('unexpected main renderer pass list')
        match = matches[0]
        body = match[3]
        for name in ('velocityBundle','motionBlurBundle'):
            body, count = re.subn(rb'\s*<listitem ref="this\.'+name.encode()+rb'"\s*/>',b'',body)
            if count != 1:
                raise ValueError('motion blur graph mismatch')
        data = data[:match.start()] + match[1] + b'47' + match[2] + body + match[4] + data[match.end():]
        pattern = rb'(<object\s+refname="fxaa_igRenderTargetInputDataList_igRenderTargetInputData"[^>]*>)(.*?)(</object>)'
        matches = list(re.finditer(pattern,data,re.DOTALL))
        if len(matches) != 1:
            raise ValueError('FXAA input missing or ambiguous')
        match = matches[0]
        before = b'ref="this.motionBlurredScene"'
        if match[2].count(before) != 1:
            raise ValueError('unexpected FXAA source')
        body = match[2].replace(before,b'ref="this.defocusedScene"')
        data = data[:match.start(2)]+body+data[match.end(2):]
    return data


def prepare_assets(game, session, dimensions=None, shadows='native', motion_blur=True, profile_path=None):
    profile = json.loads(Path(profile_path or PROFILE).read_text())
    source = game / 'renderer/tfbRenderer.igx'
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != profile['renderer_sha256']:
        raise ValueError('graphics options refuse unknown renderer asset')
    patched = renderer_options(original, dimensions, shadows, motion_blur)
    output = session / 'game'
    # Immutable assets share disk blocks through hard links. Only the overridden
    # file is unlinked/replaced; the runtime opens /app0 strictly read-only.
    def link_file(src, dst):
        if Path(src).is_symlink() or not Path(src).is_file():
            raise ValueError('asset preparation refuses non-regular files')
        return os.link(src, dst)
    # Reject directory links as well: never traverse outside the supplied dump.
    if any(p.is_symlink() for p in game.rglob('*')):
        raise ValueError('asset preparation refuses symlinks')
    shutil.copytree(game, output, copy_function=link_file)
    destination = output / 'renderer/tfbRenderer.igx'
    destination.unlink()
    with destination.open('xb') as stream:
        stream.write(patched)
    if source.read_bytes() != original:
        raise ValueError('renderer asset changed during preparation')
    return output, {'source_renderer_sha256': hashlib.sha256(original).hexdigest(),
                    'patched_renderer_sha256': hashlib.sha256(patched).hexdigest(),
                    'shadow_preset': shadows, 'shadow_atlas': list(SHADOWS[shadows]),
                    'scene_size': list(dimensions or (1920,1080)),
                    'motion_blur': motion_blur,
                    'asset_root': str(output), 'unchanged_assets': 'read-only hard links'}


def patch_pack(data, preset, variant, profile):
    width, height = PRESETS[preset]
    if hashlib.sha256(data).hexdigest() != profile['pack_sha256'].get(variant):
        raise ValueError('resolution patch refuses unknown linked executable pack')
    header = prepare_native.HEADER.unpack_from(data)
    if header[0] != prepare_native.MAGIC or not 0 < header[4] <= 4096:
        raise ValueError('invalid resolution input pack')
    expected = bytes.fromhex(profile['expected_hex'])
    address = profile['virtual_address']
    locations = []
    for index in range(header[4]):
        start, memory, length, flags, offset = prepare_native.SEGMENT.unpack_from(
            data, prepare_native.HEADER.size + index * prepare_native.SEGMENT.size)
        if flags & 1 and start <= address and address + len(expected) <= start + length:
            locations.append(offset + address - start)
    if len(locations) != 1:
        raise ValueError('resolution instructions are not uniquely mapped executable bytes')
    offset = locations[0]
    if data[offset:offset + len(expected)] != expected:
        raise ValueError('resolution instruction bytes mismatch')
    # Two movl immediate operands in the graphics-device startup descriptor.
    replacement = b'\xc7\x45\x90' + struct.pack('<I', width) + b'\xc7\x45\x94' + struct.pack('<I', height)
    if len(replacement) != len(expected):
        raise ValueError('resolution patch must preserve instruction length')
    result = bytearray(data)
    result[offset:offset + len(expected)] = replacement
    return bytes(result)


def prepare_resolution(pack, session, executable, preset, variant, profile_path=None):
    profile = json.loads(Path(profile_path or PROFILE).read_text())
    if hashlib.sha256(executable.read_bytes()).hexdigest() != profile['executable_sha256']:
        raise ValueError('resolution patch refuses unknown original executable')
    source = pack / 'image.pack'
    data = source.read_bytes()
    patched = patch_pack(data, preset, variant, profile)
    output = session / 'resolution.pack'
    with output.open('xb') as stream:
        stream.write(patched)
    return output, {'preset': preset, 'requested_internal_size': list(PRESETS[preset]),
                    'status': profile['status'], 'title_id': profile['title_id'],
                    'source_pack_sha256': hashlib.sha256(data).hexdigest(),
                    'output_pack_sha256': hashlib.sha256(patched).hexdigest()}

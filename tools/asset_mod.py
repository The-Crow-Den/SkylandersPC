# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded expected-byte asset recipes for optional game-specific modifications.

Recipes carry hashes and offsets, never replacement game archives. Preparation
breaks private session hard links only after validating every requested asset.
Raw LZMA uses the same restricted format supported by the difficulty-menu mod.
"""
import hashlib
import copy
import lzma
import os
from pathlib import Path, PurePosixPath
import struct
import tempfile

try:from .file_integrity import VerifiedDigests
except ImportError:from file_integrity import VerifiedDigests
try:from . import lzma_fill
except ImportError:import lzma_fill


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def number(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid asset recipe ' + name)
    return value


def edits(data, recipe):
    output = bytearray(data)
    end = 0
    for item in sorted(recipe, key=lambda item: item['offset']):
        at = number(item['offset'], len(data), 'edit offset')
        if 'copy_from' in item:
            source = number(item['copy_from'], len(data), 'copy source')
            length = number(item['length'], len(data), 'copy length')
            if (not length or source + length > len(data) or at + length > len(data) or
                    'expected_hex' in item or 'replacement_hex' in item):
                raise ValueError('invalid asset copy edit')
            # Read the verified original block, including when another edit
            # changes this source region in the output.
            before, after = data[at:at+length], data[source:source+length]
            if (digest(before) != item['expected_sha256'] or
                    digest(after) != item['source_sha256']):
                raise ValueError('asset copy expected bytes mismatch')
        else:
            before = bytes.fromhex(item['expected_hex'])
            after = bytes.fromhex(item['replacement_hex'])
        if not before or len(before) != len(after) or at < end or at + len(before) > len(data):
            raise ValueError('overlapping or invalid asset edits')
        if data[at:at + len(before)] != before:
            raise ValueError('asset expected bytes mismatch')
        output[at:at + len(after)] = after
        end = at + len(before)
    return bytes(output)


def patch_asset(data, recipe):
    if digest(data) != recipe['source_sha256']:
        raise ValueError('asset mod refuses an unknown source asset')
    output = bytearray(data)
    end = 0
    chunks = recipe['chunks']
    if not chunks or len(chunks) > 256:
        raise ValueError('invalid asset recipe chunk count')
    for chunk in sorted(chunks, key=lambda chunk: chunk['offset']):
        at = number(chunk['offset'], len(data), 'chunk offset')
        allocation = number(chunk['allocation'], len(data), 'allocation')
        size = number(chunk['decoded_size'], 32768, 'decoded size')
        if not allocation or not size or at < end or at + allocation > len(data):
            raise ValueError('overlapping or invalid asset allocations')
        end = at + allocation
        block = data[at:end]
        filters = None
        if chunk['encoding'] == 'raw':
            if size > allocation:
                raise ValueError('raw asset chunk exceeds allocation')
            plain = block[:size]
        elif chunk['encoding'] == 'raw-lzma':
            if allocation < 7:
                raise ValueError('asset LZMA allocation too small')
            encoded_size = struct.unpack_from('<H', block)[0]
            props = block[2:7]
            dictionary = struct.unpack_from('<I', props, 1)[0]
            if (encoded_size != chunk['encoded_size'] or props.hex() != chunk['properties_hex'] or
                    encoded_size + 7 > allocation or props[0] != 0x5d or
                    not 4096 <= dictionary <= 64 * 1024 * 1024):
                raise ValueError('asset LZMA recipe mismatch')
            alignment = chunk.get('alignment')
            if alignment is not None:
                alignment = number(alignment, 65536, 'chunk alignment')
                if (not alignment or alignment & (alignment - 1) or at % alignment or
                        end % alignment or
                        (at + 7 + encoded_size + alignment - 1) // alignment * alignment != end):
                    raise ValueError('asset chunk alignment mismatch')
            filters = [dict(id=lzma.FILTER_LZMA1, dict_size=dictionary, lc=3, lp=0, pb=2)]
            decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
            # IGA supplies the decoded block size externally. Original range
            # streams need not end with an LZMA end marker; decoding past that
            # size can consume padding as another symbol. The complete source
            # and the bounded decoded block both have independent hashes.
            plain = decoder.decompress(block[7:7 + encoded_size], max_length=size)
        else:
            raise ValueError('unsupported asset chunk encoding')
        if len(plain) != size or digest(plain) != chunk['decoded_sha256']:
            raise ValueError('asset decoded chunk mismatch')
        modified = edits(plain, chunk['edits'])
        if filters:
            compressed = lzma.compress(modified, format=lzma.FORMAT_RAW,
                                       filters=[dict(filters[0], mode=lzma.MODE_NORMAL,
                                                     nice_len=64, mf=lzma.MF_BT4)])
            if len(compressed) > 65535 or len(compressed) + 7 > allocation:
                raise ValueError('modified asset chunk exceeds original allocation')
            check = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
            if check.decompress(compressed, max_length=size + 1) != modified:
                raise ValueError('asset recompression verification failed')
            # Zero padding inside the declared length crashed the US 01.01 game
            # (Xbox prompt font, 2026-10-28). The archive's block table gives block
            # positions, so a short stream may be acceptable, but that was never
            # isolated (black text then came from the colour edit). Conservatively
            # the stream itself reaches the original boundary: when compression
            # shrinks it, a less efficient parse of the same bytes lengthens it.
            minimum = allocation - alignment - 6 if alignment is not None else encoded_size
            if len(compressed) < minimum:
                compressed = lzma_fill.fill(modified, dictionary, minimum, min(allocation - 7, 65535))
            replacement = struct.pack('<H', len(compressed)) + props + compressed
            output[at:end] = replacement + bytes(allocation - len(replacement))
        else:
            output[at:at + size] = modified
    result = bytes(output)
    return result, dict(source_sha256=recipe['source_sha256'], output_sha256=digest(result))


def relative_asset(value):
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or '..' in path.parts or '\\' in value or
            str(path) != value):
        raise ValueError('invalid relative mod asset path')
    return path


def combine_profiles(profiles):
    """Compose independently selected mods against their shared original bytes.

    Two mods can touch different fields of one compressed block. Decode and
    recompress that block once; never apply a second original-hash recipe to
    an archive already changed by another mod.
    """
    if not profiles:
        raise ValueError('no asset mod profiles selected')
    identity = tuple(profiles[0].get(key) for key in ('executable_sha256', 'title_id', 'app_version'))
    assets = {}
    for profile in profiles:
        if tuple(profile.get(key) for key in ('executable_sha256', 'title_id', 'app_version')) != identity:
            raise ValueError('asset mods target different game builds')
        for source in profile['assets']:
            path = str(relative_asset(source['asset']))
            target = assets.setdefault(path, dict(asset=path, source_sha256=source['source_sha256'], chunks=[]))
            if target['source_sha256'] != source['source_sha256']:
                raise ValueError('asset mods require different original assets')
            for incoming in source['chunks']:
                matching = next((chunk for chunk in target['chunks'] if chunk['offset'] == incoming['offset']), None)
                if matching is None:
                    target['chunks'].append(copy.deepcopy(incoming))
                    continue
                if ({key: value for key, value in matching.items() if key != 'edits'} !=
                        {key: value for key, value in incoming.items() if key != 'edits'}):
                    raise ValueError('asset mods disagree about a shared chunk')
                matching['edits'].extend(copy.deepcopy(incoming['edits']))
    for asset in assets.values():
        end = 0
        for chunk in sorted(asset['chunks'], key=lambda chunk: chunk['offset']):
            if chunk['offset'] < end:
                raise ValueError('asset mods overlap chunk allocations')
            end = chunk['offset'] + chunk['allocation']
            edit_end = 0
            for item in sorted(chunk['edits'], key=lambda item: item['offset']):
                at = item['offset']
                if at < edit_end:
                    raise ValueError('asset mods overlap edits')
                edit_end = at + (item['length'] if 'copy_from' in item else
                                 len(bytes.fromhex(item['expected_hex'])))
    return dict(executable_sha256=identity[0], title_id=identity[1], app_version=identity[2],
                default_enabled=False, assets=list(assets.values()))


def prepare(original_game, session_game, session, profile, *, enabled=False, cache_directory=None):
    if type(enabled) is not bool:
        raise ValueError('asset mod enabled must be boolean')
    if not enabled:
        return dict(enabled=False, assets=[])
    original_game, session_game, session = map(Path, (original_game, session_game, session))
    if digest((original_game / 'eboot.bin').read_bytes()) != profile['executable_sha256']:
        raise ValueError('asset mod refuses an unknown executable')
    root = session_game.resolve()
    source_root = original_game.resolve()
    if (session_game.is_symlink() or root != session.resolve() / 'game' or
            root.is_relative_to(source_root) or source_root.is_relative_to(root)):
        raise ValueError('asset mod requires a private session game tree')
    # Include story/expansion and challenge-map copies plus shared text.
    if not 0 < len(profile['assets']) <= 64:
        raise ValueError('invalid mod asset count')
    checked_digest = VerifiedDigests(file_digest)
    plans, seen = [], set()
    # Stage one archive at a time. Keeping all replacement bytes in plans
    # would retain several GB for game-wide profiles. A failed validation
    # cleans the staging files and leaves every target untouched.
    with tempfile.TemporaryDirectory(prefix='.asset-mod-', dir=session) as temporary:
        for recipe in profile['assets']:
            relative = relative_asset(recipe['asset'])
            if str(relative) in seen:
                raise ValueError('duplicate mod asset')
            seen.add(str(relative))
            source, target = original_game / relative, session_game / relative
            if (target.is_symlink() or target.resolve() != root / relative or
                    source.is_symlink() or source.resolve() != source_root / relative):
                raise ValueError('asset mod refuses a redirected path')
            before_read = checked_digest.stamp(source)
            data = source.read_bytes()
            source_hash = digest(data)
            checked_digest.remember(source,before_read,source_hash)
            if checked_digest(target) != source_hash:
                raise ValueError('asset mod refuses to overwrite another modification')
            staged = Path(temporary) / str(len(plans))
            if cache_directory is not None:
                try:from .asset_cache import stage
                except ImportError:from asset_cache import stage
                metadata=stage(cache_directory,data,recipe,staged,patch_asset)
            else:
                modified, metadata = patch_asset(data, recipe)
                staged.write_bytes(modified)
                del modified
            plans.append((source, target, staged, dict(metadata, asset=str(relative))))
            del data
        # Recheck all inputs before replacing any targets. Atomic rename
        # breaks a hard link without exposing an absent or half-written file.
        for source, target, staged, metadata in plans:
            if (source.is_symlink() or target.is_symlink() or
                    source.resolve() != source_root / metadata['asset'] or
                    target.resolve() != root / metadata['asset']):
                raise ValueError('asset mod refuses a redirected path')
            if checked_digest(source) != metadata['source_sha256']:
                raise ValueError('original asset changed during mod preparation')
            if checked_digest(target) != metadata['source_sha256']:
                raise ValueError('asset mod refuses to overwrite another modification')
            if checked_digest(staged) != metadata['output_sha256']:
                raise ValueError('staged asset changed during mod preparation')
        for source, target, staged, metadata in plans:
            os.replace(staged, target)
            if checked_digest(source) != metadata['source_sha256']:
                raise ValueError('original asset changed during mod preparation')
    return dict(enabled=True, assets=[plan[3] for plan in plans])

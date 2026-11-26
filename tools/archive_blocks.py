# SPDX-License-Identifier: GPL-3.0-or-later
"""Blocks of an IGA game archive, and portable edits located by content.

An archive (IGA version 0x0B, as in Trap Team) holds members stored as 32 KiB
blocks: raw LZMA with a 2-byte length and 5-byte properties, or raw bytes,
each starting on the archive's alignment. Offsets change between game builds
when an update repacks an archive, so a recipe written for one build does not
fit another.

A portable edit names bytes by content instead:

    {"find_hex": "1234??0000", "at": 3, "replacement_hex": "ffff"}
    {"find_hex": "...", "at": 8, "length": 8, "copy": {"find_hex": "...", "at": 4}}

`find_hex` is hex with `??` for bytes that differ between builds (pointers,
sizes). It must match exactly once in the archive's decoded blocks, inside one
block. The bytes it replaces must not be wildcards: they are the expected
bytes. The new value is either literal (`replacement_hex`) or copied from
another unique match in the same archive (`copy`), for values such as
pointers that differ per build. resolve() turns portable edits into the exact
chunk recipe that tools/asset_mod.py applies, so every hash and recompression
check still runs for the build that is installed. Nothing is written here.
"""
import hashlib
import lzma
import re
import struct
from pathlib import PurePosixPath

BLOCK = 0x8000
MAX_FIND = 256


def digest(data):
    return hashlib.sha256(data).hexdigest()


def members(data):
    """(name, offset, size, mode) for every archive member, and the alignment."""
    if data[:4] != b'IGA\x1a' or len(data) < 0x38:
        raise ValueError('not a game archive')
    count, align = struct.unpack_from('<II', data, 0x0C)
    table = struct.unpack_from('<Q', data, 0x28)[0]
    if not 0 < count <= 65536 or align not in (0x800, 0x1000) or table + 4 * count > len(data):
        raise ValueError('unexpected archive header')
    base = 0x38 + 4 * count
    result = []
    for i in range(count):
        start = table + struct.unpack_from('<I', data, table + 4 * i)[0]
        end = data.index(b'\0', start)
        offset, _, size, mode = struct.unpack_from('<IIII', data, base + 16 * i)
        if offset >= len(data) or size > 1 << 30:
            raise ValueError('unexpected archive member')
        result.append((data[start:end].decode('latin-1'), offset, size, mode))
    return result, align


def _lzma(dictionary):
    return [dict(id=lzma.FILTER_LZMA1, dict_size=dictionary, lc=3, lp=0, pb=2)]


def _decode(data, at, length, props, want):
    """The decoded block, or None when the bytes are not a whole LZMA block."""
    if props[:1] != b'\x5d' or not 0 < length <= BLOCK + 0x400 or at + 7 + length > len(data):
        return None
    dictionary = struct.unpack_from('<I', props, 1)[0]
    if not 4096 <= dictionary <= 64 * 1024 * 1024:
        return None
    try:
        plain = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=_lzma(dictionary)).decompress(
            data[at + 7:at + 7 + length], max_length=want)
    except lzma.LZMAError:
        return None
    return plain if len(plain) == want else None


def blocks(data, only=None):
    """Yield one dict per block: member, member_offset, the chunk recipe fields and plain bytes.

    only: a member name; other members are skipped without decoding.
    """
    table, align = members(data)
    for name, offset, size, mode in table:
        if only is not None and name != only:
            continue
        at, done = offset, 0
        while done < size:
            want = min(BLOCK, size - done)
            if mode == 0xFFFFFFFF:
                chunk = dict(offset=at, allocation=want, decoded_size=want, encoding='raw')
                plain, at = data[at:at + want], at + want
            elif mode >> 24 == 0x20:
                length = struct.unpack_from('<H', data, at)[0]
                props = data[at + 2:at + 7]
                plain = _decode(data, at, length, props, want)
                if plain is not None:
                    end = (at + 7 + length + align - 1) // align * align
                    chunk = dict(offset=at, allocation=end - at, decoded_size=want, encoding='raw-lzma',
                                 encoded_size=length, properties_hex=props.hex(), alignment=align)
                else:
                    # A stored block; its first bytes can look like an LZMA header by chance.
                    plain = data[at:at + want]
                    end = (at + BLOCK + align - 1) // align * align
                    chunk = dict(offset=at, allocation=end - at, decoded_size=want, encoding='raw')
                at = end
            else:
                raise ValueError(f'unsupported compression in archive member {name}')
            if len(plain) != want:
                raise ValueError(f'archive member {name} is truncated')
            yield dict(member=name, member_offset=done, chunk=chunk, plain=plain)
            done += want


def pattern(text, what='find_hex'):
    """(compiled regex, mask) for hex with ?? wildcards; mask[i] is False for a wildcard."""
    if not isinstance(text, str):
        raise ValueError(f'{what} must be hex text')
    compact = ''.join(text.split())
    if len(compact) % 2 or not 0 < len(compact) // 2 <= MAX_FIND:
        raise ValueError(f'{what} must hold 1..{MAX_FIND} whole bytes')
    parts, mask = [], []
    for i in range(0, len(compact), 2):
        pair = compact[i:i + 2]
        if pair == '??':
            parts.append(b'.');mask.append(False)
        else:
            try:value = bytes.fromhex(pair)
            except ValueError:raise ValueError(f'{what} has an invalid byte {pair!r}') from None
            parts.append(re.escape(value));mask.append(True)
    if not any(mask):
        raise ValueError(f'{what} needs at least one fixed byte')
    # A lookahead finds overlapping matches too, so a repeated pattern is never missed.
    return re.compile(b'(?=(' + b''.join(parts) + b'))', re.DOTALL), mask


def check_edit(edit):
    """Validate one portable edit; returns (find, mask, at, length, literal or None, copy or None)."""
    allowed = {'find_hex', 'at', 'replacement_hex', 'copy', 'length', 'member', 'note'}
    if not isinstance(edit, dict) or set(edit) - allowed:
        raise ValueError('a portable edit has unknown fields')
    find, mask = pattern(edit.get('find_hex'))
    at = edit.get('at', 0)
    if type(at) is not int or at < 0:
        raise ValueError('a portable edit needs a nonnegative at')
    if ('replacement_hex' in edit) == ('copy' in edit):
        raise ValueError('a portable edit needs exactly one of replacement_hex or copy')
    literal = copy = None
    if 'replacement_hex' in edit:
        try:literal = bytes.fromhex(edit['replacement_hex'])
        except (TypeError, ValueError):raise ValueError('replacement_hex must be hex') from None
        length = len(literal)
        if 'length' in edit and edit['length'] != length:
            raise ValueError('length disagrees with replacement_hex')
    else:
        length = edit.get('length')
        copy = edit['copy']
        if not isinstance(copy, dict) or set(copy) - {'find_hex', 'at', 'member'}:
            raise ValueError('copy needs find_hex and at')
        source, source_mask = pattern(copy.get('find_hex'), 'copy find_hex')
        start = copy.get('at', 0)
        if type(length) is not int or type(start) is not int or start < 0 or start + (length or 0) > len(source_mask):
            raise ValueError('copy must read inside its find_hex')
        copy = dict(copy, compiled=source, at=start)
    if type(length) is not int or not 0 < length or at + length > len(mask):
        raise ValueError('a portable edit must replace bytes inside its find_hex')
    if not all(mask[at:at + length]):
        raise ValueError('the bytes a portable edit replaces must not be wildcards')
    for name, value in (('member', edit.get('member')), ('copy member', (copy or {}).get('member'))):
        if value is not None and (not isinstance(value, str) or not value or len(value) > 512):
            raise ValueError(f'a portable edit has an invalid {name}')
    return find, mask, at, length, literal, copy


def _search(data, wanted):
    """For [(compiled, member or None)], every (block, offset) match, in one pass."""
    found = [[] for _ in wanted]
    for block in blocks(data):
        for index, (compiled, member) in enumerate(wanted):
            if member is None or member == block['member']:
                found[index].extend((block, match.start()) for match in compiled.finditer(block['plain']))
    return found


def _one(matches, what):
    if len(matches) != 1:
        raise ValueError(f"{what}: {'not found' if not matches else f'found {len(matches)} times'} in this build")
    return matches[0]


def locate(data, edits):
    """[(block, offset, replacement bytes)] for each edit; refuses missing or repeated matches."""
    checked = [check_edit(edit) for edit in edits]
    wanted = []
    for edit, (find, _, _, _, _, copy) in zip(edits, checked):
        wanted.append((find, edit.get('member')))
        wanted.append((copy['compiled'], copy.get('member')) if copy else (None, None))
    found = _search(data, [item for item in wanted if item[0] is not None])
    found = iter(found)
    result = []
    for index, (find, mask, at, length, literal, copy) in enumerate(checked):
        block, start = _one(next(found), f'portable edit {index}')
        if copy:
            source, offset = _one(next(found), f'portable edit {index} copy source')
            literal = source['plain'][offset + copy['at']:offset + copy['at'] + length]
        if block['plain'][start + at:start + at + length] == literal:
            raise ValueError(f'portable edit {index}: the bytes already have the new value')
        result.append((block, start, literal))
    return result


def resolve(data, asset, edits):
    """The asset_mod recipe for these portable edits against this exact archive."""
    path = PurePosixPath(asset)
    if not asset or path.is_absolute() or '..' in path.parts or '\\' in asset or str(path) != asset:
        raise ValueError('invalid archive path')
    if not edits or len(edits) > 4096:
        raise ValueError('a portable patch needs 1..4096 edits')
    chunks = {}
    for edit, (block, start, after) in zip(edits, locate(data, edits)):
        at = edit.get('at', 0)
        chunk = chunks.setdefault(block['chunk']['offset'], dict(
            block['chunk'], decoded_sha256=digest(block['plain']), edits=[]))
        chunk['edits'].append(dict(offset=start + at, expected_hex=block['plain'][start + at:start + at + len(after)].hex(),
                                   replacement_hex=after.hex()))
    for chunk in chunks.values():
        chunk['edits'].sort(key=lambda item: item['offset'])
        end = 0
        for item in chunk['edits']:
            if item['offset'] < end:
                raise ValueError('portable edits overlap')
            end = item['offset'] + len(bytes.fromhex(item['expected_hex']))
    return dict(asset=asset, source_sha256=digest(data), chunks=[chunks[key] for key in sorted(chunks)])

# SPDX-License-Identifier: GPL-3.0-or-later
"""Objects of a game data file (IGZ, as in Trap Team's level.bld), and pointer
translation between two copies of one file.

Another region's copy of a level holds the same objects in the same order,
except for a few language objects, so everything after them sits at other
offsets. Pointers inside the file are offsets into its object section. To
carry a pointer edit to the other copy, both object lists are read from the
file's own fixup table (RVTB: the start of every object), matched in order by
size and type, and a pointer into object k becomes the same place inside the
matching object of the other copy. Nothing is guessed: a pointer whose object
has no unambiguous match is refused.
"""
import bisect
import difflib
import struct

MAGIC = b'\x01ZGI'


def _chunks(data):
    """{tag: (count, payload)} of the fixup chunks at 0x800."""
    result, at = {}, 0x800
    while at + 16 <= len(data):
        tag, count, size, start = struct.unpack_from('<4sIII', data, at)
        if not size or start > size:
            break
        result[tag] = (count, data[at + start:at + size])
        if tag == b'ROOT':
            break
        at += size
    return result


def _unpack(payload, count):
    """Packed offsets: 3-bit groups with a continuation bit, low nibble first;
    each is the previous offset plus 4*(value+1)."""
    nibbles = []
    for byte in payload:
        nibbles += (byte & 15, byte >> 4)
    result, at, previous = [], 0, 0
    for index in range(count):
        value = shift = 0
        while True:
            if at >= len(nibbles):
                raise ValueError('truncated object table')
            nibble = nibbles[at];at += 1
            value |= (nibble & 7) << shift;shift += 3
            if not nibble & 8:
                break
        previous += value * 4 + 4
        result.append(previous)
    return result


def pointer_fields(data):
    """Object-section offsets of every pointer field (the ROFS fixup table)."""
    start, size = struct.unpack_from('<II', data, 0x28)
    chunks = _chunks(data)
    if b'ROFS' not in chunks:
        raise ValueError('game data file without a pointer table')
    return {offset for offset in _unpack(*reversed(chunks[b'ROFS'])) if offset < size}


def objects(data):
    """(object section start, [(offset, size, type)]) for an IGZ file."""
    if data[:4] != MAGIC:
        raise ValueError('not a game data file')
    start, size = struct.unpack_from('<II', data, 0x28)
    chunks = _chunks(data)
    if b'RVTB' not in chunks or start + size > len(data):
        raise ValueError('game data file without an object table')
    offsets = [offset for offset in _unpack(*reversed(chunks[b'RVTB'])) if offset < size]
    if offsets != sorted(offsets) or not offsets:
        raise ValueError('unexpected object table')
    ends = offsets[1:] + [size]
    return start, [(offset, end - offset, struct.unpack_from('<Q', data, start + offset)[0])
                   for offset, end in zip(offsets, ends)]


class Translator:
    """Maps object-section offsets of one copy of a file to another copy."""

    def __init__(self, source, target):
        self.source_start, self.source = objects(source)
        self.target_start, self.target = objects(target)
        self.pointers = pointer_fields(source)
        self.target_pointers = pointer_fields(target)
        self.starts = [offset for offset, _, _ in self.source]
        keys = lambda items: [(size, kind) for _, size, kind in items]
        matcher = difflib.SequenceMatcher(None, keys(self.source), keys(self.target), autojunk=False)
        self.match = {}
        for a, b, length in matcher.get_matching_blocks():
            for k in range(length):
                self.match[a + k] = b + k

    def __call__(self, value):
        """The other copy's offset for value, or None when its object has no match."""
        k = bisect.bisect_right(self.starts, value) - 1
        if k < 0:
            return None
        offset, size, _ = self.source[k]
        if not 0 <= value - offset < size or k not in self.match:
            return None
        return self.target[self.match[k]][0] + value - offset


def _pack(offsets):
    """The packed offset format _unpack reads."""
    nibbles, previous = [], 0
    for offset in offsets:
        value = (offset - previous) // 4 - 1
        if value < 0 or (offset - previous) % 4:
            raise ValueError('offsets out of order')
        previous = offset
        while True:
            part, value = value & 7, value >> 3
            nibbles.append(part | (8 if value else 0))
            if not value:
                break
    if len(nibbles) % 2:
        nibbles.append(0)
    return bytes(nibbles[i] | nibbles[i + 1] << 4 for i in range(0, len(nibbles), 2))


def _strings(payload, count):
    """The string table: NUL-terminated strings, each padded to an even length."""
    result, at = [], 0
    for _ in range(count):
        end = payload.index(b'\0', at)
        result.append(payload[at:end])
        at = end + 1 + (end + 1 - at) % 2
    if any(payload[at:]):
        raise ValueError('unexpected string table')
    return result


def _encode_strings(strings):
    return b''.join(text + b'\0' * (2 - len(text) % 2) for text in strings)


def _layout(data):
    """[(tag, count, payload)] of the fixup chunks, refused unless they end
    exactly where the object section starts."""
    result, at = [], 0x800
    while True:
        tag, count, size, start = struct.unpack_from('<4sIII', data, at)
        if start < 16 or size < start or size % 4:
            raise ValueError('unexpected fixup chunk')
        # Bytes between the 16-byte chunk header and the payload are kept as they are.
        result.append((tag, count, data[at + 16:at + start], data[at + start:at + size]))
        at += size
        if tag == b'ROOT':
            break
    if at != struct.unpack_from('<I', data, 0x28)[0]:
        raise ValueError('fixup chunks do not reach the object section')
    return result


OFFSET_LISTS = {b'RVTB', b'RSTT', b'ROFS', b'RPID', b'REXT', b'RHND', b'RNEX', b'RMHN'}


def _renamed(strings, rename):
    result = list(strings)
    for old, new in rename.items():
        if result.count(old) != 1 or new in result:
            raise ValueError(f'string {old!r} is not in the other copy once')
        result[result.index(old)] = new
    return result


def there_sizes(data):
    """[(tag, chunk size)] of the fixup chunks."""
    result, at = [], 0x800
    while True:
        tag, _, size, _ = struct.unpack_from('<4sIII', data, at)
        result.append((tag, size));at += size
        if tag == b'ROOT':
            return result


def port_fixups(original, edited, target, translate, rename=None):
    """The target's header and fixup chunks with the edit's fixup changes carried over.

    An edit that adds or retargets pointers changes the file's fixup lists
    (which fields hold pointers, external references and so on) and may rename
    strings. Each list is decoded in both copies of the source; every added or
    removed entry in the object section is translated to the other copy by
    object and applied to that copy's own list. A string replaced in place is
    replaced at the matching place of the other copy's table. The string table's
    zero padding absorbs size changes so the object section does not move.
    Returns bytes for target[:object section start]; anything else changed in
    the fixups is refused.

    rename: {old: new} strings of the other copy to shorten when its tables are
    full, such as a developer's source path (C:/tfb/...) the game never opens."""
    if original[:0x800] != edited[:0x800]:
        raise ValueError('the edit changes the file header')
    size = struct.unpack_from('<I', original, 0x2c)[0]
    target_size = struct.unpack_from('<I', target, 0x2c)[0]
    old, new, there = _layout(original), _layout(edited), _layout(target)
    if [c[0] for c in old] != [c[0] for c in new] or [c[0] for c in old] != [c[0] for c in there]:
        raise ValueError('the fixup chunks differ')
    built = []
    for (tag, count, extra, payload), (_, new_count, new_extra, new_payload), (_, t_count, t_extra, t_payload) \
            in zip(old, new, there):
        if extra != new_extra:
            raise ValueError(f'the edit changes {tag.decode()}')
        if (count, payload.rstrip(b'\0')) == (new_count, new_payload.rstrip(b'\0')):
            # Unchanged, or only zero padding added (the edit's own room). Zero
            # padding after the payload is room for the other changes.
            if tag in OFFSET_LISTS:
                packed = _pack(_unpack(t_payload, t_count))
                if t_payload.rstrip(b'\0') == packed.rstrip(b'\0'):
                    t_payload = packed
            if tag == b'TSTR' and rename:
                t_payload = _encode_strings(_renamed(_strings(t_payload, t_count), rename))
            built.append((tag, t_count, t_extra, t_payload))
        elif tag in OFFSET_LISTS:
            a, b = _unpack(payload, count), _unpack(new_payload, new_count)
            mine = _unpack(t_payload, t_count)
            if _pack(mine) != t_payload[:len(_pack(mine))]:
                raise ValueError(f'{tag.decode()} does not re-encode')
            if [x for x in a if x >= size] != [x for x in b if x >= size]:
                raise ValueError(f'{tag.decode()} changes outside the object section')
            result = set(mine)
            for value, add in [(x, False) for x in set(a) - set(b)] + [(x, True) for x in set(b) - set(a)]:
                place = translate(value)
                if place is None or (place in result) == add:
                    raise ValueError(f'{tag.decode()} entry {value} has no match in the other copy')
                (result.add if add else result.discard)(place)
            inside = sorted(x for x in result if x < target_size)
            built.append((tag, len(result), t_extra, _pack(inside + [x for x in mine if x >= target_size])))
        elif tag == b'TSTR' and count == new_count:
            a, b, mine = _strings(payload, count), _strings(new_payload, count), _strings(t_payload, t_count)
            matcher = difflib.SequenceMatcher(None, a, mine, autojunk=False)
            where = {}
            for i, j, length in matcher.get_matching_blocks():
                where.update((i + k, j + k) for k in range(length))
            for index, (before, after) in enumerate(zip(a, b)):
                if before != after:
                    if index not in where or mine[where[index]] != before:
                        raise ValueError(f'string {before!r} has no match in the other copy')
                    mine[where[index]] = after
            built.append((tag, t_count, t_extra, _encode_strings(_renamed(mine, rename or {}))))
        else:
            raise ValueError(f'the edit changes {tag.decode()}')
    least = [(16 + len(extra) + len(payload) + 3) // 4 * 4 for _, _, extra, payload in built]
    room = struct.unpack_from('<I', target, 0x28)[0] - 0x800 - sum(least)
    if room < 0 or room % 4:
        raise ValueError(f'the fixups do not fit in the other copy ({-room} bytes short)')
    # Each chunk keeps its size where it fits, so the chunks after it stay in place;
    # a chunk that grows takes the room from the nearest chunks' zero padding.
    sizes = [max(low, size) for low, size in zip(least, [c[1] for c in there_sizes(target)])]
    excess = sum(sizes) - sum(least) - room
    for i in reversed(range(len(sizes))):
        if excess <= 0:
            break
        take = min(excess, sizes[i] - least[i])
        sizes[i] -= take;excess -= take
    if excess < 0:
        sizes[-1] -= excess
    result = bytearray(target[:0x800])
    for (tag, count, extra, payload), chunk_size in zip(built, sizes):
        start = 16 + len(extra)
        result += struct.pack('<4sIII', tag, count, chunk_size, start) + extra + payload + bytes(chunk_size - start - len(payload))
    return bytes(result)

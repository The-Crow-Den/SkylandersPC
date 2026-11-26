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

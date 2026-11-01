#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only function-boundary evidence from ELF/SELF unwind metadata.

This never authorizes rewriting: unwind tables may omit leaf/assembly functions.
Uncovered executable bytes remain unknown, not presumed padding or data.
Encoding facts: ELF .eh_frame_hdr and DWARF CIE/FDE records, also described by
https://github.com/llvm/llvm-project/blob/main/libunwind/src/EHHeaderParser.hpp
No reference implementation is incorporated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

try:
    from . import executable
except ImportError:
    import executable


def _leb(data, pos, signed=False):
    value = shift = 0
    for _ in range(10):
        byte = executable.take(data, pos, 1)[0]
        pos += 1
        value |= (byte & 127) << shift
        shift += 7
        if not byte & 128:
            if signed and byte & 64:
                value -= 1 << shift
            if not (-(1 << 63) <= value < (1 << 63) if signed else 0 <= value < (1 << 64)):
                raise ValueError('unwind LEB integer overflow')
            return value, pos
    raise ValueError('unterminated/oversized unwind LEB integer')


def _record(image, address):
    length = executable.unpack('<I', image.virtual(address, 4))[0]
    if length < 4 or length > executable.MAX_TABLE:
        raise ValueError('unsupported unwind record length')
    return image.virtual(address + 4, length)


def _cie_encoding(record):
    if executable.unpack('<I', record)[0] != 0:
        raise ValueError('unwind CIE identifier is not zero')
    version = executable.take(record, 4, 1)[0]
    if version not in (1, 3):
        raise ValueError('unsupported unwind CIE version')
    end = record.find(b'\0', 5)
    if end < 0:
        raise ValueError('unterminated unwind augmentation')
    augmentation = record[5:end]
    if not augmentation.startswith(b'z') or len(set(augmentation)) != len(augmentation):
        raise ValueError('unsupported unwind augmentation')
    align, pos = _leb(record, end + 1)
    _, pos = _leb(record, pos, signed=True)
    if not align:
        raise ValueError('zero unwind code alignment')
    if version == 1:
        executable.take(record, pos, 1)
        pos += 1
    else:
        _, pos = _leb(record, pos)
    size, pos = _leb(record, pos)
    extra = executable.take(record, pos, size)
    cursor, encoding = 0, 0
    for letter in augmentation[1:]:
        if letter == ord('S'):
            continue
        if letter not in b'LRP':
            raise ValueError('unsupported unwind augmentation field')
        field = executable.take(extra, cursor, 1)[0]
        cursor += 1
        if letter == ord('R'):
            encoding = field
        elif letter == ord('P'):
            # Personality value is not dereferenced; only its encoded width is
            # needed to reach R. Omitted/aligned/variable-width forms refuse.
            width = {0: 8, 3: 4, 4: 8, 11: 4, 12: 8}.get(field & 15)
            if width is None or field & 0x70 not in (0, 0x10, 0x30):
                raise ValueError('unsupported unwind personality encoding')
            executable.take(extra, cursor, width)
            cursor += width
    if cursor != len(extra) or encoding not in (0, 0x1b):
        raise ValueError('unsupported unwind FDE pointer encoding')
    return encoding


def discover(data, expected_sha256):
    """Return bounded metadata evidence, refusing hash or structural mismatches."""
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('expected executable SHA-256 is required')
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError('executable hash mismatch before unwind inspection')
    image = executable.Image(data)
    headers = [p for p in image.programs if p['type'] == 0x6474e550]
    if len(headers) != 1:
        raise ValueError('requires exactly one PT_GNU_EH_FRAME header')
    header = headers[0]
    raw = image.read(header['offset'], header['filesz'])
    if executable.take(raw, 0, 4) != b'\x01\x1b\x03\x3b':
        raise ValueError('unsupported unwind header encodings')
    frame = header['vaddr'] + 4 + executable.unpack('<i', raw, 4)[0]
    count = executable.unpack('<I', raw, 8)[0]
    if not 0 < count <= executable.MAX_TABLE or frame < 0 or frame >= header['vaddr']:
        raise ValueError('invalid unwind frame address/count')
    executable.take(raw, 12, count * 8)
    loads = sorted((p for p in image.programs if p['type'] == 1 and p['flags'] & 1 and p['filesz']),
                   key=lambda p: p['vaddr'])
    for a, b in zip(loads, loads[1:]):
        if a['vaddr'] + a['filesz'] > b['vaddr']:
            raise ValueError('overlapping executable segments')
    ranges, cache, seen = [], {}, set()
    for index in range(count):
        relative_pc, relative_fde = executable.unpack('<ii', raw, 12 + index * 8)
        pc, fde = header['vaddr'] + relative_pc, header['vaddr'] + relative_fde
        if not frame <= fde < header['vaddr'] or fde in seen:
            raise ValueError('unwind FDE address outside frame area or duplicated')
        record = _record(image, fde)
        if fde + 4 + len(record) > header['vaddr']:
            raise ValueError('unwind FDE crosses header')
        seen.add(fde)
        cie_delta = executable.unpack('<I', record)[0]
        cie = fde + 4 - cie_delta
        if not frame <= cie < fde:
            raise ValueError('unwind CIE back-reference is invalid')
        if cie not in cache:
            cie_record = _record(image, cie)
            if cie + 4 + len(cie_record) > fde:
                raise ValueError('unwind CIE overlaps referring FDE')
            cache[cie] = _cie_encoding(cie_record)
        encoding = cache[cie]
        if encoding == 0x1b:
            delta, size = executable.unpack('<ii', record, 4)
            start, cursor = fde + 8 + delta, 12
        else:
            start, size = executable.unpack('<QQ', record, 4)
            cursor = 20
        extra_size, cursor = _leb(record, cursor)
        executable.take(record, cursor, extra_size)
        if start != pc or size <= 0 or start < 0 or start + size > 1 << 64:
            raise ValueError('unwind function range/table mismatch')
        matches = [p for p in loads if p['vaddr'] <= start and start + size <= p['vaddr'] + p['filesz']]
        if len(matches) != 1 or (ranges and ranges[-1]['address'] + ranges[-1]['size'] > start):
            raise ValueError('unwind function outside executable bytes or overlaps prior function')
        p = matches[0]
        logical = p['offset'] + start - p['vaddr']
        physical = logical
        if image.regions is not None:
            mappings = [r for r in image.regions if r[0] <= logical and logical + size <= r[0] + r[1]]
            if len(mappings) != 1:
                raise ValueError('unwind function SELF mapping is ambiguous')
            begin, _, source = mappings[0]
            physical = source + logical - begin
        ranges.append({'address': start, 'size': size, 'file_offset': physical})
    uncovered = []
    index = 0
    for p in loads:
        cursor, end = p['vaddr'], p['vaddr'] + p['filesz']
        while index < len(ranges) and ranges[index]['address'] < end:
            item = ranges[index]
            if cursor < item['address']:
                uncovered.append({'address': cursor, 'size': item['address'] - cursor})
            cursor = item['address'] + item['size']
            index += 1
        if cursor < end:
            uncovered.append({'address': cursor, 'size': end - cursor})
    return {'executable_sha256': digest, 'source': 'unwind function metadata',
            'rewrite_authorized': False, 'function_ranges': ranges, 'uncovered_ranges': uncovered}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    if args.executable.stat().st_size > executable.MAX_FILE:
        parser.error('executable exceeds inspection limit')
    try:
        with args.executable.open('rb') as stream:
            data = stream.read(executable.MAX_FILE + 1)
        if len(data) > executable.MAX_FILE:
            parser.error('executable exceeds inspection limit')
        report = discover(data, args.expected_sha256)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

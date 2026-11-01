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
    from . import executable, audit_imports, link_native, module_graph
except ImportError:
    import executable, audit_imports, link_native, module_graph


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


def _verified_image(data, expected_sha256):
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('expected executable SHA-256 is required')
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError('executable hash mismatch before unwind inspection')
    return executable.Image(data), digest


def discover(data, expected_sha256):
    """Return bounded metadata evidence, refusing hash or structural mismatches."""
    image, digest = _verified_image(data, expected_sha256)
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
    table_size = 12 + count * 8
    if table_size > header['memsz'] or image.virtual(header['vaddr'], table_size) != raw[:table_size]:
        raise ValueError('unwind header file/virtual mappings disagree')
    metadata = [(header['vaddr'], table_size, 'unwind')]
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
        metadata.append((fde, len(record) + 4, 'unwind'))
        cie_delta = executable.unpack('<I', record)[0]
        cie = fde + 4 - cie_delta
        if not frame <= cie < fde:
            raise ValueError('unwind CIE back-reference is invalid')
        if cie not in cache:
            cie_record = _record(image, cie)
            if cie + 4 + len(cie_record) > fde:
                raise ValueError('unwind CIE overlaps referring FDE')
            cache[cie] = _cie_encoding(cie_record)
            metadata.append((cie, len(cie_record) + 4, 'unwind'))
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
    for program in image.programs:
        if program['type'] != 3:
            continue
        size = program['filesz']
        if not 0 < size <= 4096 or size > program['memsz']:
            raise ValueError('invalid interpreter metadata extent')
        text = image.read(program['offset'], size)
        if text[-1] != 0 or b'\0' in text[:-1] or image.virtual(program['vaddr'], size) != text:
            raise ValueError('invalid interpreter metadata mapping/string')
        metadata.append((program['vaddr'], size, 'interpreter'))
    merged = []
    for address, size, kind in sorted(metadata):
        if merged and address < merged[-1]['address'] + merged[-1]['size']:
            raise ValueError('typed metadata records overlap')
        elif merged and kind == merged[-1]['kind'] and address == merged[-1]['address'] + merged[-1]['size']:
            merged[-1]['size'] += size
        else:
            merged.append({'address': address, 'size': size, 'kind': kind})
    index = 0
    for item in ranges:
        while index < len(merged) and merged[index]['address'] + merged[index]['size'] <= item['address']:
            index += 1
        if index < len(merged) and merged[index]['address'] < item['address'] + item['size']:
            raise ValueError('unwind function overlaps typed metadata')
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
            'rewrite_authorized': False, 'function_ranges': ranges, 'uncovered_ranges': uncovered,
            'metadata_ranges': merged}


def nonreturning_import_thunks(data, expected_sha256):
    """Identify exact compiler stack-failure imports for diagnostic CFG evidence.

    __stack_chk_fail has a nonreturning compiler ABI contract (for example,
    glibc debug/stack_chk_fail.c). Match its exact scoped NID, function type and
    JUMP_SLOT relocation, then verify an unconditional RIP-relative import JMP.
    No other calls are guessed to be nonreturning. Output is not patch authority.
    """
    image, _ = _verified_image(data, expected_sha256)
    one, blob, _ = link_native.dynamic_tables(image)
    imports = {s['index']: s for s in module_graph.analyze_bytes(data, 'main')['imports']}
    identity = audit_imports.nid('__stack_chk_fail') + '#libkernel#libkernel'
    slots = set()
    for offset_tag, size_tag in ((0x6100002F, 0x61000031), (0x61000029, 0x6100002D)):
        offset, size = one(offset_tag), one(size_tag)
        if offset is None and size is None:
            continue
        if offset is None or size is None or size % 24 or one(0x61000033, 24) != 24:
            raise ValueError('invalid nonreturning-import relocation table')
        table = executable.take(blob, offset, size)
        for position in range(0, size, 24):
            target, info, addend = executable.unpack('<QQq', table, position)
            symbol = imports.get(info >> 32)
            if (info & 0xffffffff) != 7 or addend or not symbol or symbol['name'] != identity:
                continue
            if symbol['type'] not in (0, 2) or symbol['binding'] not in (1, 2):
                raise ValueError('nonreturning import is not a function declaration')
            if target in slots or not any(p['type'] == 1 and p['vaddr'] <= target and
                    target + 8 <= p['vaddr'] + p['memsz'] for p in image.programs):
                raise ValueError('duplicate/unmapped nonreturning import slot')
            slots.add(target)
    result = []
    for p in image.programs:
        if p['type'] != 1 or not p['flags'] & 1 or not p['filesz']:
            continue
        code = image.read(p['offset'], p['filesz'])
        position = 0
        while True:
            position = code.find(b'\xff\x25', position)
            if position < 0:
                break
            if position + 6 <= len(code):
                pc = p['vaddr'] + position
                slot = pc + 6 + executable.unpack('<i', code, position + 2)[0]
                if slot in slots:
                    result.append({'address': pc, 'slot_address': slot, 'import': identity,
                                   'expected_bytes_hex': code[position:position + 6].hex()})
            position += 1
    return sorted(result, key=lambda item: item['address'])


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

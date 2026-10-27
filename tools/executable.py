#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, read-only ELF64/PS4 plaintext SELF metadata inspection.

This is an inspector, not a loader. It neither decrypts nor executes input and
does not claim runtime symbol resolution. Format facts: ELF gABI and PS4 SCE
dynamic-table conventions used by the supplied compatibility references.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

MAX_FILE = 512 * 1024 * 1024
MAX_TABLE = 1_000_000
PT_LOAD, PT_DYNAMIC, PT_SCE_DYNLIBDATA = 1, 2, 0x61000000


class UnsupportedExecutable(ValueError):
    """Recognized container whose payload this read-only inspector cannot read."""


def take(data, offset, size):
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ValueError('executable metadata range outside available bytes')
    return data[offset:offset + size]


def unpack(fmt, data, offset=0):
    return struct.unpack(fmt, take(data, offset, struct.calcsize(fmt)))


def terminated(data, offset):
    take(data, offset, 1)
    end = data.find(b'\0', offset)
    if end < 0:
        raise ValueError('unterminated symbol/library string')
    return data[offset:end].decode('utf-8', errors='strict')


class Image:
    def __init__(self, data):
        if len(data) > MAX_FILE:
            raise ValueError('executable exceeds 512 MiB inspection limit')
        self.data = data
        self.regions = None
        self.container = 'ELF64'
        if data[:4] == b'O\x15=\x1d':
            self.container = 'PS4 SELF (plaintext segments)'
            count = unpack('<H', data, 24)[0]
            if not 0 < count <= 4096:
                raise ValueError('unsupported SELF segment count')
            base = 32 + count * 32
            take(data, 32, count * 32)
        elif data[:4] == b'\x7fELF':
            base, count = 0, 0
        else:
            raise ValueError('expected ELF or PS4 SELF signature')
        header = unpack('<16sHHIQQQIHHHHHH', data, base)
        if header[0][:7] != b'\x7fELF\x02\x01\x01' or header[2] != 62 or header[3] != 1:
            raise ValueError('expected ELF64 little-endian x86-64 version 1')
        self.entry, phoff, shoff = header[4:7]
        if header[8] != 64 or header[9] != 56 or header[10] > 4096:
            raise ValueError('unsupported ELF/program-header layout')
        self.programs = []
        for i in range(header[10]):
            values = unpack('<II6Q', data, base + phoff + i * 56)
            p = dict(zip(('type', 'flags', 'offset', 'vaddr', 'paddr', 'filesz', 'memsz', 'align'), values))
            if p['vaddr'] + p['memsz'] > 1 << 64 or p['offset'] + p['filesz'] > MAX_FILE:
                raise ValueError('segment address/file range exceeds inspection limits')
            if p['type'] in (PT_LOAD, 0x61000010) and p['filesz'] > p['memsz']:
                raise ValueError('load segment file size exceeds memory size')
            self.programs.append(p)
        if count:
            header_size = max(64, phoff + header[10] * 56)
            take(data, base, header_size)
            self.regions = []
            indices = set()
            for i in range(count):
                flags, source, size, memory_size = unpack('<4Q', data, 32 + i * 32)
                if not flags & 0x800:
                    continue
                if flags & 0xA:
                    raise UnsupportedExecutable('encrypted/compressed SELF payload is unsupported; no decryption attempted')
                index = (flags >> 20) & 0xFFF
                if index >= len(self.programs) or index in indices:
                    raise ValueError('invalid/duplicate SELF program-header mapping')
                indices.add(index)
                p = self.programs[index]
                if size != memory_size or size != p['filesz']:
                    raise UnsupportedExecutable('blocked/partial SELF segment layout is unsupported')
                take(data, source, size)
                self.regions.append((p['offset'], size, source))
            ordered = sorted((r for r in self.regions if r[1]))
            for left, right in zip(ordered, ordered[1:]):
                if left[0] + left[1] > right[0]:
                    raise ValueError('overlapping SELF payload mappings')
            # ELF header/program headers are embedded independently of payloads.
            self.regions.append((0, header_size, base))
        self.unavailable_program_headers = []
        for index, p in enumerate(self.programs):
            if p['filesz']:
                try:
                    self.read(p['offset'], p['filesz'])
                except ValueError:
                    if p['type'] in (PT_LOAD, PT_DYNAMIC, PT_SCE_DYNLIBDATA):
                        raise
                    self.unavailable_program_headers.append(index)
        self.sections = []
        if header[12]:
            if header[11] != 64 or header[12] > 4096:
                raise ValueError('unsupported ELF section-header layout')
            for i in range(header[12]):
                self.sections.append(unpack('<II4QII2Q', self.read(shoff + i * 64, 64)))
        elif shoff:
            raise ValueError('extended section counts are unsupported')

    def read(self, offset, size):
        if self.regions is None:
            return take(self.data, offset, size)
        for begin, length, source in self.regions:
            if begin <= offset and offset + size <= begin + length:
                return take(self.data, source + offset - begin, size)
        raise ValueError('SELF does not contain the requested plaintext ELF range')

    def virtual(self, address, size):
        matches = [p for p in self.programs if p['type'] == PT_LOAD and
                   p['vaddr'] <= address and address + size <= p['vaddr'] + p['filesz']]
        if len(matches) != 1:
            raise ValueError('dynamic virtual range is unmapped or ambiguous')
        p = matches[0]
        return self.read(p['offset'] + address - p['vaddr'], size)


def symbols(table, strings, entry_size):
    if entry_size != 24 or len(table) % 24 or len(table) // 24 > MAX_TABLE:
        raise ValueError('unsupported dynamic symbol table layout')
    result = []
    for index in range(len(table) // 24):
        name, info, other, section, value, size = unpack('<IBBHQQ', table, index * 24)
        text = terminated(strings, name)
        if section == 0 and text:
            parts = text.split('#')
            result.append({'symbol_index': index, 'name': text, 'binding': info >> 4,
                           'type': info & 15, 'weak': info >> 4 == 2,
                           'nid': parts[0] if len(parts) == 3 else None,
                           'library_id_encoded': parts[1] if len(parts) == 3 else None,
                           'module_id_encoded': parts[2] if len(parts) == 3 else None,
                           'resolution': 'not checked'})
    return result


def inspect_bytes(data):
    image = Image(data)
    dynamic = [p for p in image.programs if p['type'] == PT_DYNAMIC]
    if len(dynamic) > 1:
        raise ValueError('multiple dynamic segments are unsupported')
    tags = {}
    if dynamic:
        p = dynamic[0]
        if p['filesz'] % 16 or p['filesz'] // 16 > MAX_TABLE:
            raise ValueError('invalid dynamic table size')
        raw = image.read(p['offset'], p['filesz'])
        ended = False
        for pos in range(0, len(raw), 16):
            tag, value = unpack('<QQ', raw, pos)
            if tag == 0:
                ended = True
                break
            tags.setdefault(tag, []).append(value)
        if not ended:
            raise ValueError('dynamic table lacks DT_NULL terminator')

    def one(tag, default=None):
        values = tags.get(tag, [])
        if len(values) > 1:
            raise ValueError(f'duplicate singleton dynamic tag {tag:#x}')
        return values[0] if values else default

    imported, libraries, source = [], [], 'no import table present'
    sce_tags = (0x61000035, 0x61000037, 0x61000039, 0x6100003B, 0x6100003F)
    if any(t in tags for t in sce_tags):
        if not all(t in tags for t in sce_tags):
            raise ValueError('incomplete SCE import-table metadata')
        blobs = [p for p in image.programs if p['type'] == PT_SCE_DYNLIBDATA]
        if len(blobs) != 1:
            raise ValueError('expected one SCE dynamic-library segment')
        blob = image.read(blobs[0]['offset'], blobs[0]['filesz'])
        strings = take(blob, one(sce_tags[0]), one(sce_tags[1]))
        table = take(blob, one(sce_tags[2]), one(sce_tags[4]))
        imported = symbols(table, strings, one(sce_tags[3]))
        for tag, kind in ((0x6100000F, 'module'), (0x61000015, 'library')):
            for value in tags.get(tag, []):
                libraries.append({'kind': kind, 'name': terminated(strings, value & 0xFFFFFFFF),
                                  'id': value >> 48, 'version_raw': (value >> 32) & 0xFFFF})
        source = 'SCE dynamic symbol table'
    else:
        for section in image.sections:
            # SHT_DYNSYM, linked SHT_STRTAB; do not infer table sizes from addresses.
            if section[1] != 11:
                continue
            link = section[6]
            if link >= len(image.sections) or image.sections[link][1] != 3:
                raise ValueError('dynamic symbol table has invalid string-table link')
            strings_section = image.sections[link]
            imported.extend(symbols(image.read(section[4], section[5]),
                                    image.read(strings_section[4], strings_section[5]), section[9]))
            source = 'ELF dynamic symbol sections'
        if source == 'no import table present' and any(t in tags for t in (5, 6)):
            source = 'unsupported stripped generic ELF symbol layout; imports not inspected'
    return {'schema_version': 1, 'sha256': hashlib.sha256(data).hexdigest(),
            'container': image.container, 'architecture': 'x86-64', 'entry': hex(image.entry),
            'program_headers': image.programs,
            'unavailable_program_headers': image.unavailable_program_headers,
            'imports': {'status': source, 'count': len(imported), 'symbols': imported,
                        'libraries': libraries, 'runtime_resolution': 'not checked'},
            'limitations': ['Read-only metadata inspection; no decryption or execution.',
                            'Undefined symbols are declarations, not evidence of reached calls.',
                            'Relocations and instruction semantics are not validated.']}


def inspect(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('executable exceeds 512 MiB inspection limit')
    return inspect_bytes(path.read_bytes())


inspect_path = inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.executable), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)

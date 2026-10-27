#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare a private native-host image from readable PS4 ELF/SELF data.

This serializes game-derived bytes only under ignored out/. It performs no
decryption, game execution, module linking or automatic import implementation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys

try:
    from . import executable
except ImportError:
    import executable

ROOT = Path(__file__).resolve().parents[1]
MAGIC = b'SKYPS401'
IMPORT_BIT = 1 << 63
HEADER = struct.Struct('<8s6Q')
SEGMENT = struct.Struct('<5Q')
RELOCATION = struct.Struct('<QQQq')
IMPORT_SIZE = 128
MAX_IMAGE = 512 * 1024 * 1024
ID_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-'


def scope_id(text):
    if not text or len(text) > 3:
        raise ValueError('invalid encoded PS4 scope ID')
    value = 0
    for character in text:
        if character not in ID_ALPHABET:
            raise ValueError('invalid encoded PS4 scope character')
        value = value * 64 + ID_ALPHABET.index(character)
    if value > 0xFFFF:
        raise ValueError('encoded PS4 scope ID exceeds descriptor width')
    return value


def build_pack(data):
    """Return (pack bytes, metadata) without writing or executing anything."""
    image = executable.Image(data)
    loads = sorted((p for p in image.programs if p['type'] in (1, 0x61000010) and p['memsz']),
                   key=lambda p: p['vaddr'])
    if not loads:
        raise ValueError('native image requires at least one nonempty load segment')
    for left, right in zip(loads, loads[1:]):
        if left['vaddr'] + left['memsz'] > right['vaddr']:
            raise ValueError('native load segments overlap')
    base = loads[0]['vaddr'] & ~4095
    end = (max(p['vaddr'] + p['memsz'] for p in loads) + 4095) & ~4095
    if end > 1 << 64 or not 0 < end - base <= MAX_IMAGE:
        raise ValueError('native virtual image exceeds 512 MiB span limit')
    if not any(p['flags'] & 1 and p['vaddr'] <= image.entry < p['vaddr'] + p['filesz'] for p in loads):
        raise ValueError('entry point is not in file-backed executable memory')

    def mapped(address, length=8):
        return any(p['vaddr'] <= address and address + length <= p['vaddr'] + p['memsz'] for p in loads)

    dynamic = [p for p in image.programs if p['type'] == 2]
    if len(dynamic) > 1:
        raise ValueError('multiple dynamic segments are unsupported')
    tags = {}
    if dynamic:
        p = dynamic[0]
        if p['filesz'] % 16 or p['filesz'] // 16 > executable.MAX_TABLE:
            raise ValueError('invalid dynamic-table size')
        table = image.read(p['offset'], p['filesz'])
        terminated = False
        for offset in range(0, len(table), 16):
            tag, value = executable.unpack('<QQ', table, offset)
            if tag == 0:
                terminated = True
                break
            tags.setdefault(tag, []).append(value)
        if not terminated:
            raise ValueError('dynamic table lacks DT_NULL')

    def one(tag, default=None):
        values = tags.get(tag, [])
        if len(values) > 1:
            raise ValueError(f'duplicate native dynamic tag {tag:#x}')
        return values[0] if values else default

    if any(t in tags for t in (2, 5, 6, 7, 8, 9, 17, 18, 19, 23)):
        raise ValueError('generic ELF dynamic linking is not supported by this PS4 pack preparer')
    sce = any(0x61000000 <= tag <= 0x6100003F for tag in tags)
    blob, symbol_rows, strings = b'', [], b''
    if sce:
        required = (0x61000035, 0x61000037, 0x61000039, 0x6100003B, 0x6100003F)
        if not all(t in tags for t in required):
            raise ValueError('incomplete SCE symbol metadata')
        segments = [p for p in image.programs if p['type'] == 0x61000000]
        if len(segments) != 1:
            raise ValueError('expected one SCE dynamic-library data segment')
        blob = image.read(segments[0]['offset'], segments[0]['filesz'])
        strings = executable.take(blob, one(0x61000035), one(0x61000037))
        symbols = executable.take(blob, one(0x61000039), one(0x6100003F))
        if one(0x6100003B) != 24 or len(symbols) % 24 or len(symbols) // 24 > executable.MAX_TABLE:
            raise ValueError('unsupported SCE symbol-table entry size')
        for offset in range(0, len(symbols), 24):
            symbol_rows.append(executable.unpack('<IBBHQQ', symbols, offset))

    scope_maps = {}
    for tag, kind in ((0x6100000F, 'module'), (0x61000015, 'library')):
        names = {}
        for descriptor in tags.get(tag, []):
            name = executable.terminated(strings, descriptor & 0xFFFFFFFF)
            identifier = descriptor >> 48
            if not name or '#' in name:
                raise ValueError(f'invalid {kind} descriptor name')
            if identifier in names and names[identifier] != name:
                raise ValueError(f'ambiguous {kind} scope descriptor')
            names[identifier] = name
        scope_maps[kind] = names

    imports, import_indices, import_details, relocations = [], {}, [], []
    table_ranges = []
    for offset_tag, size_tag in ((0x6100002F, 0x61000031), (0x61000029, 0x6100002D)):
        offset, size = one(offset_tag), one(size_tag)
        if offset is None and size is None:
            continue
        if offset is None or size is None:
            raise ValueError('incomplete SCE relocation metadata')
        if not sce or one(0x61000033, 24) != 24 or size % 24 or size // 24 > executable.MAX_TABLE:
            raise ValueError('unsupported SCE relocation table layout')
        if size:
            table_ranges.append((offset, offset + size))
        table = executable.take(blob, offset, size)
        for position in range(0, len(table), 24):
            target, info, addend = executable.unpack('<QQq', table, position)
            kind, symbol_index = info & 0xFFFFFFFF, info >> 32
            if kind == 0:
                continue
            if kind not in (1, 6, 7, 8):
                raise ValueError(f'unsupported x86-64 relocation {kind}; TLS/PC-relative/other types are not implemented')
            if not mapped(target):
                raise ValueError('relocation target is outside mapped memory or crosses a segment boundary')
            if kind == 8:
                if symbol_index or not base <= addend <= end:
                    raise ValueError('relative relocation is not an internal image reference')
                relocations.append((target, kind, 0, addend))
                continue
            if symbol_index >= len(symbol_rows):
                raise ValueError('relocation symbol index outside SCE symbol table')
            name_offset, info_byte, other, section, value, symbol_size = symbol_rows[symbol_index]
            symbol_kind = info_byte & 15
            if symbol_kind not in (0, 1, 2):
                raise ValueError('TLS/IFUNC/other special symbol types are unsupported')
            if section == 0:
                raw_name = executable.terminated(strings, name_offset)
                parts = raw_name.split('#')
                if len(parts) != 3 or not parts[0]:
                    raise ValueError('import lacks a complete scoped PS4 symbol identity')
                library_id, module_id = scope_id(parts[1]), scope_id(parts[2])
                if library_id not in scope_maps['library'] or module_id not in scope_maps['module']:
                    raise ValueError('import scope ID has no matching library/module descriptor')
                name = '#'.join((parts[0], scope_maps['library'][library_id], scope_maps['module'][module_id]))
                encoded = name.encode('utf-8')
                if not encoded or len(encoded) >= IMPORT_SIZE:
                    raise ValueError('import name is empty or exceeds 127 UTF-8 bytes')
                if name not in import_indices:
                    import_indices[name] = len(imports)
                    imports.append(name)
                    import_details.append({'name': name, 'raw_names': [raw_name],
                                           'library_id': library_id, 'module_id': module_id,
                                           'weak': info_byte >> 4 == 2,
                                           'symbol_type': symbol_kind, 'resolution': 'unresolved'})
                else:
                    detail = import_details[import_indices[name]]
                    if detail['symbol_type'] != symbol_kind:
                        raise ValueError('same canonical import has conflicting symbol types')
                    if raw_name not in detail['raw_names']:
                        detail['raw_names'].append(raw_name)
                    detail['weak'] = detail['weak'] and info_byte >> 4 == 2
                relocations.append((target, kind | IMPORT_BIT, import_indices[name], addend))
            else:
                if section >= 0xFF00:
                    raise ValueError('absolute/reserved ELF symbol sections are unsupported')
                if not mapped(value, 0) or not base <= value + addend <= end:
                    raise ValueError('defined relocation symbol/reference is outside native image')
                relocations.append((target, kind, value, addend))
    for left, right in zip(sorted(table_ranges), sorted(table_ranges)[1:]):
        if left[1] > right[0]:
            raise ValueError('SCE relocation tables overlap')
    relocations.sort()
    for left, right in zip(relocations, relocations[1:]):
        if left[0] + 8 > right[0]:
            raise ValueError('relocation writes overlap')

    payload_start = HEADER.size + len(loads) * SEGMENT.size + len(relocations) * RELOCATION.size + len(imports) * IMPORT_SIZE
    records, payload = [], bytearray()
    for p in loads:
        records.append(SEGMENT.pack(p['vaddr'], p['memsz'], p['filesz'], p['flags'], payload_start + len(payload)))
        payload.extend(image.read(p['offset'], p['filesz']))
    packed = bytearray(HEADER.pack(MAGIC, image.entry, base, end - base, len(loads), len(relocations), len(imports)))
    for record in records:
        packed.extend(record)
    for row in relocations:
        packed.extend(RELOCATION.pack(*row))
    for name in imports:
        packed.extend(name.encode('utf-8').ljust(IMPORT_SIZE, b'\0'))
    packed.extend(payload)
    metadata = {'schema_version': 1, 'format': MAGIC.decode(), 'input_sha256': hashlib.sha256(data).hexdigest(),
                'pack_sha256': hashlib.sha256(packed).hexdigest(), 'container': image.container,
                'entry': image.entry, 'image_base': base, 'image_size': end - base,
                'segment_count': len(loads), 'relocation_count': len(relocations), 'import_count': len(imports),
                'relocation_types': dict(Counter(str(r[1] & ~IMPORT_BIT) for r in relocations)),
                'imports': import_details,
                'imports_types_sha256': hashlib.sha256(bytes(item['symbol_type'] for item in import_details)).hexdigest(),
                'tls_segments': [p for p in image.programs if p['type'] == 7],
                'status': 'prepared native-host input; no game execution or import implementation',
                'limitations': ['No decryption, module loading, TLS relocations or runtime service implementation.',
                                'Pack import identities use descriptor-resolved scopes; raw names remain in metadata.',
                                'All imports are unresolved at preparation time.']}
    return bytes(packed), metadata


def prepare_path(source, output):
    source, output = Path(source), Path(output)
    source = source.resolve(strict=True)
    output = output.resolve()
    private_root = (ROOT / 'out').resolve()
    output.relative_to(private_root)
    if output == private_root or output == source or output in source.parents:
        raise ValueError('output must be a new private subdirectory of out/')
    if source.stat().st_size > executable.MAX_FILE:
        raise ValueError('executable exceeds 512 MiB inspection limit')
    packed, metadata = build_pack(source.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Exclusive creation: existing directories are never reused.
    try:
        with (output / 'image.pack').open('xb') as stream:
            stream.write(packed)
        with (output / 'metadata.json').open('x', encoding='utf-8') as stream:
            json.dump(metadata, stream, indent=2)
            stream.write('\n')
        with (output / 'imports.types').open('xb') as stream:
            stream.write(bytes(item['symbol_type'] for item in metadata['imports']))
        if hashlib.sha256(source.read_bytes()).hexdigest() != metadata['input_sha256']:
            raise ValueError('source changed during native preparation')
    except BaseException:
        shutil.rmtree(output)
        raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='new private directory under this repository out/')
    args = parser.parse_args()
    print(json.dumps(prepare_path(args.executable, args.out), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Link readable user-supplied PS4 modules into a private SKYPS401 host pack.

No module is executed here. Only exact scope/version exports are linked. Local
R_X86_64_DTPMOD64 (null or anonymous local-section symbol) is encoded as type16
with its stable TLS module ID in the symbol field; the host must validate
IDs1..16 and write that integer without rebasing. Other TLS relocations fail.
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
    from . import executable, module_graph, prepare_native
except ImportError:
    import executable
    import module_graph
    import prepare_native

ROOT = Path(__file__).resolve().parents[1]


def dynamic_tables(image):
    dynamic = [p for p in image.programs if p['type'] == 2]
    blobs = [p for p in image.programs if p['type'] == 0x61000000]
    if len(dynamic) != 1 or len(blobs) != 1:
        raise ValueError('linking requires one SCE dynamic and library-data segment')
    raw = image.read(dynamic[0]['offset'], dynamic[0]['filesz'])
    if len(raw) % 16 or len(raw) // 16 > executable.MAX_TABLE:
        raise ValueError('invalid linking dynamic-table size')
    tags, ended = {}, False
    for position in range(0, len(raw), 16):
        tag, value = executable.unpack('<QQ', raw, position)
        if not tag:
            ended = True
            break
        tags.setdefault(tag, []).append(value)
    if not ended:
        raise ValueError('linking dynamic table lacks terminator')

    def one(tag, default=None):
        values = tags.get(tag, [])
        if len(values) > 1:
            raise ValueError(f'duplicate linking metadata {tag:#x}')
        return values[0] if values else default

    blob = image.read(blobs[0]['offset'], blobs[0]['filesz'])
    syms = executable.take(blob, one(0x61000039), one(0x6100003F))
    if one(0x6100003B) != 24 or len(syms) % 24:
        raise ValueError('unsupported linking symbol-table layout')
    symbols = [executable.unpack('<IBBHQQ', syms, pos) for pos in range(0, len(syms), 24)]
    return one, blob, symbols


def link_images(inputs):
    if not inputs or len(inputs) > 16 or len({name for name, _ in inputs}) != len(inputs):
        raise ValueError('linking needs 1..16 uniquely named images')
    modules, cursor = [], None
    for index, (name, data) in enumerate(inputs):
        image = executable.Image(data)
        analysis = module_graph.analyze_bytes(data, name)
        loads = sorted((p for p in image.programs if p['type'] in (1, 0x61000010) and p['memsz']), key=lambda p: p['vaddr'])
        if not loads:
            raise ValueError('linked module has no loadable memory')
        for left, right in zip(loads, loads[1:]):
            if left['vaddr'] + left['memsz'] > right['vaddr']:
                raise ValueError('linked module load segments overlap')
        low = loads[0]['vaddr'] & ~4095
        high = (max(p['vaddr'] + p['memsz'] for p in loads) + 4095) & ~4095
        assigned = low if cursor is None else (cursor + 16383) & ~16383
        slide = assigned - low
        if slide < 0:
            raise ValueError('module would require a negative pack slide')
        cursor = high + slide
        if cursor > (1 << 64):
            raise ValueError('linked module virtual address overflow')
        one, blob, symbols = dynamic_tables(image)
        modules.append({'name': name, 'image': image, 'analysis': analysis, 'loads': loads,
                        'low': low, 'high': high, 'slide': slide, 'one': one, 'blob': blob,
                        'symbols': symbols, 'tls_id': index + 1})
    base = modules[0]['low']
    if cursor - base > prepare_native.MAX_IMAGE:
        raise ValueError('linked image exceeds 512 MiB span')
    if not any(p['flags'] & 1 and p['vaddr'] <= modules[0]['image'].entry < p['vaddr'] + p['filesz'] for p in modules[0]['loads']):
        raise ValueError('main entry is not file-backed executable memory')

    exporters = {}
    for module in modules[1:]:
        for symbol in module['analysis']['exports']:
            exporters.setdefault(module_graph.identity(symbol), []).append((module, symbol))
    imports, indices, details, requirements, relocs = [], {}, [], {}, []
    module_metadata = []
    bound_counts = Counter()
    for module in modules:
        image, one, blob, syms = module['image'], module['one'], module['blob'], module['symbols']
        slide = module['slide']
        imported = {s['index']: s for s in module['analysis']['imports']}

        def mapped(address, size=8):
            return any(p['vaddr'] <= address and address + size <= p['vaddr'] + p['memsz'] for p in module['loads'])

        ranges, count_by_type = [], Counter()
        for offset_tag, size_tag in ((0x6100002F, 0x61000031), (0x61000029, 0x6100002D)):
            offset, size = one(offset_tag), one(size_tag)
            if offset is None and size is None:
                continue
            if offset is None or size is None or size % 24 or one(0x61000033, 24) != 24:
                raise ValueError('invalid module relocation layout')
            table = executable.take(blob, offset, size)
            if size:
                ranges.append((offset, offset + size))
            for position in range(0, len(table), 24):
                target, info, addend = executable.unpack('<QQq', table, position)
                kind, symbol_index = info & 0xFFFFFFFF, info >> 32
                count_by_type[kind] += 1
                if not kind:
                    continue
                if not mapped(target):
                    raise ValueError('module relocation target outside load segments')
                target += slide
                if kind == 16:
                    local_section = (symbol_index < len(syms) and syms[symbol_index] == (0, 3, 0, 0, 0, 0))
                    if (symbol_index != 0 and not local_section) or addend != 0 or not any(p['type'] == 7 for p in image.programs):
                        raise ValueError(f"{module['name']}: DTPMOD64 requires a local null/anonymous-section symbol, zero addend and TLS template")
                    relocs.append((target, 16, module['tls_id'], 0))
                    continue
                if kind == 8:
                    if not module['low'] <= addend <= module['high']:
                        raise ValueError('module relative relocation is not internal')
                    if symbol_index:
                        if symbol_index >= len(syms):
                            raise ValueError('relative relocation redundant symbol index is out of range')
                        redundant = syms[symbol_index]
                        if not 0 < redundant[3] < 0xFF00 or redundant[4] != addend or not mapped(addend, 0):
                            raise ValueError('relative relocation has a nonredundant symbol index')
                    relocs.append((target, 8, 0, addend + slide))
                    continue
                if kind not in (1, 6, 7):
                    raise ValueError(f'unsupported module relocation type {kind}; other TLS forms are not implemented')
                if symbol_index >= len(syms):
                    raise ValueError('module relocation symbol index outside symbol table')
                _, info_byte, _, section, value, _ = syms[symbol_index]
                symbol_type = info_byte & 15
                if symbol_type not in (0, 1, 2):
                    raise ValueError('unsupported TLS/IFUNC relocation symbol')
                if section:
                    if section >= 0xFF00 or not mapped(value, 0):
                        raise ValueError('defined module relocation symbol is unmapped/reserved')
                    relocs.append((target, kind, value + slide, addend))
                    continue
                if symbol_index not in imported:
                    raise ValueError('undefined relocation lacks named import metadata')
                symbol = imported[symbol_index]
                key = module_graph.identity(symbol)
                candidates = exporters.get(key, []) if key else []
                candidates = [(owner, export) for owner, export in candidates
                              if export['type'] == symbol_type or 0 in (export['type'], symbol_type)]
                if len(candidates) > 1:
                    raise ValueError('ambiguous exact-scope native export providers')
                if candidates:
                    owner, export = candidates[0]
                    if not any(p['vaddr'] <= export['address'] <= p['vaddr'] + p['memsz'] for p in owner['loads']):
                        raise ValueError('native export address is outside provider memory')
                    relocs.append((target, kind, export['address'] + owner['slide'], addend))
                    bound_counts[(module['name'], owner['name'])] += 1
                    continue
                name = symbol['name']
                encoded = name.encode('utf-8')
                if not encoded or len(encoded) >= prepare_native.IMPORT_SIZE:
                    raise ValueError('native import name does not fit pack')
                if name in requirements and requirements[name] != key:
                    raise ValueError('pack cannot merge different scope versions with one canonical name')
                requirements[name] = key
                if name not in indices:
                    indices[name] = len(imports)
                    imports.append(name)
                    details.append({'name': name, 'symbol_type': symbol_type, 'weak': symbol['binding'] == 2,
                                    'raw_names': [symbol['raw_name']], 'consumers': [module['name']],
                                    'resolution': 'unresolved'})
                else:
                    detail = details[indices[name]]
                    if detail['symbol_type'] != symbol_type and 0 not in (detail['symbol_type'], symbol_type):
                        raise ValueError('canonical native import has conflicting types')
                    detail['symbol_type'] = detail['symbol_type'] or symbol_type
                    detail['weak'] = detail['weak'] and symbol['binding'] == 2
                    for field, item in (('raw_names', symbol['raw_name']), ('consumers', module['name'])):
                        if item not in detail[field]:
                            detail[field].append(item)
                relocs.append((target, kind | prepare_native.IMPORT_BIT, indices[name], addend))
        for left, right in zip(sorted(ranges), sorted(ranges)[1:]):
            if left[1] > right[0]:
                raise ValueError('module relocation tables overlap')
        tls = []
        for p in image.programs:
            if p['type'] == 7:
                if p['filesz'] > p['memsz'] or not mapped(p['vaddr'], p['memsz']):
                    raise ValueError('module TLS template is outside loaded memory')
                tls.append({'module_id': module['tls_id'], 'address': p['vaddr'] + slide,
                            'filesz': p['filesz'], 'memsz': p['memsz'], 'align': p['align']})
        init = {}
        for tag, label in ((12, 'init'), (13, 'fini'), (25, 'init_array'), (26, 'fini_array')):
            value = one(tag)
            if value is not None:
                if not mapped(value, 0):
                    raise ValueError('module initialization metadata outside loaded memory')
                init[label] = value + slide
        for tag, label in ((27, 'init_array_bytes'), (28, 'fini_array_bytes')):
            value = one(tag)
            if value is not None:
                if value % 8:
                    raise ValueError('module initializer array size is not pointer-aligned')
                init[label] = value
        module_metadata.append({'name': module['name'], 'input_sha256': module['analysis']['input_sha256'],
                                'slide': slide, 'tls_id': module['tls_id'], 'tls': tls,
                                'initialization': init, 'relocation_types': dict(count_by_type),
                                'status': 'linked metadata only; no initializer executed'})
        params = [p for p in image.programs if p['type'] == 0x61000001]
        if len(params) > 1 or (params and not mapped(params[0]['vaddr'], params[0]['memsz'])):
            raise ValueError('invalid process parameter segment')
        module_metadata[-1]['process_param'] = params[0]['vaddr'] + slide if params else 0
    relocs.sort()
    for left, right in zip(relocs, relocs[1:]):
        if left[0] + 8 > right[0]:
            raise ValueError('linked relocation writes overlap')
    segments = [(module, p) for module in modules for p in module['loads']]
    payload_offset = prepare_native.HEADER.size + len(segments) * prepare_native.SEGMENT.size + len(relocs) * prepare_native.RELOCATION.size + len(imports) * prepare_native.IMPORT_SIZE
    records, payload = [], bytearray()
    for module, p in segments:
        records.append(prepare_native.SEGMENT.pack(p['vaddr'] + module['slide'], p['memsz'], p['filesz'], p['flags'], payload_offset + len(payload)))
        payload.extend(module['image'].read(p['offset'], p['filesz']))
    packed = bytearray(prepare_native.HEADER.pack(prepare_native.MAGIC, modules[0]['image'].entry,
                                                base, cursor - base, len(segments), len(relocs), len(imports)))
    for record in records:
        packed.extend(record)
    for relocation in relocs:
        packed.extend(prepare_native.RELOCATION.pack(*relocation))
    for name in imports:
        packed.extend(name.encode('utf-8').ljust(prepare_native.IMPORT_SIZE, b'\0'))
    packed.extend(payload)
    types = bytes(detail['symbol_type'] | (0x80 if detail['weak'] else 0) for detail in details)
    metadata = {'schema_version': 1, 'format': 'SKYPS401', 'pack_sha256': hashlib.sha256(packed).hexdigest(),
                'imports_types_sha256': hashlib.sha256(types).hexdigest(), 'modules': module_metadata,
                'segment_count': len(segments), 'relocation_count': len(relocs), 'import_count': len(imports),
                'imports': details, 'bindings': [{'consumer': consumer, 'provider': provider, 'sites': count}
                                               for (consumer, provider), count in sorted(bound_counts.items())],
                'tls_relocation_extension': 'type16 local DTPMOD64 writes symbol-field TLS module ID1..16, no rebasing',
                'status': 'prepared linked native input; no execution or runtime import implementation'}
    return bytes(packed), types, metadata


def boot_plan(metadata):
    """SKYBOOT1: process-param VA, count, then six-Q module records.

    The host validates every address against the pack before executing anything.
    Main DT_INIT is left to the executable startup; dependencies run in link order.
    Nonempty initializer arrays need a future explicit execution contract.
    """
    modules = metadata['modules']
    result = bytearray(struct.pack('<8s2Q', b'SKYBOOT1', modules[0]['process_param'], len(modules)))
    for module in modules:
        init = module['initialization']
        if init.get('init_array_bytes', 0):
            raise ValueError('nonempty initializer arrays are not supported by diagnostic boot')
        if len(module['tls']) > 1:
            raise ValueError('multiple TLS templates in module')
        tls = module['tls'][0] if module['tls'] else {}
        result.extend(struct.pack('<6Q', module['tls_id'], init.get('init', 0),
                                  tls.get('address', 0), tls.get('filesz', 0),
                                  tls.get('memsz', 0), tls.get('align', 1)))
    return bytes(result)


def prepare_linked(game, output, module_names=('libc.prx', 'libSceFios2.prx')):
    game, output = Path(game).resolve(strict=True), Path(output).resolve()
    private = (ROOT / 'out').resolve()
    output.relative_to(private)
    if output == private:
        raise ValueError('choose a new private subdirectory under out/')
    if any(Path(name).name != name for name in module_names):
        raise ValueError('module names must be basenames under sce_module/')
    paths = [game / 'eboot.bin', *(game / 'sce_module' / name for name in module_names)]
    if any(path.stat().st_size > executable.MAX_FILE for path in paths):
        raise ValueError('linked input exceeds file-size inspection limit')
    packed, types, metadata = link_images([(path.name, path.read_bytes()) for path in paths])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    try:
        (output / 'image.pack').write_bytes(packed)
        (output / 'imports.types').write_bytes(types)
        (output / 'boot.plan').write_bytes(boot_plan(metadata))
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        for path, module in zip(paths, metadata['modules']):
            if hashlib.sha256(path.read_bytes()).hexdigest() != module['input_sha256']:
                raise ValueError('input changed during linked preparation')
    except BaseException:
        shutil.rmtree(output)
        raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    metadata = prepare_linked(args.game, args.out)
    print(json.dumps({key: metadata[key] for key in ('segment_count', 'relocation_count', 'import_count', 'bindings')}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, struct.error) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)

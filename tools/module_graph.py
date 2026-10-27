#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only PS4 module export/dependency analysis; no loading or execution."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys

try:
    from . import executable
    from .prepare_native import scope_id
except ImportError:
    import executable
    from prepare_native import scope_id

ROOT = Path(__file__).resolve().parents[1]


def analyze_bytes(data, name):
    image = executable.Image(data)
    dynamics = [p for p in image.programs if p['type'] == 2]
    blobs = [p for p in image.programs if p['type'] == 0x61000000]
    if len(dynamics) != 1 or len(blobs) != 1:
        raise ValueError('module analysis requires one dynamic and one SCE library-data segment')
    dynamic = image.read(dynamics[0]['offset'], dynamics[0]['filesz'])
    if len(dynamic) % 16 or len(dynamic) // 16 > executable.MAX_TABLE:
        raise ValueError('invalid module dynamic-table size')
    tags, ended = {}, False
    for position in range(0, len(dynamic), 16):
        tag, value = executable.unpack('<QQ', dynamic, position)
        if tag == 0:
            ended = True
            break
        tags.setdefault(tag, []).append(value)
    if not ended:
        raise ValueError('module dynamic table lacks terminator')

    def one(tag):
        values = tags.get(tag, [])
        if len(values) != 1:
            raise ValueError(f'missing/duplicate module dynamic metadata {tag:#x}')
        return values[0]

    blob = image.read(blobs[0]['offset'], blobs[0]['filesz'])
    strings = executable.take(blob, one(0x61000035), one(0x61000037))
    table = executable.take(blob, one(0x61000039), one(0x6100003F))
    if one(0x6100003B) != 24 or len(table) % 24 or len(table) // 24 > executable.MAX_TABLE:
        raise ValueError('unsupported module symbol-table layout')
    descriptors = {'library': {}, 'module': {}}
    declared = []
    for tag, kind, direction in ((0x6100000D, 'module', 'export'), (0x6100000F, 'module', 'import'),
                                 (0x61000013, 'library', 'export'), (0x61000015, 'library', 'import')):
        for raw in tags.get(tag, []):
            identifier = raw >> 48
            identity = {'name': executable.terminated(strings, raw & 0xFFFFFFFF),
                        'version_raw': (raw >> 32) & 0xFFFF}
            if not identity['name'] or '#' in identity['name']:
                raise ValueError('invalid scope descriptor name')
            previous = descriptors[kind].get(identifier)
            if previous is not None and previous != identity:
                raise ValueError('conflicting descriptor identity for module-local scope ID')
            descriptors[kind][identifier] = identity
            declared.append({'id': identifier, 'kind': kind, 'direction': direction, **identity})

    imports, exports, plain_definitions = [], [], []
    for index in range(len(table) // 24):
        offset, info, other, section, address, size = executable.unpack('<IBBHQQ', table, index * 24)
        raw_name = executable.terminated(strings, offset)
        if not raw_name:
            continue
        symbol = {'raw_name': raw_name, 'index': index, 'type': info & 15,
                  'binding': info >> 4, 'visibility': other & 3,
                  'section': section, 'address': address, 'size': size}
        parts = raw_name.split('#')
        if len(parts) != 3:
            if section:
                plain_definitions.append(symbol)
                continue
            symbol.update(name=raw_name, nid=None, library=None, module=None,
                          scope_status='unscoped; no automatic matching')
            imports.append(symbol)
            continue
        library_id, module_id = scope_id(parts[1]), scope_id(parts[2])
        if not parts[0] or library_id not in descriptors['library'] or module_id not in descriptors['module']:
            raise ValueError('symbol scope lacks a descriptor')
        library, module = descriptors['library'][library_id], descriptors['module'][module_id]
        symbol.update(nid=parts[0], library=library, module=module,
                      name='#'.join((parts[0], library['name'], module['name'])))
        if section == 0:
            imports.append(symbol)
        elif symbol['binding'] in (1, 2) and symbol['visibility'] in (0, 3) and section < 0xFF00:
            exports.append(symbol)
    return {'name': name, 'input_sha256': hashlib.sha256(data).hexdigest(),
            'container': image.container, 'descriptors': declared,
            'imports': imports, 'exports': exports, 'plain_definitions': plain_definitions,
            'status': 'metadata only; no module loading, relocation or execution'}


def analyze_path(path):
    path = Path(path)
    if path.stat().st_size > executable.MAX_FILE:
        raise ValueError('module exceeds 512 MiB inspection limit')
    return analyze_bytes(path.read_bytes(), path.name)


def identity(symbol):
    if symbol['library'] is None or symbol['module'] is None:
        return None
    return (symbol['nid'], symbol['library']['name'], symbol['library']['version_raw'],
            symbol['module']['name'], symbol['module']['version_raw'])


def match_modules(consumers, providers):
    export_index = {}
    for module in providers:
        for symbol in module['exports']:
            export_index.setdefault(identity(symbol), []).append((module['name'], symbol))
    reports = []
    for module in consumers:
        matched, missing, ambiguous, incompatible = [], [], [], []
        for symbol in module['imports']:
            key = identity(symbol)
            candidates = export_index.get(key, []) if key is not None else []
            compatible = [(provider, export) for provider, export in candidates
                          if symbol['type'] == export['type'] or 0 in (symbol['type'], export['type'])]
            record = {'name': symbol['name'], 'raw_name': symbol['raw_name'],
                      'weak': symbol['binding'] == 2,
                      'library_name': symbol['library']['name'] if symbol['library'] else '<unscoped>',
                      'library_version_raw': symbol['library']['version_raw'] if symbol['library'] else None,
                      'module_version_raw': symbol['module']['version_raw'] if symbol['module'] else None}
            if len(compatible) == 1:
                provider, export = compatible[0]
                matched.append({**record, 'provider': provider, 'export_address': export['address']})
            elif compatible:
                ambiguous.append({**record, 'providers': [p for p, _ in compatible]})
            elif candidates:
                incompatible.append(record)
            else:
                missing.append(record)
        reports.append({'consumer': module['name'], 'imports': len(module['imports']),
                        'matched': matched, 'missing': missing, 'ambiguous': ambiguous,
                        'type_mismatch': incompatible,
                        'missing_by_library': dict(Counter(s['library_name'] for s in missing))})
    return {'schema_version': 1, 'matching': 'exact NID, library name/version, module name/version; compatible symbol type',
            'consumers': reports, 'provider_names': [p['name'] for p in providers],
            'status': 'static dependency candidates only; none executed or runtime-resolved',
            'limitations': ['No library aliases, version substitution or NID-only fallback.',
                            'Export declarations do not establish valid relocation, TLS or initializer behavior.']}


def write_graph(game, output, module_names=('libc.prx', 'libSceFios2.prx')):
    game, output = Path(game).resolve(strict=True), Path(output).resolve()
    private = (ROOT / 'out').resolve()
    output.relative_to(private)
    if output == private:
        raise ValueError('choose a new subdirectory under out/')
    for filename in module_names:
        if Path(filename).name != filename:
            raise ValueError('module names must be basenames inside sce_module/')
    main = analyze_path(game / 'eboot.bin')
    modules = [analyze_path(game / 'sce_module' / filename) for filename in module_names]
    graph = match_modules([main, *modules], modules)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    (output / 'modules.json').write_text(json.dumps([main, *modules], indent=2) + '\n', encoding='utf-8')
    (output / 'graph.json').write_text(json.dumps(graph, indent=2) + '\n', encoding='utf-8')
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    graph = write_graph(args.game, args.out)
    print(json.dumps([{'consumer': c['consumer'], 'imports': c['imports'], 'matched': len(c['matched']),
                       'missing': len(c['missing']), 'ambiguous': len(c['ambiguous']),
                       'type_mismatch': len(c['type_mismatch']), 'missing_by_library': c['missing_by_library']}
                      for c in graph['consumers']], indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)

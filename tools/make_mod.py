#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make a data mod by editing game files, without writing offsets or hashes.

    make_mod.py unpack level/title.bld out/mod-work/title
        Decode every file inside a game archive into a folder you can edit.
    make_mod.py diff out/mod-work/title mods/my-mod
        Compare your edited files with the game and write portable edits into
        mods/my-mod/mod.json (created if missing). Files must keep their size.
    make_mod.py port profiles/patches/x-01.01.json --to CUSA00626@01.00 -o x-01.00.json
        Write an exact recipe file for another installed build from one that
        works on this build: unchanged archives are reused, identical blocks
        keep their edits, and other changes are found again by content.
    make_mod.py check mods/my-mod [--add]
        Try the mod on every installed build of the game; --add lists the
        builds it fits in its targets.

Edits are found by content (tools/archive_blocks.py), so one mod can fit
several game builds. The mod holds only your changes and short search
patterns, never the game's files. Unpacked files are the game's: keep them
private, inside out/ or another ignored folder.
"""
import argparse
import hashlib
import struct
import json
from pathlib import Path, PurePosixPath
import re
import sys

try:
    from . import archive_blocks, asset_mod, game_install, game_library, mod_manifest
except ImportError:
    import archive_blocks, asset_mod, game_install, game_library, mod_manifest

ROOT = Path(__file__).resolve().parents[1]
GAP = 8          # changed runs closer than this become one edit
CONTEXT = 8      # bytes of context added on each side per step


def builds(project=ROOT, title_id=None):
    """(entry, install) for every installed game build, newest last."""
    result = []
    for entry in game_library.entries(project):
        if title_id is None or entry['title_id'] == title_id:
            result.append((entry, game_install.discover(entry)))
    return sorted(result, key=lambda item: (item[0]['title_id'], game_install.version(item[0]['app_version'])))


def pick(project, game):
    choices = builds(project)
    if game:
        title, version = game_library.split_selector(game)
        choices = [c for c in choices if c[0]['title_id'] == title and version in (None, c[0]['app_version'])]
    if not choices:
        raise SystemExit('No matching installed game; pass --game TITLE_ID@APP_VER')
    titles = {c[0]['title_id'] for c in choices}
    if len(titles) > 1:
        raise SystemExit('Several games are installed; pass --game TITLE_ID@APP_VER')
    return choices[-1]


def safe_name(member):
    """A relative file path for an archive member name."""
    parts = [part for part in re.split(r'[\\/]+', member.replace(':', '_')) if part not in ('', '.')]
    if not parts or '..' in parts:
        raise ValueError(f'archive member {member!r} has no safe file name')
    return PurePosixPath(*parts)


def unpack(asset, folder, game=None, project=ROOT):
    entry, install = pick(project, game)
    source = install.source(asset)
    data = source.read_bytes()
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f'{folder} is not empty')
    folder.mkdir(parents=True, exist_ok=True)
    files, current, parts = {}, None, []

    def flush():
        if current is not None:
            path = safe_name(current)
            if str(path) in files:
                raise ValueError(f'two archive members share the file name {path}')
            files[str(path)] = current
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(b''.join(parts))
    for block in archive_blocks.blocks(data):
        if block['member'] != current:
            flush();current, parts = block['member'], []
        parts.append(block['plain'])
    flush()
    (folder / 'unpack.json').write_text(json.dumps(dict(
        asset=asset, title_id=entry['title_id'], app_version=entry['app_version'],
        executable_sha256=entry['executable_sha256'], source_sha256=hashlib.sha256(data).hexdigest(),
        files=files), indent=2) + '\n', encoding='utf-8')
    return files


def runs(original, edited):
    """[start, end) ranges where the bytes differ, joined across small gaps and split at blocks."""
    changed, start, last = [], None, None
    for index, (a, b) in enumerate(zip(original, edited)):
        if a == b:
            continue
        if start is not None and index - last > GAP:
            changed.append((start, last + 1));start = None
        if start is None:
            start = index
        last = index
    if start is not None:
        changed.append((start, last + 1))
    result = []
    for start, end in changed:
        while start // archive_blocks.BLOCK != (end - 1) // archive_blocks.BLOCK:
            cut = (start // archive_blocks.BLOCK + 1) * archive_blocks.BLOCK
            result.append((start, cut));start = cut
        result.append((start, end))
    return result


def overlapping_count(haystack, needle):
    count, at = 0, haystack.find(needle)
    while at >= 0:
        count += 1;at = haystack.find(needle, at + 1)
    return count


PIECE = 128


def portable_edits(data, other_archives, changed):
    """Portable edits for changed={member: edited bytes} of archive data.

    other_archives: the same archive from other builds; edits are made to fit
    them where the content allows. Returns (edits, [fits each other archive]).
    """
    members = {}
    for block in archive_blocks.blocks(data):
        members.setdefault(block['member'], []).append(block['plain'])
    blocks = [plain for parts in members.values() for plain in parts]
    others = [[block['plain'] for block in archive_blocks.blocks(other)] for other in other_archives]
    edits = []
    for member, edited in changed.items():
        if member not in members:
            raise ValueError(f'{member} is not in this archive')
        original = b''.join(members[member])
        if len(edited) != len(original):
            raise ValueError(f'{member} changed size ({len(original)} -> {len(edited)} bytes); edits must keep the size')
        for start, end in runs(original, edited):
            # A long change (rewritten text) is split so each piece fits a pattern with context.
            for piece in range(start, end, PIECE):
                edits.append(_edit(blocks, others, member, original, edited, piece, min(end, piece + PIECE)))
    if not edits:
        raise ValueError('No changes found')
    fitting = []
    for other in other_archives:
        try:archive_blocks.resolve(other, 'archive', edits);fitting.append(True)
        except ValueError:fitting.append(False)
    return edits, fitting


def diff(folder, mod, project=ROOT):
    folder, mod = Path(folder), Path(mod)
    info = json.loads((folder / 'unpack.json').read_text(encoding='utf-8'))
    entry, install = pick(project, game_library.selector(info['title_id'], info['app_version']))
    data = install.source(info['asset']).read_bytes()
    if hashlib.sha256(data).hexdigest() != info['source_sha256']:
        raise SystemExit('The game archive changed since it was unpacked; unpack it again')
    others = []
    for other, other_install in builds(project, info['title_id']):
        if other['executable_sha256'] == entry['executable_sha256']:
            continue
        try:other_data = other_install.source(info['asset']).read_bytes()
        except OSError:continue
        if other_data != data:
            others.append((other, other_data))
    changed = {member: (folder / path).read_bytes() for path, member in info['files'].items()}
    edits, fitting = portable_edits(data, [o[1] for o in others], changed)
    fits = [entry] + [other for (other, _), ok in zip(others, fitting) if ok]
    manifest_path = mod / 'mod.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    else:
        manifest = dict(schema_version=1, id=re.sub(r'[^a-z0-9-]+', '-', mod.name.lower()).strip('-')[:64] or 'my-mod',
                        name=mod.name, version='1.0.0', author='Unknown', licence='Unspecified',
                        description='Made with tools/make_mod.py.',
                        targets=[dict(title_id=e['title_id'], app_version=e['app_version'],
                                      executable_sha256=e['executable_sha256']) for e in fits],
                        requires=[], conflicts=[], settings={}, operations=[])
    manifest['operations'] = [op for op in manifest.get('operations', [])
                              if not (op.get('type') == 'asset-find' and op.get('asset') == info['asset'])]
    manifest['operations'].append(dict(type='asset-find', asset=info['asset'], edits=edits))
    # Check before writing: a mod.json that fails here would fail at launch too.
    mod_manifest.parse(manifest, mod)
    archive_blocks.resolve(data, info['asset'], edits)
    mod.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return edits, fits, [other for other, _ in others if other not in fits]


class NotUnique(ValueError):
    pass


def _pointerish(raw):
    """A value that looks like an offset or pointer, which builds tend to change."""
    return len(raw) == 8 and 0x100 <= int.from_bytes(raw, 'little') < 1 << 40


def _literal(text):
    """The longest run of fixed bytes in hex text with ?? wildcards."""
    return max((bytes.fromhex(part) for part in text.split('??') if part), key=len, default=b'')


def _count(plains, compiled, text=None):
    """0, 1 or 2 (two or more): only uniqueness matters.

    text: the pattern's hex; blocks without its longest fixed run are skipped by a
    fast byte search before the slower pattern match (large archives)."""
    literal = _literal(text) if text else b''
    total = 0
    for plain in plains:
        if literal and literal not in plain:
            continue
        for _ in compiled.finditer(plain):
            total += 1
            if total > 1:
                return 2
    return total


def _portable(blocks, others, original, start, end, fixed):
    """(a, b, find_hex) around [start, end): unique here and, when possible, once in every
    other build. Pointer-like 8-byte values outside fixed=(from, to) become wildcards."""
    low = start // archive_blocks.BLOCK * archive_blocks.BLOCK
    high = min(len(original), low + archive_blocks.BLOCK)
    best, grow = None, 0
    while True:
        a, b = max(low, start - grow), min(high, end + grow)
        if b - a > archive_blocks.MAX_FIND:
            break
        texts = [original[a:b].hex()]
        # Pointers sit at a fixed alignment that need not be a multiple of 8 from the
        # member start; try each phase.
        for phase in range(8):
            mask = [True] * (b - a)
            for q in range(a + (phase - a) % 8, b - 7, 8):
                if (q + 8 <= fixed[0] or q >= fixed[1]) and _pointerish(original[q:q + 8]):
                    mask[q - a:q - a + 8] = [False] * 8
            texts.append(''.join(f'{byte:02x}' if keep else '??' for byte, keep in zip(original[a:b], mask)))
        for text in sorted(dict.fromkeys(texts), key=lambda item: item.count('?')):
            if b - a < 4:
                continue
            try:compiled, _ = archive_blocks.pattern(text)
            except ValueError:continue
            if _count(blocks, compiled, text) != 1:
                continue
            if all(_count(plains, compiled, text) == 1 for plains in others):
                return a, b, text
            best = best or (a, b, text)
        if a == low and b == high:
            break
        grow += CONTEXT
    if best:
        return best
    raise NotUnique(f'the change at byte {start} is not unique within its block; edit fewer bytes there or edit by hand')


def _edit(blocks, others, member, original, edited, start, end):
    """One portable edit for the change at [start, end) of a member."""
    # The first changed byte is usually where the value starts, so try that window first.
    for q0 in range(start, max(end - 8, 0) - 1, -1):
        new, old = edited[q0:q0 + 8], original[q0:q0 + 8]
        if q0 // archive_blocks.BLOCK != (q0 + 7) // archive_blocks.BLOCK or not (_pointerish(new) and _pointerish(old)):
            continue
        # A changed pointer: copy the new value from where the game already holds it, so
        # each build gets its own value instead of this build's.
        at = original.find(new)
        while at >= 0:
            if at != q0 and at // archive_blocks.BLOCK == (at + 7) // archive_blocks.BLOCK:
                try:
                    ca, cb, ctext = _portable(blocks, others, original, at, at + 8, (at, at))
                    a, b, text = _portable(blocks, others, original, q0, q0 + 8, (q0, q0 + 8))
                    return dict(member=member, find_hex=text, at=q0 - a, length=8,
                                copy=dict(member=member, find_hex=ctext, at=at - ca))
                except NotUnique:
                    pass
            at = original.find(new, at + 1)
    a, b, text = _portable(blocks, others, original, start, end, (start, end))
    return dict(member=member, find_hex=text, at=start - a, replacement_hex=edited[start:end].hex())


def _member_bytes(data):
    members = {}
    for block in archive_blocks.blocks(data):
        members.setdefault(block['member'], []).append(block)
    return members


def port_asset(recipe, source, target):
    """An asset recipe for archive target, from recipe written for archive source.

    Returns (recipe, how) or raises ValueError explaining why it cannot be ported.
    """
    if hashlib.sha256(source).hexdigest() != recipe['source_sha256']:
        raise ValueError(f"{recipe['asset']}: the recipe is for a different copy of this archive")
    if source == target:
        return recipe, 'same archive'
    by_hash = {}
    for block in archive_blocks.blocks(target):
        by_hash.setdefault(hashlib.sha256(block['plain']).hexdigest(), []).append(block)
    chunks, moved = [], True
    for chunk in recipe['chunks']:
        found = by_hash.get(chunk['decoded_sha256'], [])
        if len(found) != 1 or found[0]['chunk']['decoded_size'] != chunk['decoded_size']:
            moved = False
            break
        chunks.append(dict(found[0]['chunk'], decoded_sha256=chunk['decoded_sha256'], edits=chunk['edits']))
    if moved:
        ported = dict(recipe, source_sha256=hashlib.sha256(target).hexdigest(), chunks=chunks)
        asset_mod.patch_asset(target, ported)  # every check, before it is written anywhere
        return ported, 'identical blocks'
    # The edited blocks differ: find each change again by content.
    patched, _ = asset_mod.patch_asset(source, recipe)
    before, after = _member_bytes(source), _member_bytes(patched)
    changed = {}
    for member, parts in after.items():
        edited = b''.join(block['plain'] for block in parts)
        if edited != b''.join(block['plain'] for block in before[member]):
            changed[member] = edited
    edits, fitting = portable_edits(source, [target], changed)
    if fitting[0]:
        ported = archive_blocks.resolve(target, recipe['asset'], edits)
        asset_mod.patch_asset(target, ported)
        return ported, 'found by content'
    ported = relocate(recipe['asset'], source, target, before, changed)
    asset_mod.patch_asset(target, ported)
    return ported, 'relocated: the original values differ in this build, review before use'


def _translate(original, whole, value):
    """Where the object a pointer value names sits in the other build's member.

    Game data members are IGZ files whose pointers are offsets into the object
    section (its start is at header offset 0x28). The object is found by its
    first 128 bytes with pointer-like values masked, near the same offset; the
    result is None unless exactly one place matches."""
    if original[:4] != b'\x01ZGI' or whole[:4] != b'\x01ZGI':
        return None
    size = 128
    def signature(data, at):
        base = struct.unpack_from('<I', data, 0x28)[0] + at
        if not 0 <= base <= len(data) - size:
            return None
        part = data[base:base + size]
        return [None if _pointerish(part[i:i + 8]) else part[i:i + 8] for i in range(0, size, 8)]
    wanted = signature(original, value)
    if wanted is None or sum(item is not None for item in wanted) < 6:
        return None
    hits = []
    for distance in range(-0x4000, 0x4001, 4):
        other = signature(whole, value + distance)
        if other and all(a is None or b is None or a == b for a, b in zip(wanted, other)) and \
                sum(a is not None and b is not None for a, b in zip(wanted, other)) >= 6:
            hits.append(value + distance)
    return hits[0] if len(hits) == 1 else None


def relocate(asset, source, target, before, changed):
    """Exact edits for target where the original bytes are moved pointers.

    Each change is found by its surroundings with pointer-like values masked,
    including the bytes it replaces, uniquely in both builds. The target's own
    bytes there become the expected bytes. A new value is written only when it
    also occurs in the target archive's file, so a pointer is never invented.
    """
    blocks = [block['plain'] for parts in before.values() for block in parts]
    target_blocks = list(archive_blocks.blocks(target))
    target_plains = [block['plain'] for block in target_blocks]
    target_members = {}
    for block in target_blocks:
        target_members.setdefault(block['member'], []).append(block['plain'])
    chunks = {}
    for member, edited in changed.items():
        original = b''.join(block['plain'] for block in before[member])
        whole = b''.join(target_members.get(member, []))
        for start, end in runs(original, edited):
            new = bytearray()
            q0 = start
            # Each changed 8-byte value from the change's start; a pointer may name an
            # object that sits elsewhere in the other build too.
            while q0 < end:
                if _pointerish(edited[q0:q0 + 8]):
                    target_value = _translate(original, whole, int.from_bytes(edited[q0:q0 + 8], 'little'))
                    if target_value is None:
                        raise ValueError(f'{asset}: the object the new value at byte {q0} of {member} points to '
                                         'is not found once in the other build')
                    new += target_value.to_bytes(8, 'little');end = max(end, q0 + 8)
                else:
                    new += edited[q0:min(q0 + 8, end)]
                q0 += 8
            new = bytes(new)
            a, b, text = _portable(blocks, [target_plains], original, start, end, (start, start))
            compiled, _ = archive_blocks.pattern(text)
            found = [(block, match.start()) for block in target_blocks if block['member'] == member
                     for match in compiled.finditer(block['plain'])]
            if len(found) != 1:
                raise ValueError(f'{asset}: the change at byte {start} of {member} is not found once in the other build')
            block, at = found[0]
            offset = at + start - a
            expected = block['plain'][offset:offset + len(new)]
            if expected == new:
                continue
            chunk = chunks.setdefault(block['chunk']['offset'], dict(
                block['chunk'], decoded_sha256=hashlib.sha256(block['plain']).hexdigest(), edits=[]))
            chunk['edits'].append(dict(offset=offset, expected_hex=expected.hex(), replacement_hex=new.hex()))
    if not chunks:
        raise ValueError(f'{asset}: nothing to change in the other build')
    for chunk in chunks.values():
        chunk['edits'].sort(key=lambda item: item['offset'])
    return dict(asset=asset, source_sha256=hashlib.sha256(target).hexdigest(),
                chunks=[chunks[key] for key in sorted(chunks)])


def port(profile_path, game, output, project=ROOT):
    profile = json.loads(Path(profile_path).read_text(encoding='utf-8'))
    source_entry, source_install = pick(project, game_library.selector(profile['title_id'], profile['app_version']))
    if source_entry['executable_sha256'] != profile['executable_sha256']:
        raise SystemExit('The installed source build does not match the recipe file')
    entry, install = pick(project, game)
    assets, report = [], []
    for recipe in profile['assets']:
        source = source_install.source(recipe['asset']).read_bytes()
        target = install.source(recipe['asset']).read_bytes()
        ported, how = port_asset(recipe, source, target)
        assets.append(ported);report.append((recipe['asset'], how))
    result = dict(profile, title_id=entry['title_id'], app_version=entry['app_version'],
                  executable_sha256=entry['executable_sha256'], assets=assets)
    if 'status' in profile:
        result['status'] = f"Ported from {profile['app_version']} by tools/make_mod.py port; " + profile['status']
    Path(output).write_text(json.dumps(result, indent=1) + '\n', encoding='utf-8')
    return report


def check(mod, add=False, project=ROOT):
    mod = Path(mod)
    manifest = mod_manifest.read(mod)
    manifest['root'] = str(project)
    title_ids = {target['title_id'] for target in manifest['targets']}
    declared = {target['executable_sha256'] for target in manifest['targets']}
    results, fits = [], []
    for entry, install in [item for title in sorted(title_ids) for item in builds(project, title)]:
        trial = dict(manifest, targets=manifest['targets'] + ([] if entry['executable_sha256'] in declared else [
            dict(title_id=entry['title_id'], app_version=entry['app_version'], executable_sha256=entry['executable_sha256'])]))
        try:
            mod_manifest.plan({manifest['id']: trial}, [manifest['id']], entry['executable_sha256'],
                              title_id=entry['title_id'], asset_source=install.source,
                              executable=Path(install.source('eboot.bin')).read_bytes())
            status = 'fits'
            fits.append(entry)
        except (OSError, ValueError) as error:
            status = 'does not fit: ' + str(error)
        listed = 'listed' if entry['executable_sha256'] in declared else 'not listed'
        results.append((entry, listed, status))
        print(f"{entry['title_id']} {entry['app_version']} ({listed}): {status}")
    if add:
        data = json.loads((mod / 'mod.json').read_text(encoding='utf-8'))
        for entry in fits:
            if entry['executable_sha256'] not in declared:
                data['targets'].append(dict(title_id=entry['title_id'], app_version=entry['app_version'],
                                            executable_sha256=entry['executable_sha256']))
                declared.add(entry['executable_sha256'])
                print(f"Added {entry['title_id']} {entry['app_version']} to the targets.")
        (mod / 'mod.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('unpack', help='decode a game archive into editable files')
    one.add_argument('asset', help='archive path inside the game, for example level/title.bld')
    one.add_argument('folder')
    one.add_argument('--game', help='TITLE_ID@APP_VER of the installed build to read')
    two = commands.add_parser('diff', help='write portable edits from your edited files')
    two.add_argument('folder', help='a folder made by unpack')
    two.add_argument('mod', help='the mod folder; mod.json is created or updated')
    four = commands.add_parser('port', help='write a recipe file for another installed build')
    four.add_argument('profile', help='a recipe file (profiles/patches format) for an installed build')
    four.add_argument('--to', required=True, help='TITLE_ID@APP_VER of the build to port to')
    four.add_argument('-o', '--output', required=True)
    three = commands.add_parser('check', help='try a mod on every installed build')
    three.add_argument('mod')
    three.add_argument('--add', action='store_true', help='add the builds it fits to its targets')
    args = parser.parse_args(argv)
    try:
        if args.command == 'unpack':
            files = unpack(args.asset, args.folder, args.game)
            print(f'Unpacked {len(files)} files into {args.folder}. Edit them in place, keeping each file\'s size.')
        elif args.command == 'diff':
            edits, fits, misses = diff(args.folder, args.mod)
            print(f'Wrote {len(edits)} portable edits to {Path(args.mod) / "mod.json"}.')
            print('Fits: ' + ', '.join(f"{e['title_id']} {e['app_version']}" for e in fits))
            for other in misses:
                print(f"Does not fit {other['title_id']} {other['app_version']}: its bytes differ there; "
                      'unpack that build and make the change in it too.')
            print('Finding the bytes is not proof the change works: test the mod in each game build.')
        elif args.command == 'port':
            for asset, how in port(args.profile, args.to, args.output):
                print(f'{asset}: {how}')
            print(f'Wrote {args.output}. Test the mod in that build before relying on it.')
        else:
            results = check(args.mod, args.add)
            return 0 if any(status == 'fits' and listed == 'listed' for _, listed, status in results) else 1
    except (OSError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

# SPDX-License-Identifier: GPL-3.0-or-later
"""mod.json v1: one manifest format for every title, and the loader that plans it.

A mod is a folder holding mod.json. Built-in mods live in profiles/mods; the
user's own go in mods/ at the repository root, which is never tracked. Every
operation is pinned to an executable sha256 and carries expected bytes or an
expected source hash, so a mismatched build is refused before launch.

Operations:
  code-patch   executable file offset, expected and replacement bytes (the
               profiles/patches schema 1 entry format)
  asset-patch  tools/asset_mod recipe assets (archive path, source sha256,
               chunks with expected-byte edits), inline as `recipe` or in a
               recipe file named by `profile`
  host-option  SKY_* environment values for the native host
  generated    edits built at launch by a named host handler (for example
               from local artwork); `writes` lists whole files it replaces
"""
import json
from pathlib import Path
import re

try:
    from .asset_mod import relative_asset
except ImportError:
    from asset_mod import relative_asset

SCHEMA_VERSION = 1
BUILTIN = Path('profiles/mods')
USER = Path('mods')
IDENTIFIER = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
SHA256 = re.compile(r'[0-9a-f]{64}')
OPERATIONS = ('code-patch', 'asset-patch', 'host-option', 'generated')
PATCHES = 'profiles/patches/'
SETTING_TYPES = ('bool', 'choice', 'number')
HOST_OPTION = re.compile(r'SKY_[A-Z0-9_]{1,64}')


class ModError(ValueError):
    pass


def text(value, name, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ModError(f'{name} must be a nonempty string')
    return value


def hex_bytes(value, name):
    try:
        data = bytes.fromhex(value)
    except (TypeError, ValueError):
        raise ModError(f'{name} must be hex') from None
    return data


def check_setting(name, spec):
    if not IDENTIFIER.fullmatch(name) or not isinstance(spec, dict):
        raise ModError(f'invalid setting {name!r}')
    kind, default = spec.get('type'), spec.get('default')
    if kind not in SETTING_TYPES:
        raise ModError(f'setting {name} has unknown type {kind!r}')
    if kind == 'bool' and type(default) is not bool:
        raise ModError(f'setting {name} needs a boolean default')
    if kind == 'choice':
        choices = spec.get('choices')
        if (not isinstance(choices, list) or not choices or len(set(map(str, choices))) != len(choices) or
                not all(isinstance(item, str) for item in choices) or default not in choices):
            raise ModError(f'setting {name} needs unique string choices including its default')
    if kind == 'number':
        low, high = spec.get('min'), spec.get('max')
        if not all(type(item) in (int, float) for item in (low, high, default)) or not low <= default <= high:
            raise ModError(f'setting {name} needs numeric min <= default <= max')
    return spec


def setting_value(spec, value):
    kind = spec['type']
    if kind == 'bool':
        return type(value) is bool
    if kind == 'choice':
        return value in spec['choices']
    return type(value) in (int, float) and spec['min'] <= value <= spec['max']


def check_operation(operation, targets, settings, index):
    where = f'operation {index}'
    if not isinstance(operation, dict) or operation.get('type') not in OPERATIONS:
        raise ModError(f'{where} has an unknown type')
    kind = operation['type']
    # Operations apply to every declared target unless pinned to one hash.
    target = operation.get('target')
    if target is not None and target not in targets:
        raise ModError(f'{where} targets an undeclared executable')
    when = operation.get('when')
    if when is not None:
        if (not isinstance(when, dict) or set(when) != {'setting', 'equals'} or when['setting'] not in settings or
                not setting_value(settings[when['setting']], when['equals'])):
            raise ModError(f'{where} has an invalid setting condition')
    if kind == 'code-patch':
        if target is None:
            raise ModError(f'{where}: code patches must name one target executable')
        text(operation.get('id'), f'{where} id', 80)
        offset = operation.get('file_offset')
        if type(offset) is not int or offset < 0:
            raise ModError(f'{where} file_offset must be a nonnegative integer')
        before = hex_bytes(operation.get('expected_hex'), f'{where} expected_hex')
        after = hex_bytes(operation.get('replacement_hex'), f'{where} replacement_hex')
        if not before or len(before) != len(after):
            raise ModError(f'{where} must preserve byte length')
        text(operation.get('reason'), f'{where} reason', 2000)
    elif kind == 'asset-patch':
        if target is None:
            raise ModError(f'{where}: asset patches must name one target executable')
        if ('recipe' in operation) == ('profile' in operation):
            raise ModError(f'{where} needs exactly one of recipe or profile')
        if 'recipe' in operation:
            check_recipe(operation['recipe'], where)
        else:
            profile_path(operation['profile'], where)
    elif kind == 'generated':
        if target is None:
            raise ModError(f'{where}: generated operations must name one target executable')
        if not isinstance(operation.get('handler'), str) or not IDENTIFIER.fullmatch(operation['handler']):
            raise ModError(f'{where} needs a handler id')
        if 'profile' in operation:
            profile_path(operation['profile'], where)
        writes = operation.get('writes', [])
        if not isinstance(writes, list):
            raise ModError(f'{where} writes must be a list of game files')
        for item in writes:
            try:
                relative_asset(item)
            except (ValueError, TypeError):
                raise ModError(f'{where} writes an invalid path') from None
    else:
        environment = operation.get('environment')
        if not isinstance(environment, dict) or not environment:
            raise ModError(f'{where} needs an environment map')
        for key, value in environment.items():
            if not HOST_OPTION.fullmatch(key) or not isinstance(value, str) or len(value) > 256:
                raise ModError(f'{where} may only set SKY_* string values')
    return operation


def check_recipe(recipe, where):
    if not isinstance(recipe, dict) or not SHA256.fullmatch(str(recipe.get('source_sha256'))):
        raise ModError(f'{where} needs an asset recipe with source_sha256')
    try:
        relative_asset(recipe.get('asset'))
    except (ValueError, TypeError):
        raise ModError(f'{where} has an invalid asset path') from None
    chunks = recipe.get('chunks')
    if not isinstance(chunks, list) or not chunks:
        raise ModError(f'{where} recipe needs chunks')
    for chunk in chunks:
        if not isinstance(chunk, dict) or type(chunk.get('offset')) is not int or not isinstance(chunk.get('edits'), list) or not chunk['edits']:
            raise ModError(f'{where} has an invalid chunk')
        for edit in chunk['edits']:
            if not isinstance(edit, dict) or type(edit.get('offset')) is not int:
                raise ModError(f'{where} has an invalid edit')
            if 'copy_from' in edit:
                if type(edit.get('length')) is not int or edit['length'] <= 0:
                    raise ModError(f'{where} has an invalid copy edit')
            else:
                before = hex_bytes(edit.get('expected_hex'), f'{where} expected_hex')
                after = hex_bytes(edit.get('replacement_hex'), f'{where} replacement_hex')
                if not before or len(before) != len(after):
                    raise ModError(f'{where} edits must preserve byte length')


def profile_path(value, where):
    try:
        path = relative_asset(value)
    except (ValueError, TypeError):
        raise ModError(f'{where} has an invalid profile path') from None
    if path.suffix != '.json':
        raise ModError(f'{where} profile must be a .json file')
    return path


def locate(manifest, value):
    """Built-in mods name shared recipe files under profiles/patches; user
    mods name files inside their own folder."""
    if manifest.get('builtin'):
        if not value.startswith(PATCHES):
            raise ModError(f"mod {manifest['id']}: built-in profiles must live in {PATCHES}")
        return Path(manifest['root']) / value
    return Path(manifest['source']) / value


def load_profile(manifest, value, executable_sha256):
    path = locate(manifest, value)
    if not path.is_file():
        raise ModError(f"mod {manifest['id']}: {value} is unavailable in this checkout; see profiles/patches/README.md")
    try:
        profile = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ModError(f"mod {manifest['id']}: {value}: {error}") from None
    if not isinstance(profile, dict) or profile.get('executable_sha256') != executable_sha256:
        raise ModError(f"mod {manifest['id']}: {value} targets a different executable")
    return path, profile


def parse(data, source=None):
    """Validate one manifest object; returns it unchanged with its source folder."""
    if not isinstance(data, dict) or data.get('schema_version') != SCHEMA_VERSION:
        raise ModError('unsupported mod.json schema_version (expected 1)')
    ident = data.get('id')
    if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident):
        raise ModError('mod id must be lowercase letters, digits and dashes')
    for key in ('name', 'version', 'author', 'licence'):
        text(data.get(key), f'{ident}: {key}')
    targets = data.get('targets')
    if not isinstance(targets, list) or not targets:
        raise ModError(f'{ident}: targets must list at least one build')
    hashes = {}
    for target in targets:
        if not isinstance(target, dict):
            raise ModError(f'{ident}: invalid target')
        text(target.get('title_id'), f'{ident}: target title_id', 16)
        text(target.get('app_version'), f'{ident}: target app_version', 16)
        digest = target.get('executable_sha256')
        if not isinstance(digest, str) or not SHA256.fullmatch(digest) or digest in hashes:
            raise ModError(f'{ident}: targets need unique lowercase executable_sha256 values')
        hashes[digest] = target
    for key in ('requires', 'conflicts'):
        items = data.get(key, [])
        if not isinstance(items, list) or not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in items) or ident in items:
            raise ModError(f'{ident}: {key} must list other mod ids')
    settings = data.get('settings', {})
    if not isinstance(settings, dict):
        raise ModError(f'{ident}: settings must be an object')
    for name, spec in settings.items():
        check_setting(name, spec)
    operations = data.get('operations')
    if not isinstance(operations, list) or not operations or len(operations) > 4096:
        raise ModError(f'{ident}: operations must list 1..4096 entries')
    for index, operation in enumerate(operations):
        try:
            check_operation(operation, hashes, settings, index)
        except ModError as error:
            raise ModError(f'{ident}: {error}') from None
    return dict(data, source=str(source) if source else None)


def read(folder):
    path = Path(folder) / 'mod.json'
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ModError(f'{path}: {error}') from None
    return parse(data, Path(folder))


def discover(root):
    """Built-in mods first, then the user's mods/ folder. Duplicate ids are refused."""
    found = {}
    for base in (Path(root) / BUILTIN, Path(root) / USER):
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir()):
            if not (folder / 'mod.json').is_file():
                continue
            manifest = read(folder)
            if manifest['id'] in found:
                raise ModError(f"mod id {manifest['id']} is defined by both {found[manifest['id']]['source']} and {folder}")
            manifest['builtin'] = base == Path(root) / BUILTIN
            manifest['root'] = str(root)
            found[manifest['id']] = manifest
    return found


def order(selected, available):
    """Requires first, ties by id; refuses missing requirements, cycles and declared conflicts."""
    wanted, pending = set(), list(selected)
    while pending:
        ident = pending.pop()
        if ident in wanted:
            continue
        if ident not in available:
            raise ModError(f'mod {ident} is not installed')
        wanted.add(ident)
        pending.extend(available[ident].get('requires', []))
    for ident in sorted(wanted):
        for other in available[ident].get('conflicts', []):
            if other in wanted:
                raise ModError(f'mod {ident} conflicts with mod {other}')
    result, done, visiting = [], set(), set()

    def visit(ident):
        if ident in done:
            return
        if ident in visiting:
            raise ModError(f'mod {ident} has a circular requirement')
        visiting.add(ident)
        for need in sorted(available[ident].get('requires', [])):
            visit(need)
        visiting.discard(ident)
        done.add(ident)
        result.append(ident)
    for ident in sorted(wanted):
        visit(ident)
    return result


def supports(available, ident, executable_sha256):
    manifest = available.get(ident)
    return bool(manifest) and any(item['executable_sha256'] == executable_sha256 for item in manifest['targets'])


def resolve_settings(manifest, values):
    settings, chosen = manifest.get('settings', {}), {}
    for name, spec in settings.items():
        chosen[name] = spec['default']
    for name, value in (values or {}).items():
        if name not in settings or not setting_value(settings[name], value):
            raise ModError(f"mod {manifest['id']}: invalid value for setting {name}")
        chosen[name] = value
    return chosen


WHOLE = float('inf')


def recipe_ranges(recipe):
    for chunk in recipe['chunks']:
        for edit in chunk['edits']:
            size = edit['length'] if 'copy_from' in edit else len(bytes.fromhex(edit['expected_hex']))
            # Edits address decoded chunk bytes; key ranges by archive and chunk.
            yield (recipe['asset'], chunk['offset'], edit['offset'], edit['offset'] + size)


def edit_ranges(operation):
    """(file, chunk, start, end) byte ranges an operation writes, for overlap checks.
    chunk is None for raw file bytes; a whole-file write spans every chunk."""
    if operation['type'] == 'code-patch':
        start = operation['file_offset']
        yield ('eboot.bin', None, start, start + len(bytes.fromhex(operation['expected_hex'])))
    elif operation['type'] == 'generated':
        for path in operation.get('writes', []):
            yield (path, None, 0, WHOLE)
    else:
        for recipe in operation['recipes']:
            yield from recipe_ranges(recipe)


def claim(writes, ident, ranges):
    """Record ranges for mod ident, refusing any overlap with another write."""
    for path, chunk, start, end in ranges:
        for other, other_path, other_chunk, other_start, other_end in writes:
            if path != other_path:
                continue
            whole = end == WHOLE or other_end == WHOLE
            if whole or (chunk == other_chunk and start < other_end and other_start < end):
                who = f'mods {other} and {ident}' if other != ident else f'mod {ident}'
                if whole:
                    raise ModError(f'{who} both change {path}')
                where = path if chunk is None else f'{path} chunk {chunk}'
                raise ModError(f'{who} both change bytes {max(start, other_start)}..{min(end, other_end)} of {where}')
        writes.append((ident, path, chunk, start, end))


def plan(available, selected, executable_sha256, settings=None, executable=None, writes=None):
    """Check selected mods against one build; returns ordered, conflict-free operations.

    executable: original eboot bytes, required when a code patch is selected so
    its expected bytes are compared before launch. writes: a list that receives
    every claimed byte range, so edits generated later can be checked with claim().
    """
    settings = settings or {}
    writes = [] if writes is None else writes
    applied, environment = [], {}
    for ident in order(selected, available):
        manifest = available[ident]
        target = next((item for item in manifest['targets'] if item['executable_sha256'] == executable_sha256), None)
        if target is None:
            raise ModError(f"mod {ident} does not support this game build (executable sha256 {executable_sha256[:12]}…)")
        chosen = resolve_settings(manifest, settings.get(ident))
        operations = []
        for operation in manifest['operations']:
            if operation.get('target', executable_sha256) != executable_sha256:
                continue
            when = operation.get('when')
            if when and chosen[when['setting']] != when['equals']:
                continue
            if operation['type'] == 'code-patch':
                if executable is None:
                    raise ModError(f'mod {ident}: code patches need the original executable')
                start, before = operation['file_offset'], bytes.fromhex(operation['expected_hex'])
                if executable[start:start + len(before)] != before:
                    raise ModError(f"mod {ident}: original bytes mismatch for {operation['id']}")
            if operation['type'] == 'asset-patch':
                if 'profile' in operation:
                    path, profile = load_profile(manifest, operation['profile'], executable_sha256)
                    recipes = profile.get('assets')
                    if not isinstance(recipes, list) or not recipes:
                        raise ModError(f"mod {ident}: {operation['profile']} has no assets")
                    for recipe in recipes:
                        check_recipe(recipe, f"mod {ident}: {operation['profile']}")
                else:
                    recipes = [operation['recipe']]
                operation = dict(operation, recipes=recipes)
            if operation['type'] == 'generated' and 'profile' in operation:
                path, _ = load_profile(manifest, operation['profile'], executable_sha256)
                operation = dict(operation, profile_path=str(path))
            if operation['type'] == 'host-option':
                for key, value in operation['environment'].items():
                    owner = environment.get(key)
                    if owner and owner[1] != value:
                        raise ModError(f'mods {owner[0]} and {ident} both set {key}')
                    environment[key] = (ident, value)
            else:
                claim(writes, ident, list(edit_ranges(operation)))
            operations.append(operation)
        if not operations:
            raise ModError(f'mod {ident} has no operations for this game build')
        applied.append(dict(id=ident, name=manifest['name'], version=manifest['version'],
                            builtin=manifest.get('builtin', False), title_id=target['title_id'],
                            app_version=target['app_version'], settings=chosen, operations=operations))
    return applied


def asset_profile(applied, title_id, app_version, executable_sha256):
    """The asset-patch operations as one asset_mod profile, or None."""
    assets = [recipe for mod in applied for operation in mod['operations']
              if operation['type'] == 'asset-patch' for recipe in operation['recipes']]
    if not assets:
        return None
    return dict(schema_version=2, executable_sha256=executable_sha256, title_id=title_id,
                app_version=app_version, assets=assets)


def generated(applied):
    """(mod, operation) pairs for host handlers, in load order."""
    return [(mod, operation) for mod in applied for operation in mod['operations'] if operation['type'] == 'generated']


def host_environment(applied):
    return {key: value for mod in applied for operation in mod['operations']
            if operation['type'] == 'host-option' for key, value in operation['environment'].items()}


def record(applied):
    """Session metadata: what each mod changed, without bulk recipe data."""
    def summary(operation):
        if operation['type'] == 'code-patch':
            return dict(type='code-patch', id=operation['id'], file_offset=operation['file_offset'])
        if operation['type'] == 'asset-patch':
            return dict(type='asset-patch', assets=[recipe['asset'] for recipe in operation['recipes']],
                        **({'profile': operation['profile']} if 'profile' in operation else {}))
        if operation['type'] == 'generated':
            return dict(type='generated', handler=operation['handler'], writes=operation.get('writes', []))
        return dict(type='host-option', environment=sorted(operation['environment']))
    return [dict({key: value for key, value in mod.items() if key != 'operations'},
                 operations=[summary(item) for item in mod['operations']]) for mod in applied]

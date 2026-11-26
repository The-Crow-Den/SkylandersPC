# Mods

A mod is a folder with a `mod.json` manifest. `tools/mod_manifest.py` reads it,
checks it against the selected game build and plans what it changes before the
game starts. The same format serves every title.

- Built-in mods live here, in `profiles/mods/<id>/mod.json`. They hold hashes,
  offsets and expected bytes only, never game files.
- Your own mods go in `mods/<id>/mod.json` at the repository root. That folder
  is ignored by Git. Never commit game data, keys, saves or extracted assets
  into a mod.

Mod ids must be unique across both folders.

## Turning mods on

```bash
python3 tools/run_session.py --mod nightmare --mod my-mod
```

`--mod ID` can be repeated. The built-in mods keep their older options, which
now just select the mod:

| Mod id | Option | What it does |
| --- | --- | --- |
| `nightmare` | `--unlock-nightmare` (on by default) | Nightmare selectable on a new save |
| `sixty-fps` | `--mod sixty-fps`, or `--frame-policy auto` (on by default in the launcher) | 60 FPS with elapsed-time simulation; setting `automatic` (default `true`) keeps menus, cutscenes and portal arrival at 30, `false` caps everything at 60 |
| `level-events` | `--level-events`, or required by `sixty-fps` | Level-switch hooks for automatic FPS |
| `controller-glyphs` | `--controller-glyphs xbox\|nintendo\|auto` | Xbox or Nintendo button prompts from imported Steam artwork |
| `trap-master` | `--mod trap-master` | Experimental: no Trap Master needed, with settings `elemental-gates` and `traptanium` (both on); replaces `element-gates` and `traptanium`. The Traptanium recipe is left out of source exports |
| `unlock-expansions` | `--unlock-expansions` | Experimental, with settings `unlock-adventure-packs` (pack access without toys) and `replay-introductions` (a pack's introduction replays from its Academy statue), both on; replaces `replay-expansion-intros` |
| `skip-cutscenes` | `--mod skip-cutscenes` | Cross or Options ends any movie (US 01.01 host hook) |

The launcher's **Mods** page (in a game's settings) lists every mod found in
both folders, shows whether it works with the installed version, and has a
switch and the declared settings for each one. Choices are saved per game in
the launcher library and passed as `--mod ID` and
`--mod-setting ID.NAME=JSON` (for example `my-mod.strength="high"`). Built-in
mods that follow another option show which option controls them. **Open mods
folder** creates `mods/` if needed. A requested mod
that is missing, does not support the build, or clashes with another mod stops
the launch with an error before anything is changed. Mods a mod `requires` are
turned on with it.

Each session's `session.json` lists the applied mods under `mods`: id, version,
build, settings and a short summary of each operation.

## mod.json v1

```json
{
  "schema_version": 1,
  "id": "my-mod",
  "name": "My mod",
  "version": "1.0.0",
  "author": "Your name",
  "licence": "GPL-3.0-or-later",
  "targets": [
    {"title_id": "CUSA00626", "app_version": "01.01",
     "executable_sha256": "<sha256 of the original eboot.bin>"}
  ],
  "requires": [],
  "conflicts": [],
  "settings": {
    "strength": {"type": "choice", "choices": ["low", "high"], "default": "low"}
  },
  "operations": [ ... ]
}
```

- `id`: lowercase letters, digits and dashes, up to 64 characters.
- `name`, `version`, `author`, `licence`: required, nonempty text.
- `targets`: every build the mod supports. The selected build's executable
  sha256 must be listed or the mod is refused.
- `requires` / `conflicts`: other mod ids. Required mods apply first; a declared
  conflict refuses the launch.
- `settings`: `bool` (`default` true/false), `choice` (`choices` list of
  strings, `default` one of them) or `number` (`min`, `max`, `default`).
  Settings choose which operations run, through `when` (below). The launcher
  does not show per-mod settings yet.

### Operations

Every operation may have `"when": {"setting": "<name>", "equals": <value>}`;
it then runs only when that setting has that value. A mod with no operations
left for the selected build and settings is refused.

**`asset-patch`**: expected-byte edits inside game archives. `target` is the
executable sha256 it belongs to. Give either `recipe`, one asset entry in the
`tools/asset_mod.py` recipe format, or `profile`, a recipe file whose `assets`
list holds such entries and whose `executable_sha256` matches the target. A
built-in mod's `profile` is a path under `profiles/patches/`; a user mod's is a
path inside its own folder. A missing recipe file is reported as unavailable.
Inline example:

```json
{"type": "asset-patch", "target": "<sha256>", "recipe": {
  "asset": "level/title.bld",
  "source_sha256": "<sha256 of the original archive>",
  "chunks": [{"offset": 1038336, "allocation": 4096, "encoding": "raw-lzma", "...": "...",
              "edits": [{"offset": 32476, "expected_hex": "284e0200", "replacement_hex": "d8c40600"}]}]}}
```

The archive is refused if its hash differs; each edit is refused if the bytes
at its offset differ from `expected_hex`. Replacement bytes keep the original
length. `profiles/mods/nightmare/mod.json` is a complete example.

**`asset-find`**: portable edits inside a game archive, found by content
instead of offsets, so one operation can fit several builds of a game. It
applies to every build in `targets` (narrow it with `title_id`). At launch each
edit is searched for in the installed archive and turned into an exact
`asset-patch` recipe, so every hash and expected-byte check above still runs.
`tools/make_mod.py` writes these for you; the format is:

```json
{"type": "asset-find", "asset": "level/title.bld", "edits": [
  {"member": "level.bld", "find_hex": "f0fd15?? 0000 284e0200", "at": 6, "replacement_hex": "d8c4"},
  {"member": "level.bld", "find_hex": "...", "at": 32, "length": 8,
   "copy": {"member": "level.bld", "find_hex": "...", "at": 32}}]}
```

- `find_hex` is hex (spaces allowed) with `??` for bytes that differ between
  builds. It must match exactly once in the archive's decoded files, within one
  32 KiB block, or the mod is refused for that build.
- `at` is where the change starts inside the match. The bytes it replaces must
  not be wildcards: they are the expected bytes.
- The new bytes are either `replacement_hex` or `copy`: read `length` bytes at
  `at` inside another unique match. Use `copy` for values that differ per build,
  such as pointers, by copying them from where the game already holds them.
- `member` (optional) limits the search to one file inside the archive.

`profiles/mods/nightmare/mod.json` uses one `asset-find` edit for both US
builds.

**`code-patch`**: an edit to the executable, using the entry format of
`profiles/patches/*.json` (schema 1):

```json
{"type": "code-patch", "target": "<sha256>", "id": "skip-intro",
 "file_offset": 123456, "expected_hex": "7405", "replacement_hex": "eb05",
 "reason": "Why this change is needed."}
```

`file_offset` is a file offset, not a virtual address. Code patches are
checked against the original executable, but launching with one is refused
for now: the game runs from pre-translated code, and there is no step yet that
applies executable patches to it.

**`generated`**: edits a host step builds at launch, for changes that cannot
be stored as fixed bytes (they depend on local artwork, or rewrite whole
files). `handler` names the step; `profile` is its data file, found the same
way as above; `writes` lists game files it replaces whole, so another mod
editing those files is refused. The handlers are `level-events` (patches the
translated code pack) and `controller-glyphs` (draws prompts into the font and
title archives; its edits are checked for overlaps once built). A mod naming
any other handler is refused.

```json
{"type": "generated", "handler": "controller-glyphs", "target": "<sha256>",
 "profile": "profiles/patches/trap-team-us-01.01-controller-glyphs.json"}
```

The movie narration fix and the game language are not mods: they are session
options (`--movie-audio`, `--language`) that every player gets.

**`host-option`**: environment values for the native host. Only `SKY_*` names
with string values are allowed:

```json
{"type": "host-option", "environment": {"SKY_EXAMPLE": "1"}}
```

### Conflicts between mods

Before launch the loader collects every byte each selected mod writes. Two mods
that change the same executable bytes, or the same bytes of the same archive
chunk, are refused with an error naming both. Edits to different bytes of one
archive are combined into a single preparation. A file listed in a generated
operation's `writes` belongs to that mod alone. Two mods setting one
host option to different values are refused the same way.

## Making a data mod

`tools/make_mod.py` makes `asset-find` edits from files you edit, so you never
write offsets or hashes:

```bash
python3 tools/make_mod.py unpack level/title.bld out/mod-work/title
```

Edit the unpacked files in place with any tool, keeping each file's size, then:

```bash
python3 tools/make_mod.py diff out/mod-work/title mods/my-mod
```

`diff` writes the edits into `mods/my-mod/mod.json`, creating it if needed
(fill in its name, author and licence). It tries every installed build of the
game: patterns get `??` for pointer-like values that moved, and a changed
pointer is copied from where each build holds it. It lists the builds the mod
fits and adds them to `targets`. To try the mod on builds installed later:

```bash
python3 tools/make_mod.py check mods/my-mod --add
```

An existing recipe file can be carried to another installed build:

```bash
python3 tools/make_mod.py port profiles/patches/x-01.01.json --to CUSA00626@01.00 -o x-01.00.json
```

Archives the update did not replace are reused as they are; blocks whose
content is unchanged keep their edits at their new position; other changes are
found again by content. A change whose original value is a pointer that moved
is *relocated*: its place is found with pointers masked, the target's own bytes
become the expected bytes, and the new value must already occur in the target
file. Review relocated edits. This is how Trap Master, Unlock Expansions and
the controller prompts gained US 01.00 support.

A build "fits" when every edit is found exactly once with the expected bytes;
that does not prove the change does the same thing there. Play each build
before sharing the mod. Unpacked files are the game's own data: keep them in
`out/` or another ignored folder and never share them. `diff` takes 10–60
seconds on a large archive.

## Finding addresses

Work from your own legally obtained copy. Record only what a mod needs to be
checked and applied: hashes, offsets, the original bytes and the replacement.
Do not add decompiled code, disassembly listings or extracted assets to the
repository or to a mod you share.

1. Hash the executable (`sha256sum eboot.bin`) and confirm it is a build listed
   in `profiles/<game>.json`.
2. For asset edits, note the archive path and its sha256, then the chunk offset
   and the edit offset within the decoded chunk. `tools/asset_mod.py` documents
   the chunk fields.
3. Copy the current bytes into `expected_hex` and write the same number of
   bytes into `replacement_hex`.
4. Run the mod once and read `out/last-session/session.json` to confirm it was
   applied.

## Testing

`tests/test_mod_manifest.py` covers parsing, build and byte refusal, ordering
and conflicts with synthetic data; `tests/test_archive_blocks.py` and
`tests/test_make_mod.py` cover portable edits with synthetic archives. Run all tests with:

```bash
python3 -m unittest discover -s tests
```

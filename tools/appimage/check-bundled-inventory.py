#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail when the AppImage AppDir carries an ELF file LICENSES/bundled-components.json does not list.

    tools/appimage/check-bundled-inventory.py out/appimage-build/AppDir
"""
import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def unlisted(appdir, inventory):
    # fnmatch's '*' also crosses '/', so '**' globs in the inventory work as written.
    patterns = [p for component in inventory['components'] for p in component.get('paths', ())]
    missing = []
    for path in sorted(appdir.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as handle:
            if handle.read(4) != b'\x7fELF':
                continue
        name = path.relative_to(appdir).as_posix()
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
            missing.append(name)
    return missing


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit(__doc__.strip())
    inventory = json.loads((ROOT / 'LICENSES/bundled-components.json').read_text())
    missing = unlisted(Path(args[0]), inventory)
    for name in missing:
        print('Not in LICENSES/bundled-components.json:', name, file=sys.stderr)
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())

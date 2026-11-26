#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail when the Windows bundle carries a binary no license inventory lists.

    python tools/windows_inventory_check.py out/SkylandersPC-windows

Binaries are files starting with 'MZ' (exe, dll, pyd). Each must match a path
pattern in LICENSES/windows-bundled-components.json or be a file listed in the
bundle's generated LICENSES/msys2-runtime.json.
"""
import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def unlisted(bundle, inventory, msys2):
    patterns = [p for component in inventory['components'] for p in component.get('paths', ())]
    listed = {entry['file'] for entry in msys2}
    missing = []
    for path in sorted(Path(bundle).rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as handle:
            if handle.read(2) != b'MZ':
                continue
        name = path.relative_to(bundle).as_posix()
        if name in listed or any(fnmatch.fnmatchcase(name.lower(), p.lower()) for p in patterns):
            continue
        missing.append(name)
    return missing


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit(__doc__.strip())
    bundle = Path(args[0])
    inventory = json.loads((ROOT / 'LICENSES/windows-bundled-components.json').read_text(encoding='utf-8'))
    generated = bundle / 'LICENSES/msys2-runtime.json'
    msys2 = json.loads(generated.read_text(encoding='utf-8')) if generated.is_file() else []
    bad = [e['file'] for e in msys2 if not e.get('license') or not e.get('package')]
    for name in bad:
        print('MSYS2 file without package/license:', name, file=sys.stderr)
    missing = unlisted(bundle, inventory, msys2)
    for name in missing:
        print('Not in any Windows license inventory:', name, file=sys.stderr)
    return 1 if missing or bad else 0


if __name__ == '__main__':
    sys.exit(main())

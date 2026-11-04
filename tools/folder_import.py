# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy an already unpacked game or update folder into installer staging.

The installer publishes by moving staged files into the library, so a folder the
player chose is copied first and their original stays where it is.
"""
import argparse
from pathlib import Path
import shutil
import sys


def import_folder(source, out_dir, progress=print):
    source = Path(source).resolve()
    if not (source / 'sce_sys/param.sfo').is_file():
        raise ValueError(f'{source} is not an unpacked PS4 game or update (no sce_sys/param.sfo)')
    files = [p for p in source.rglob('*') if not p.is_dir()]
    if any(p.is_symlink() for p in [source, *files]):
        raise ValueError('Unpacked folders cannot contain symlinks')
    total = sum(p.stat().st_size for p in files) or 1
    target = Path(out_dir) / source.name
    target.mkdir(parents=True)
    done = shown = 0
    for path in files:
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        done += path.stat().st_size
        percent = 100 * done // total
        if percent >= shown + 5 or done == total:
            shown = percent
            progress(f'Copied {percent}% ({len(files)} files)')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    parser.add_argument('out_dir')
    args = parser.parse_args()
    try:
        import_folder(args.folder, args.out_dir, progress=lambda line: print(line, flush=True))
    except (OSError, ValueError) as error:
        print('Copy failed: ' + str(error), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

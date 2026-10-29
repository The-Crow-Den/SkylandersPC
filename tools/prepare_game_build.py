# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility command; preparation is implemented by game_prepare."""
import argparse
from pathlib import Path
try:
    from . import game_prepare, game_library, game_build
except ImportError:
    import game_prepare, game_library, game_build

ROOT = Path(__file__).resolve().parents[1]


def prepare(root, variant, game=None):
    entry = game_library.resolve_entry(root,game)
    game_prepare.prepare(root,entry)
    return game_build.configuration(root,game_library.discover(entry),variant)['pack']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=('original','60','60-delta'),default='60-delta')
    parser.add_argument('--game')
    args = parser.parse_args()
    try:prepare(ROOT,args.variant,args.game)
    except (OSError,ValueError) as error:parser.error(str(error))


if __name__=='__main__':main()

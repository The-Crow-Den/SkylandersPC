# SPDX-License-Identifier: GPL-3.0-or-later
"""Play without the launcher window: start a game straight away.

    SkylandersPC.exe --play [GAME]                 (Windows)
    SkylandersPC.AppImage --play [GAME]            (Linux)
    python3 tools/play.py [GAME]                   (source checkout)

GAME is a game id such as trap-team (the default). The game runs with the
settings, mods and portal choice last saved in the launcher, so the launcher is
only needed to install a game or change those. This is the command to add to
Steam as a non-Steam game, or to a desktop shortcut. If setup needs finishing
(for example, the game host changed after an update), it runs first.
"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
try:
    from . import game_library, game_prepare, launcher_library, launcher_model, launcher_mods, user_data
except ImportError:
    import game_library, game_prepare, launcher_library, launcher_model, launcher_mods, user_data


def find_game(root, wanted):
    """The library entry for a game id, with its installation filled in."""
    library = launcher_library.load(user_data.path(root, '.local/launcher-library.json'))
    launcher_library.sync_installations(root, library)
    game = next((g for g in library['games'] if g['id'] == wanted), None)
    if game is None:
        known = ', '.join(g['id'] for g in library['games'] if g.get('installation'))
        raise SystemExit(f'Unknown game {wanted!r}. Installed: {known or "none"}.')
    if not game.get('installation'):
        raise SystemExit(f'{game["name"]} is not installed. Install it in the launcher first.')
    return game


def command(root, game, python=sys.executable):
    """The run_session command the launcher's Play button would use."""
    universal = launcher_model.load(user_data.path(root, '.local/launcher-settings.json'))
    value = launcher_model.validate({**universal, **game.get('settings', {})})
    return launcher_model.command(root, python, value, mods=launcher_mods.selection(root, game), game=game,
                                  mod_settings=game.get('mod_settings'))


def ready(root, game):
    """Finish setup if it needs it (only changed steps run). True when ready."""
    entry = game_library.resolve_entry(root, game=game)
    try:
        game_prepare.require_ready(root, entry, deep=False)
        return True
    except (OSError, ValueError):
        print('Finishing setup before starting…', file=sys.stderr)
        selector = game_library.selector(entry['title_id'], entry['app_version'])
        return subprocess.run([sys.executable, str(Path(root)/'tools/game_prepare.py'), '--game', selector], cwd=root).returncode == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('game', nargs='?', default='trap-team', help='game id (default: trap-team)')
    parser.add_argument('--print', action='store_true', help='show the command instead of running it')
    args = parser.parse_args(argv)
    try:
        report = user_data.migrate(ROOT)
        if report['conflicts']:print('Kept in their old place (different copies exist):', *report['conflicts'], sep='\n  ', file=sys.stderr)
    except OSError as error:
        print(f'Could not move your data to the SkylandersPC folder: {error}', file=sys.stderr)
    game = find_game(ROOT, args.game)
    argv = command(ROOT, game)
    if args.print:
        print(subprocess.list2cmdline(argv) if sys.platform == 'win32' else ' '.join(argv))
        return 0
    if not ready(ROOT, game):
        print('Setup could not finish. Open the launcher and choose Repair.', file=sys.stderr)
        return 1
    return subprocess.run(argv, cwd=ROOT).returncode


if __name__ == '__main__':
    sys.exit(main())

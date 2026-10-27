#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Entry point of the standalone launcher AppImage. The image carries only a
# relocatable CPython with the launcher's Python packages; the launcher, the
# runner and every tool still run from the repository checkout, so editing
# tools/ needs no rebuild. Child sessions reuse this interpreter through
# sys.executable, which stays valid while the launcher keeps the image mounted.
#
#   Skylanders-Launcher.AppImage [launcher arguments]
#   Skylanders-Launcher.AppImage --python [python arguments]
set -eu
here="${APPDIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
python="$here/usr/python/bin/python3"

is_root() {
    [ -f "$1/tools/launcher.py" ] && [ -f "$1/tools/run_session.py" ]
}

find_root() {
    if [ -n "${SKYLANDERS_ROOT:-}" ]; then
        if is_root "$SKYLANDERS_ROOT"; then printf '%s\n' "$SKYLANDERS_ROOT"; return 0; fi
        echo "SKYLANDERS_ROOT does not contain tools/launcher.py: $SKYLANDERS_ROOT" >&2
        return 1
    fi
    # Next to the image, inside a SkylandersPS4 folder beside it, or any parent.
    directory="$(dirname -- "${APPIMAGE:-$here}")"
    while :; do
        for candidate in "$directory" "$directory/SkylandersPS4"; do
            if is_root "$candidate"; then printf '%s\n' "$candidate"; return 0; fi
        done
        [ "$directory" = / ] && break
        directory="$(dirname -- "$directory")"
    done
    # The checkout the image was built from.
    if [ -f "$here/usr/share/skylanders/root" ]; then
        candidate="$(cat "$here/usr/share/skylanders/root")"
        if is_root "$candidate"; then printf '%s\n' "$candidate"; return 0; fi
    fi
    echo 'Cannot find the SkylandersPS4 checkout. Put the AppImage in or beside it, or set SKYLANDERS_ROOT.' >&2
    return 1
}

# Only the bundled interpreter and packages: ignore the host's Python setup.
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP
export PYTHONNOUSERSITE=1

if [ "${1:-}" = --python ]; then
    shift
    exec "$python" "$@"
fi
root="$(find_root)"
cd "$root"
exec "$python" "$root/tools/launcher.py" "$@"

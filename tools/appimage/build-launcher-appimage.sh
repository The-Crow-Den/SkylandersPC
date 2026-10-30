#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the standalone launcher AppImage: a relocatable CPython plus the pinned
# packages in requirements.txt, entered through AppRun.sh. Build needs uv, curl,
# sha256sum and python3; running the result needs none of them. Every download is
# pinned and hash-checked. Output and caches stay in ignored out/.
#
#   tools/appimage/build-launcher-appimage.sh [output.AppImage]
set -euo pipefail

PYTHON_BUILD=cpython-3.14.10-linux-x86_64-gnu
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

here="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(CDPATH= cd -- "$here/../.." && pwd)"
work="$root/out/appimage-build"
cache="$work/cache"
appdir="$work/AppDir"
output="${1:-$root/out/dist/Skylanders-Launcher-x86_64.AppImage}"

for tool in uv curl sha256sum python3; do
    command -v "$tool" >/dev/null || { echo "Building needs $tool on PATH." >&2; exit 1; }
done

fetch() {  # url sha256 destination
    if [ -f "$3" ] && echo "$2  $3" | sha256sum --check --status; then return; fi
    curl --fail --location --silent --show-error --output "$3.part" "$1"
    echo "$2  $3.part" | sha256sum --check --status || { echo "Checksum mismatch: $1" >&2; rm -f "$3.part"; exit 1; }
    mv "$3.part" "$3"; chmod +x "$3"
}

mkdir -p "$cache" "$(dirname -- "$output")"
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" "$cache/appimagetool"
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" "$cache/runtime"
uv python install --no-bin --no-registry --install-dir "$cache/python" "$PYTHON_BUILD"

rm -rf "$appdir"
mkdir -p "$appdir/usr/share/skylanders" "$appdir/usr/share/licenses"
cp -a "$cache/python/$PYTHON_BUILD" "$appdir/usr/python"
python="$appdir/usr/python/bin/python3"
# The interpreter is private to the image; uv's marker only guards shared installs.
rm -f "$appdir"/usr/python/lib/python3*/EXTERNALLY-MANAGED
rm -rf "$appdir"/usr/python/lib/python3*/test "$appdir"/usr/python/lib/python3*/idlelib
uv pip install --python "$python" --require-hashes --only-binary :all: --link-mode copy \
    --compile-bytecode -r "$here/requirements.txt"

# Trim to what the launcher uses: QtCore, QtGui and QtWidgets with their platform
# plugins, and the interpreter without Tk, pip, headers, terminfo or the shared
# libpython the statically linked python3 does not load.
python_lib=("$appdir"/usr/python/lib/python3*)
rm -rf "$appdir"/usr/python/{include,share} "$appdir"/usr/python/lib/{libpython3*,libtcl*,libtk*,tcl*,tk*,itcl*,thread*,pkgconfig} \
    "${python_lib[0]}"/{tkinter,turtledemo,ensurepip,config-3*} "${python_lib[0]}"/lib-dynload/_tkinter* \
    "${python_lib[0]}"/site-packages/{pip,pip-*.dist-info}
find "$appdir/usr/python/bin" -type f ! -name 'python3*' -delete
find "$appdir/usr/python/bin" -type l ! -name 'python*' -delete
rm -f "$appdir"/usr/python/bin/python3*-config
"$python" - "${python_lib[0]}/site-packages/PyQt6" <<'EOF'
import pathlib, re, shutil, subprocess, sys
pyqt = pathlib.Path(sys.argv[1]); qt = pyqt / 'Qt6'
MODULES = {'QtCore', 'QtGui', 'QtWidgets', 'QtDBus'}
LIBS = re.compile(r'lib(Qt6(Core|Gui|Widgets|DBus|XcbQpa|WaylandClient|WlShellIntegration|Svg|OpenGL)|icu(data|i18n|uc))\.so')
PLUGINS = {'platforms', 'platformthemes', 'platforminputcontexts', 'imageformats', 'iconengines',
           'xcbglintegrations', 'wayland-decoration-client', 'wayland-graphics-integration-client',
           'wayland-shell-integration'}
for path in pyqt.iterdir():
    module = path.name.split('.')[0]
    if path.is_dir() and path.name not in ('Qt6', '__pycache__'):
        shutil.rmtree(path)
    elif path.is_file() and module.startswith('Qt') and module not in MODULES:
        path.unlink()
for path in qt.iterdir():
    if path.name not in ('lib', 'plugins'):
        shutil.rmtree(path) if path.is_dir() else path.unlink()
for path in (qt / 'lib').iterdir():
    if not LIBS.match(path.name):
        shutil.rmtree(path) if path.is_dir() else path.unlink()
for path in (qt / 'plugins').iterdir():
    if path.name not in PLUGINS:
        shutil.rmtree(path)
# A plugin needing a removed Qt library could never load: drop it, but never a core platform.
for path in sorted(pyqt.rglob('*.so*')):
    missing = [line.split()[0] for line in subprocess.run(['ldd', str(path)], capture_output=True, text=True).stdout.splitlines()
               if 'not found' in line and line.split()[0].startswith(('libQt6', 'libicu'))]
    if missing:
        if path.name in ('libqxcb.so', 'libqwayland.so') or 'plugins' not in path.relative_to(pyqt).parts:
            sys.exit(f'{path} needs removed Qt libraries: {missing}')
        print('Dropping', path.relative_to(qt), 'needs', ', '.join(missing)); path.unlink()
EOF
QT_QPA_PLATFORM=offscreen "$python" -c '
import cryptography.hazmat.primitives.ciphers
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication([]); QWidget().show(); app.processEvents()'

# Retained notices: the interpreter's licence and each package's dist-info.
cp "$appdir"/usr/python/lib/python3*/LICENSE.txt "$appdir/usr/share/licenses/CPython-LICENSE.txt"
cp "$root/LICENSE" "$appdir/usr/share/licenses/SkylandersPS4-LICENSE"
cp "$root/THIRD_PARTY_NOTICES.md" "$appdir/usr/share/licenses/"
"$python" - "$appdir/usr/share/licenses/python-packages.txt" <<'EOF'
import importlib.metadata, sys
with open(sys.argv[1], 'w') as out:
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        files = [str(f) for f in dist.files or () if 'licen' in str(f).lower() or 'copying' in str(f).lower()]
        out.write(f"{dist.metadata['Name']} {dist.version}: {dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'see licence files'}\n")
        out.write(''.join(f'  site-packages/{f}\n' for f in files))
EOF

install -m 755 "$here/AppRun.sh" "$appdir/AppRun"
printf '%s\n' "$root" > "$appdir/usr/share/skylanders/root"
cat > "$appdir/org.skylanders.Launcher.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Skylanders PC
Comment=Open the Skylanders game library
Exec=AppRun
Icon=org.skylanders.Launcher
Terminal=false
Categories=Game;
EOF
# The supplied launcher icon is private (.local/); fall back to a plain square.
if [ -f "$root/.local/app-icon/launcher.png" ]; then
    cp "$root/.local/app-icon/launcher.png" "$appdir/org.skylanders.Launcher.png"
else
    "$python" - "$appdir/org.skylanders.Launcher.png" <<'EOF'
import struct, sys, zlib
size = 64
def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
rows = b''.join(b'\0' + bytes((40, 110, 200, 255)) * size for _ in range(size))
png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
open(sys.argv[1], 'wb').write(png)
EOF
fi
ln -sf org.skylanders.Launcher.png "$appdir/.DirIcon"

# Every bundled binary must be inventoried with its licence and source.
python3 "$here/check-bundled-inventory.py" "$appdir"

ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$cache/appimagetool" --no-appstream \
    --runtime-file "$cache/runtime" "$appdir" "$output.part"
# Renaming keeps a running copy of the previous image intact.
mv -f "$output.part" "$output"
echo "Built $output"

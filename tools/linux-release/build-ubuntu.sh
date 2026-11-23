#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the Linux release runtime (game host + renderer) on Ubuntu 22.04, so it
# runs on any distro with glibc 2.35 or newer: Ubuntu 22.04+, Debian 12, Fedora,
# Arch, SteamOS. Libraries Ubuntu 22.04 lacks or ships too old are built from
# pinned commits into $DEPS (cacheable). Output: out/linux-runtime, laid out as
# the install folder expects, with every bundled library beside the host.
#
# CI runs it in an ubuntu:22.04 container. Locally:
#   docker run --rm -v "$PWD:/src" -w /src ubuntu:22.04 tools/linux-release/build-ubuntu.sh
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPS="${DEPS:-$ROOT/out/ubuntu-deps}"
BUILD="${BUILD:-$ROOT/out/ubuntu-build}"
OUT="$ROOT/out/linux-runtime"
JOBS="${JOBS:-$(nproc)}"
MAX_GLIBC=2.35

# name repository commit (tag in the comment)
PINS=(
  "sdl3 libsdl-org/SDL f00dc919ca35b9756316e86c4777392de442f9b2"            # release-3.4.20
  "fmt fmtlib/fmt 1be298e1bd68957e4cd352e1f676f00e07dcfb57"                 # 12.2.0
  "glslang KhronosGroup/glslang e1b562a8bed273a02f30b59b66a5d499793cede5"   # 16.6.0
  "ffmpeg FFmpeg/FFmpeg 8ae0b34901ba60a802f183ee75a250a9fc3e09a5"           # n8.0.3
  "zycore zyantific/zycore-c 0b2432ced0884fd152b471d97ecf0258ff4d859f"      # as LICENSES/dependencies.json
  "zydis zyantific/zydis a2278f1d254e492f6a6b39f6cb5d1f5d515659dc"          # v4.1.1
  "robin-map Tessil/robin-map 188c45569cc2a5dd768077c193830b51d33a5020"     # v1.3.0
  "vulkan-headers KhronosGroup/Vulkan-Headers 6802bb4733b63ed5efd3adb308a6c885ef180ea1"  # v1.4.363
  "vma GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator 1d8f600fd424278486eade7ed3e877c99f0846b1"
  "xbyak herumi/xbyak cd6bad3cad2e07a3e277c23d2b1f065320024717"
)

if [ "$(id -u)" = 0 ] && command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends software-properties-common gpg-agent ca-certificates curl git \
    pkg-config ninja-build make patchelf python3-pip nasm file binutils \
    libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxi-dev libxss-dev libxfixes-dev libxtst-dev libxinerama-dev libxkbcommon-dev \
    libwayland-dev wayland-protocols libegl-dev libdrm-dev libgbm-dev libvulkan-dev \
    libasound2-dev libpulse-dev libpipewire-0.3-dev libudev-dev libdbus-1-dev \
    libssl-dev libusb-1.0-0-dev libxxhash-dev libglm-dev zlib1g-dev
  add-apt-repository -y ppa:ubuntu-toolchain-r/test >/dev/null
  add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
  # The renderer uses C++23 "deducing this": Clang 19 (LLVM's own packages) with GCC 13's libstdc++.
  curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key | gpg --dearmor -o /usr/share/keyrings/llvm.gpg
  echo 'deb [signed-by=/usr/share/keyrings/llvm.gpg] http://apt.llvm.org/jammy/ llvm-toolchain-jammy-19 main' > /etc/apt/sources.list.d/llvm.list
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends gcc-13 g++-13 python3.11 clang-19 lld-19
  python3 -m pip install -q cmake==3.31.6
fi
export CC=gcc-13 CXX=g++-13
export PKG_CONFIG_PATH="$DEPS/lib/pkgconfig:$DEPS/lib/x86_64-linux-gnu/pkgconfig:$DEPS/share/pkgconfig"
export CMAKE_PREFIX_PATH="$DEPS"
export PATH="$DEPS/bin:$PATH"
mkdir -p "$DEPS/src" "$BUILD"
# In a container, hand the files back to the calling user however the build ends.
if [ -n "${HOST_UID:-}" ]; then trap 'chown -R "$HOST_UID" "$DEPS" "$BUILD" "$OUT" 2>/dev/null || true' EXIT; fi

fetch() {  # name -> $DEPS/src/name at the pinned commit
  local name repo commit
  for pin in "${PINS[@]}"; do set -- $pin; [ "$1" = "$name_wanted" ] && { name=$1 repo=$2 commit=$3; }; done
  local dir="$DEPS/src/$name"
  if [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" != "$commit" ]; then
    rm -rf "$dir"; git init -q "$dir"
    git -C "$dir" fetch -q --depth 1 "https://github.com/$repo.git" "$commit"
    git -C "$dir" checkout -q FETCH_HEAD
  fi
  test "$(git -C "$dir" rev-parse HEAD)" = "$commit"
  echo "$dir"
}
src() { name_wanted=$1 fetch; }
done_mark() { [ -f "$DEPS/.built-$1" ]; }
mark() { touch "$DEPS/.built-$1"; }
cmake_dep() {  # name [cmake options]
  local name=$1; shift
  done_mark "$name" && return
  local dir; dir=$(src "$name")
  cmake -S "$dir" -B "$BUILD/dep-$name" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$DEPS" -DCMAKE_PREFIX_PATH="$DEPS" \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON "$@"
  cmake --build "$BUILD/dep-$name" -j "$JOBS"; cmake --install "$BUILD/dep-$name"
  mark "$name"
}

cmake_dep sdl3 -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF
cmake_dep fmt -DFMT_TEST=OFF -DFMT_DOC=OFF -DBUILD_SHARED_LIBS=ON
cmake_dep glslang -DENABLE_OPT=OFF -DGLSLANG_TESTS=OFF -DBUILD_EXTERNAL=OFF -DENABLE_SPVREMAPPER=OFF
# Zydis builds its pinned Zycore from its own dependencies/ folder (its system-Zycore
# option links the wrong target name), but its installed zydis-config.cmake still looks
# Zycore up, so the same Zycore is installed on its own first.
cmake_dep zycore -DZYCORE_BUILD_SHARED_LIB=OFF
if ! done_mark zydis; then
  zycore=$(src zycore); zydis=$(src zydis)
  rm -rf "$zydis/dependencies/zycore"; mkdir -p "$zydis/dependencies"; cp -a "$zycore" "$zydis/dependencies/zycore"
fi
cmake_dep zydis -DZYDIS_BUILD_SHARED_LIB=OFF -DZYDIS_BUILD_TOOLS=OFF -DZYDIS_BUILD_EXAMPLES=OFF -DZYDIS_BUILD_DOXYGEN=OFF
cmake_dep robin-map
cmake_dep vulkan-headers
if ! done_mark ffmpeg; then
  # LGPL, shared, decoders and demuxers only; nothing auto-detected from the system.
  dir=$(src ffmpeg); mkdir -p "$BUILD/dep-ffmpeg"
  (cd "$BUILD/dep-ffmpeg" && "$dir/configure" --prefix="$DEPS" --enable-shared --disable-static --disable-programs \
     --disable-doc --disable-network --disable-autodetect --disable-encoders --disable-muxers --disable-devices \
     --disable-filters --enable-filter=aresample,scale,format,null,anull --cc=gcc-13 --cxx=g++-13 \
   && make -j "$JOBS" && make install)
  mark ffmpeg
fi
if ! done_mark boost; then
  # Header-only Boost 1.87 (Ubuntu 22.04's 1.74 containers aren't std::span-compatible).
  curl -fsSL -o "$DEPS/src/boost.tar.gz" https://archives.boost.io/release/1.87.0/source/boost_1_87_0.tar.gz
  echo "f55c340aa49763b1925ccf02b2e83f35fdcf634c9d5164a2acb87540173c741d  $DEPS/src/boost.tar.gz" | sha256sum --check --status
  tar -xzf "$DEPS/src/boost.tar.gz" -C "$DEPS/src" boost_1_87_0/boost boost_1_87_0/LICENSE_1_0.txt
  rm -rf "$DEPS/include/boost"; mv "$DEPS/src/boost_1_87_0/boost" "$DEPS/include/boost"; rm "$DEPS/src/boost.tar.gz"
  mark boost
fi
VMA=$(src vma); XBYAK=$(src xbyak)

export CC=clang-19 CXX=clang++-19 CXXFLAGS="-fbracket-depth=1024"  # Clang picks the newest GCC installed (13) for libstdc++
cmake -S "$ROOT/renderer/gpu" -B "$BUILD/renderer" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DSKY_RENDERER_LTO=OFF -DSKY_RENDERER_PGO=off -DVMA_INCLUDE_DIR="$VMA/include" \
  -DBOOST_ROOT="$DEPS" -DBoost_NO_SYSTEM_PATHS=ON -DBoost_INCLUDE_DIR="$DEPS/include" \
  -DVulkan_INCLUDE_DIR="$DEPS/include" -DCMAKE_CXX_FLAGS="$CXXFLAGS -isystem $XBYAK"
cmake --build "$BUILD/renderer" --target skyrender -j "$JOBS"
cmake -S "$ROOT/native" -B "$BUILD/native" -G Ninja -DCMAKE_BUILD_TYPE=Release -DSKY_TLS_PREFLIGHT=ON \
  -DPython3_EXECUTABLE=/usr/bin/python3.11 -DSKY_RENDERER_ROOT="$ROOT/renderer" \
  -DSKY_RENDERER_LIBRARY="$BUILD/renderer/libskyrender.so"
cmake --build "$BUILD/native" -j "$JOBS"
if [ "${SKIP_TESTS:-0}" != 1 ]; then ctest --test-dir "$BUILD/native" --output-on-failure; fi

# Bundle: every library they load except the system's own (glibc, graphics
# drivers, audio, display and device services), found through relative RUNPATHs.
rm -rf "$OUT"
host_dir="$OUT/.local/native-gpu-build"; renderer_dir="$OUT/out/dependency-build/renderer"
mkdir -p "$host_dir/lib" "$renderer_dir"
cp "$BUILD/native/skylanders-native-host" "$host_dir/"
cp "$BUILD/renderer/libskyrender.so" "$renderer_dir/"
system='^(ld-linux|libc|libm|libdl|libpthread|librt|libresolv|libutil|libvulkan|libGL|libEGL|libGLX|libGLdispatch|libdrm|libgbm|libX|libxcb|libwayland|libasound|libpulse|libpipewire|libdbus|libudev|libsystemd)[.-]'
: > "$BUILD/bundled.txt"
for binary in "$host_dir/skylanders-native-host" "$renderer_dir/libskyrender.so"; do
  LD_LIBRARY_PATH="$DEPS/lib:$BUILD/renderer" ldd "$binary" | awk '$3 ~ /^\// {print $3}'
done | sort -u | while read -r lib; do
  name=$(basename "$lib")
  echo "$name" | grep -Eq "$system" && continue
  cp -L "$lib" "$host_dir/lib/$name"; echo "$lib" >> "$BUILD/bundled.txt"
done
patchelf --set-rpath '$ORIGIN/lib:$ORIGIN/../../out/dependency-build/renderer' "$host_dir/skylanders-native-host"
patchelf --set-rpath '$ORIGIN/../../../.local/native-gpu-build/lib' "$renderer_dir/libskyrender.so"
for lib in "$host_dir"/lib/*.so*; do patchelf --set-rpath '$ORIGIN' "$lib"; done
printf '{"commit": "%s", "built_on": "ubuntu-22.04"}\n' "${GITHUB_SHA:-$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo local)}" > "$host_dir/prebuilt.json"

# Checks: everything resolves from the bundle, and nothing needs newer than glibc 2.35.
env -i PATH=/usr/bin:/bin ldd "$host_dir/skylanders-native-host" | tee "$BUILD/ldd.txt"
if grep -q 'not found' "$BUILD/ldd.txt" || grep -q "$BUILD\|$DEPS" "$BUILD/ldd.txt"; then echo 'unresolved or build-tree library' >&2; exit 1; fi
glibc=$( { objdump -T "$host_dir/skylanders-native-host" "$renderer_dir/libskyrender.so" "$host_dir"/lib/*.so* 2>/dev/null; } \
  | grep -o 'GLIBC_[0-9.]*' | sort -Vu | tail -1)
echo "Needs $glibc or newer"; echo "$glibc" > "$host_dir/glibc-required.txt"
if [ "$(printf '%s\n%s\n' "${glibc#GLIBC_}" "$MAX_GLIBC" | sort -V | tail -1)" != "$MAX_GLIBC" ]; then
  echo "Bundle needs $glibc, newer than $MAX_GLIBC" >&2; exit 1
fi

# License inventory: each bundled library, where it came from, and its terms.
mkdir -p "$OUT/LICENSES/linux-runtime"
python3 - "$BUILD/bundled.txt" "$DEPS" "$OUT" <<'EOF'
import json, subprocess, sys, shutil
from pathlib import Path
bundled, deps, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
pins = {'libSDL3': 'SDL3 (Zlib) libsdl-org/SDL release-3.4.20', 'libfmt': 'fmt (MIT) fmtlib/fmt 12.2.0',
        'libav': 'FFmpeg (LGPL-2.1-or-later) FFmpeg/FFmpeg n8.0.3', 'libsw': 'FFmpeg (LGPL-2.1-or-later) FFmpeg/FFmpeg n8.0.3'}
rows = []
for line in bundled.read_text().split():
    name = Path(line).name
    if line.startswith(deps):
        origin = next((v for k, v in pins.items() if name.startswith(k)), 'built from source, see tools/linux-release/build-ubuntu.sh')
        rows.append({'file': '.local/native-gpu-build/lib/' + name, 'source': origin})
        continue
    package = subprocess.run(['dpkg', '-S', line], capture_output=True, text=True).stdout.split(':')[0]
    version = subprocess.run(['dpkg-query', '-W', '-f=${Version}', package], capture_output=True, text=True).stdout if package else ''
    copyright = Path('/usr/share/doc')/package/'copyright'
    if package and copyright.is_file():shutil.copy(copyright, out/'LICENSES/linux-runtime'/(package+'.copyright'))
    rows.append({'file': '.local/native-gpu-build/lib/' + name, 'package': package, 'version': version, 'source': 'Ubuntu 22.04'})
(out/'LICENSES/linux-runtime.json').write_text(json.dumps(rows, indent=2) + '\n')
print(len(rows), 'bundled libraries inventoried')
EOF
for license in "$DEPS"/src/sdl3/LICENSE.txt "$DEPS"/src/fmt/LICENSE "$DEPS"/src/ffmpeg/COPYING.LGPLv2.1; do
  [ -f "$license" ] && cp "$license" "$OUT/LICENSES/linux-runtime/$(basename "$(dirname "$license")")-$(basename "$license")"
done
ls -la "$host_dir/lib"

# SkylandersPC

Play the PS4 Skylanders games natively on PC, from your own copies.

SkylandersPC is one compatibility layer for the whole PS4 Skylanders series.
It is not an emulator: a C++ host loads each game's original x86-64 executable
and runs it directly, supplying the PS4 system services the games call (files,
threads, memory, audio, controllers, saves, trophies and the portal) itself,
with a Vulkan renderer for graphics. The parts the games share live in one
runtime; anything specific to one game is kept in a small profile matched to
that game's exact build.

| Game | Status |
| --- | --- |
| Skylanders: Trap Team | Supported (US and EU) |
| Skylanders: Swap Force | Next |
| Skylanders: SuperChargers | Planned |
| Skylanders: Imaginators | Planned |

> **You need your own games.** This project contains no game code, data, keys,
> firmware or artwork, and never will. Install a game from your own PS4 package
> files through the launcher.

## Playing

Everything goes through the **launcher**: it installs a game from its package
files, keeps your saves, figures and settings, and starts the game. Each game
runs from a private working copy, so the installed files and your figure dumps
are never modified.

Click **Install** and follow the steps: choose your game file, add an update
or skip it, then click **Install game**. The launcher unpacks both into the **Games** folder
and uses the newest installed update automatically. **Open games folder** opens
that folder in your file manager. Existing installations stay where they are.
After installing a supported game, setup runs automatically. If it needs
attention, choose **Repair game setup** from the game’s menu. Controller artwork
and portrait downloads are optional extras; they never block setup.
The library shows setup status, installed versions and size. Use **Repair** to
finish setup, **Open folder** to find the files, or **Remove** to unregister the
game. Removal keeps saves, figures and settings; managed game files are retained
for recovery, so this does not immediately reclaim their disk space.
Unrecognized titles can be installed and are labelled “not supported yet”.

Builds will be published on the [Releases](https://github.com/The-Crow-Den/SkylandersPC/releases)
page, each with patch notes. There is no release yet.

## Features

- **Virtual portal**: place Skylanders, traps and magic items from figure
  dumps, create new figures, and capture villains, all from the in-game PC menu
  (F6, Insert or L3+R3), which works with a controller.
- **PC settings**: internal resolution up to 2160p (the game renders natively
  at it), shadow quality, fullscreen, a 30 or 60 FPS cap or an automatic mode
  that keeps cutscenes at 30 and gameplay at 60, and PlayStation, Xbox or
  Nintendo button icons in the game's own prompts.
- **Optional tweaks** (Trap Team US 01.01): elemental gates and Traptanium without a Trap Master,
  adventure packs available in the Academy, and Nightmare mode unlocked.
- **Launcher**: game installation from PKG files, figure management, trophies
  and per-game settings.

## Building from source

Requirements: Linux x86-64, CMake, a C++20 compiler, SDL3, OpenSSL, Python
3.11 or newer, and a GPU with Vulkan 1.3.

```sh
cmake -S native -B .local/native-build -DCMAKE_BUILD_TYPE=Release
cmake --build .local/native-build
ctest --test-dir .local/native-build --output-on-failure
python3 -m unittest discover -s tests -v
python3 tools/launcher.py
```

The Vulkan renderer, skyrender, lives in `renderer/` (GPL-2.0-or-later; a
modified fork of bloodborne_pc, which derives from shadPS4; see
[renderer/NOTICE.md](renderer/NOTICE.md)). Build it into `libskyrender.so`, then
point the host at it:

```sh
git submodule update --init
cmake -S renderer/gpu -B .local/renderer-build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DSKY_RENDERER_LTO=OFF -DSKY_RENDERER_PGO=off
cmake --build .local/renderer-build --target skyrender
cmake -S native -B .local/native-gpu-build -DCMAKE_BUILD_TYPE=Release \
  -DSKY_RENDERER_ROOT="$PWD/renderer" -DSKY_RENDERER_LIBRARY="$PWD/.local/renderer-build/libskyrender.so"
cmake --build .local/native-gpu-build
```

## Layout

- `native/`: the host: loader, import bridge, PS4 service implementations
  (`native/hle/`) and per-game hooks enabled only for an exact executable hash.
  See [native/README.md](native/README.md).
- `tools/`: the launcher, session runner, in-game PC menu, package extractor
  and asset/patch recipe tools.
- `profiles/`: per-game build identities and patch recipes. Recipes hold
  expected bytes and refuse to apply to anything else.
- `renderer/`: skyrender, the Vulkan GPU, video-out and audio component.
- `tests/`: synthetic tests; none need a game.

Unknown system calls are reported, never answered with a fake success.

## License

Original project material is **GPL-3.0-or-later** ([LICENSE](LICENSE),
[license scope](LICENSE_SCOPE.md)). Third-party components keep their own terms
([third-party notices](THIRD_PARTY_NOTICES.md), [LICENSES/](LICENSES)).
Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md). Skylanders is a trademark
of Activision. This project is not affiliated with or endorsed by Activision,
Toys for Bob or Sony.

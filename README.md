# SkylandersPC (W.I.P)

Play the PS4 Skylanders games natively on PC, from your own copies.

SkylandersPC is one compatibility layer for the whole PS4 Skylanders series.
It is not an emulator: a C++ host loads each game's original x86-64 executable
and runs it directly, supplying the PS4 system services the games call (files,
threads, memory, audio, controllers, saves, trophies and the portal) itself,
with a Vulkan renderer for graphics. The parts the games share live in one
runtime; anything specific to one game is kept in a small profile matched to
that game's exact build.

SkylandersPC builds on **bbport** ([bloodborne_pc](https://github.com/deadinside28/bloodborne_pc)
by deadinside28), the native PS4 port work for Bloodborne. Its approach of running the original
executable natively, and its Vulkan renderer (itself derived from
[shadPS4](https://github.com/shadps4-emu/shadPS4)), are the foundation this project's host and
renderer grew from.

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
After installing a supported game, setup runs automatically. When an update
changes the game host, **Play** rebuilds it before starting. If the game files
themselves need attention, choose **Repair game setup** from the game’s menu. Controller artwork
and portrait downloads are optional extras; they never block setup.
When a newer release is published, an **Update available** button appears at the
top of the library. In a git checkout it updates with a fast-forward pull (rebuild
the native parts afterwards); otherwise it opens the release page.
The library shows setup status, installed versions and size. Use **Repair** to
finish setup, **Open folder** to find the files, or **Remove** to unregister the
game. Removal keeps saves, figures and settings; managed game files are retained
for recovery, so this does not immediately reclaim their disk space.
Unrecognized titles can be installed and are labelled “not supported yet”.

Builds are published on the [Releases](https://github.com/The-Crow-Den/SkylandersPC/releases)
page, each with patch notes ([RELEASE_NOTES.md](RELEASE_NOTES.md) for the coming
0.1.0 beta). Windows gets a ready-to-run bundle; on Linux, build the native host
from source (below) and use the launcher AppImage or `python3 tools/launcher.py`.

## Features

- **Virtual portal**: place Skylanders, swappers, traps and magic items from
  figure files, mix swapper halves (named the way the game does, such as Wash
  Ranger), keep favourites, create new figures and capture villains, all from
  the in-game PC menu (F6, Insert or L3+R3), which works with a controller.
- **Physical portals (experimental)**: PS3, PS4, Wii and Wii U portals are
  passed to the game; *Automatic* uses one when it is plugged in.
- **PC settings**: internal resolution up to 2160p (the game renders natively
  at it), aspect ratios up to 32:9, shadow quality (High by default),
  fullscreen, and a 30 or 60 FPS cap or an automatic mode that keeps cutscenes
  at 30 and gameplay at 60.
- **Controller prompts**: Xbox or Nintendo buttons in the game's own prompts,
  including the animated ones, chosen automatically for the controller in use.
  PlayStation controllers keep the game's original prompts.
- **Skylanders Manager**: the collection in the launcher, with level, XP, gold
  and nicknames you can edit and a backup before every change.
- **Optional mods** (Trap Team US 01.01), each with its own switches: *No Trap
  Master required* (elemental gates, Traptanium), *Unlock adventure packs*
  (pack access, replayable introductions), *Skip cutscenes*, and Nightmare
  unlocked from the start.
- **Launcher**: game installation from PKG files, saves with automatic
  snapshots, trophies, storage management and per-game settings.

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
- `profiles/`: per-game build identities and patch recipes; `profiles/mods/README.md` describes how to write a mod. Recipes hold
  expected bytes and refuse to apply to anything else.
- `renderer/`: skyrender, the Vulkan GPU, video-out and audio component.
- `tests/`: synthetic tests; none need a game.

Unknown system calls are reported, never answered with a fake success.

## Credits

- [bbport / bloodborne_pc](https://github.com/deadinside28/bloodborne_pc) by deadinside28: the
  native-port approach and the renderer this project's `renderer/` is forked from.
- [shadPS4](https://github.com/shadps4-emu/shadPS4): the PS4 GPU and system-library work bbport
  builds on.
- [Cemu](https://github.com/cemu-project/Cemu): the Skylanders portal implementation.
- [skylanders-portal](https://github.com/TheBiemGamer/skylanders-portal) by TheBiemGamer: the Xbox 360
  portal frame format the Xbox portal transport follows.
- Mew00, SuperSamus and Winner Nombre: the Wii U Trap Team FPS graphics pack, whose delta-time
  clamp change the `60-delta` patch adapts.
- Valve's Steam client: the Xbox and Nintendo button artwork used for the game's prompts. It is
  imported from your own Steam installation on your machine, restyled locally, and never shipped.
- Dear ImGui, SDL3, Qt/PyQt6, Lucide icons, the Montserrat font and the other libraries listed
  in the [third-party notices](THIRD_PARTY_NOTICES.md).

## License

Original project material is **GPL-3.0-or-later** ([LICENSE](LICENSE),
[license scope](LICENSE_SCOPE.md)). Third-party components keep their own terms
([third-party notices](THIRD_PARTY_NOTICES.md), [LICENSES/](LICENSES)).
Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md). Skylanders is a trademark
of Activision. This project is not affiliated with or endorsed by Activision,
Toys for Bob or Sony.

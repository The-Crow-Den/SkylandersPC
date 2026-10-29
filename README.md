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

Click **Install**, choose the game's PKG and, if you have one, its update PKG,
then click **Install game**. The launcher unpacks both into the **Games** folder
and uses the newest installed update automatically. **Open games folder** opens
that folder in your file manager. Existing installations stay where they are.
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

The Vulkan renderer is a separate GPL-2.0-or-later project, skyrender, built as
`libskyrender.so`. It is not published yet.

## Layout

- `native/`: the host: loader, import bridge, PS4 service implementations
  (`native/hle/`) and per-game hooks enabled only for an exact executable hash.
  See [native/README.md](native/README.md).
- `tools/`: the launcher, session runner, in-game PC menu, package extractor
  and asset/patch recipe tools.
- `profiles/`: per-game build identities and patch recipes. Recipes hold
  expected bytes and refuse to apply to anything else.
- `tests/`: synthetic tests; none need a game.

Unknown system calls are reported, never answered with a fake success.

## License

Original project material is **GPL-3.0-or-later** ([LICENSE](LICENSE),
[license scope](LICENSE_SCOPE.md)). Third-party components keep their own terms
([third-party notices](THIRD_PARTY_NOTICES.md), [LICENSES/](LICENSES)).
Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md). Skylanders is a trademark
of Activision. This project is not affiliated with or endorsed by Activision,
Toys for Bob or Sony.

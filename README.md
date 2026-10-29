# SkylandersPS4

Run your own PS4 copy of **Skylanders: Trap Team** natively on a Linux PC.

SkylandersPS4 is a compatibility framework, not an emulator: a C++ host loads the
game's original x86-64 executable and runs it directly, supplying the PS4 system
services it calls (files, threads, memory, audio, pads, saves, trophies, the
Traptanium Portal) itself. Graphics go through a Vulkan renderer. Trap Team is
the first target; Swap Force is next and is used early to keep the shared parts
general.

> **You must supply your own game.** This repository contains no game code,
> data, keys, firmware or artwork, and never will. You need your own extracted
> CUSA00626 (US) or CUSA00697 (EU) package; the launcher can extract a fake-PKG
> dump for you.

## Status

Playable on the developer's machine (Linux, KDE Plasma, NVIDIA + AMD laptop):
title screen, Skylanders Academy, story levels, saving, the virtual portal and
the expansion levels have been played. It is a work in progress: not every
level, feature or GPU has been verified, and there is no binary release yet.

Highlights:

- **Virtual Traptanium Portal**: place Skylanders, traps and magic items from
  figure dumps, create new figures, and capture villains, from an in-game PC menu
  (F6, Insert or L3+R3) that works with a controller.
- **PC settings**: internal resolution up to 2160p (the game renders natively at
  it), shadow quality, fullscreen, a 30/60 FPS cap or an automatic policy that
  keeps cutscenes at 30 and gameplay at 60, and controller button icons
  (PlayStation, Xbox or Nintendo) in the game's own prompts.
- **Optional gameplay tweaks** for the US 01.01 build: elemental gates and
  Traptanium without a Trap Master, automatic adventure-pack access in the
  Academy, and Nightmare mode unlocked.
- **Launcher** (PyQt6, or a standalone AppImage) that installs games from PKG
  files, manages figures and settings, and shows trophies.

## Build

Requirements: Linux x86-64, CMake, a C++20 compiler, SDL3, OpenSSL, Python 3.11+,
and a Vulkan 1.3 GPU.

```sh
cmake -S native -B .local/native-build -DCMAKE_BUILD_TYPE=Release
cmake --build .local/native-build
ctest --test-dir .local/native-build --output-on-failure
python3 -m unittest discover -s tests -v
```

The Vulkan renderer is a separate project, **skyrender** (GPL-2.0-or-later),
built as `libskyrender.so`; see [the GPU component](docs/OPTIONAL_GPU_BACKEND.md)
and [renderer build](docs/RENDERER_BUILD.md). It is not yet published alongside
this repository.

## Play

Start the launcher with `python3 tools/launcher.py` (or the
[standalone AppImage](docs/STANDALONE_LAUNCHER.md)), install your game from its
PKG files, and press Play. From a terminal:

```sh
python3 tools/run_session.py --variant 60-delta --frame-policy auto --resolution 1600p --nvidia
```

Each session runs from its own private copy under the ignored `out/`; original
game files and figure dumps are never modified. See
[launcher](docs/PC_LAUNCHER.md), [portal and controllers](docs/PORTAL_AND_CONTROLLERS.md)
and [resolution options](docs/RESOLUTION_OPTIONS.md).

## How it fits together

- `native/`: the host: loader, import bridge and PS4 service implementations
  (`native/hle/`), game-specific hooks gated by the executable's hash. See
  [native/README.md](native/README.md) and [architecture](docs/ARCHITECTURE.md).
- `tools/`: launcher, session runner, PC menu, package extractor, and
  hash-guarded asset/patch recipes.
- `profiles/`: per-game build identities and patch recipes (expected bytes only).
- `docs/`: design notes and measurements. Start with [the plan](docs/PLAN.md),
  [system call contracts](docs/SYSTEM_CALL_CONTRACTS.md),
  [frame pacing](docs/FRAME_PACING.md) and [asset recipes](docs/ASSET_MOD_RECIPES.md).
  The original workspace and baseline-launcher tools are in
  [workspace tools](docs/WORKSPACE_TOOLS.md).

Every patch requires the exact executable hash and expected bytes and refuses a
mismatch; unknown system calls are reported, never faked as successful.

## License

Original project material is **GPL-3.0-or-later** ([LICENSE](LICENSE),
[license scope](LICENSE_SCOPE.md)). Third-party components keep their own terms
([third-party notices](THIRD_PARTY_NOTICES.md), [LICENSES/](LICENSES)). Before
publishing, run the checks in [publication preparation](docs/PUBLICATION.md).
Skylanders is a trademark of Activision; this project is not affiliated with or
endorsed by Activision.

# SkylandersPS4 (working name)

A shared PS4 compatibility project for running user-supplied Skylanders games
on PC. First target: Trap Team. Second target: Swap Force, used early to verify
that the shared base generalizes. Initial platform: Linux x86-64, shadPS4 and
Vulkan. The custom C++ native host executes the original Trap Team image with
bundled libc/Fios and explicit platform services. Its optional private GPU
component renders the title menu and the first level with Dino Rang, terrain,
foliage, NPCs and the HUD. Full gameplay, chapter completion and in-game
save/reload correctness remain unverified. A separate experimental 60 FPS/delta-time
patch reaches Chapter One; correct simulation speed and automatic phase switching
remain under investigation.
Current launchers use explicit offline socket failures; diagnostic network-worker
suspension is off by default. Later retry paths remain under validation.
The repository also contains dump/profile tooling and a separate stock-shadPS4
baseline launcher. See [current boot evidence](docs/CUSTOM_BOOT_PROGRESS_20261021.md),
[service contracts and priorities](docs/SYSTEM_CALL_CONTRACTS.md), and the
[709-import inventory](docs/SYSTEM_CALL_INVENTORY.md).

Optional graphical launcher: `python3 tools/launcher.py` (PyQt6). See
[launcher controls and validation](docs/PC_LAUNCHER.md) and the
[active PC experience goal](docs/PC_EXPERIENCE_GOAL.md).

Latest work: [native runtime efficiency](docs/NATIVE_RUNTIME_EFFICIENCY.md)
removes kernel crossings from supported CPUs' import bridge without lowering
graphics quality. [PC and physical portal plans](docs/PC_ROADMAP_AND_PORTAL_TRANSPORTS.md)
separate implemented features from future hardware support.

Run the configured local build with `./tools/run-native.sh`. It enables the
virtual portal: F2 imports a figure dump into a private working copy; F3 removes
characters while retaining the trap. F6 opens settings on the left and the portal
manager on the right, with separate character and initially empty villain traps.
Physical SDL gamepads now feed the guest pad state; a DualSense
Edge was detected in the real trial. See [portal, controller and display-backend
details](docs/PORTAL_AND_CONTROLLERS.md). X11/XWayland is the working backend;
native Wayland currently fails Vulkan swapchain creation on this machine.

Experimental internal resolution presets are available through
`python3 tools/run_session.py --variant 60-delta --resolution 1440p --nvidia`.
Choose `720p`, `900p`, `1080p`, `1440p`, `1600p` (2560×1600), or `2160p`;
changes require a restart. F6 opens the PC menu for resolution, shadow-quality
presets, fullscreen, an FPS counter, and a built-in 30/60 cap. MangoHud is an
optional user overlay (`--mangohud`); normal launches require none of its tools.
Use `--window-resolution 1080p` to fit a larger internal resolution into a smaller
window. See [resolution options and validation](docs/RESOLUTION_OPTIONS.md).

The experimental `--performance-profile low-end` selects native 1080p, lower
shadows, no motion blur and compact allocator settings. Start at 30 FPS for
portal arrival, then Shift+F1 selects 60 during gameplay. This targets GTX
16-series / RTX 20-series hardware; performance on those GPUs is not yet verified.
See [the low-end performance pass](docs/LOW_END_PERFORMANCE.md).

The sibling Wii U project is preserved. The current playable native host uses
bbport/shadPS4-derived renderer/platform code and the optional Cemu portal
component; it does not launch the historical reference AppImage. Dependency
origins, retained licenses and remaining publication checks are documented in
[third-party notices](THIRD_PARTY_NOTICES.md) and
[publication preparation](docs/PUBLICATION.md). Private game/code-generation
outputs and user artwork are excluded from source exports.

## Build the custom native host

```sh
cmake -S native -B .local/native-build -DCMAKE_BUILD_TYPE=Debug
cmake --build .local/native-build -j2
ctest --test-dir .local/native-build --output-on-failure
python3 tools/prepare_native.py /absolute/path/to/eboot.bin --out out/my-native-image
.local/native-build/skylanders-native-host --load out/my-native-image/image.pack
```

The preparation output directory must be new and inside ignored `out/`. Pack
bytes are game-derived and private. `--load` maps/links only and reports unresolved
imports; it does not launch the game. Normal play goes through
`tools/run_session.py`, which prepares the linked pack and starts the host with
`--run` (alias `--trace-start`). No unknown import returns a fabricated success.
See [the native host README](native/README.md) for the runtime layout.

## Prepare the workspace

Python 3.11+ and Git suffice for the current tools. From this repository:

```sh
python3 tools/workspace.py stage-runtime
python3 tools/workspace.py doctor
python3 tools/workspace.py probe-runtime
python3 -m unittest discover -s tests -v
```

The default archive path is `../shadps4-linux-sdl-0.20.0.zip`; pass `--archive`
for another location. Staging checks both archive and AppImage hashes, copies
only the pinned member to ignored `.local/runtime/` and makes it executable.
Staging does not execute the binary, install system packages or download anything.
Doctor reports environment facts; it does not certify GPU/runtime compatibility.
`probe-runtime` executes the pinned AppImage's help command with local XDG/temp
directories. Its logs and option checks go under `.local/probes/`. This has been
tested against the supplied binary; no game is launched by the probe.

When the extracted dump arrives:

```sh
python3 tools/workspace.py inventory /absolute/path/to/game
python3 tools/workspace.py inspect-executable /absolute/path/to/eboot.bin
python3 tools/workspace.py prepare-session /absolute/path/to/game \
  --profile trap-team --figure /absolute/path/to/owned-figure.sky
```

`--figure` is optional. Inventory reads build metadata, hashes the executable and
bundled modules, and inspects ELF64/plaintext SELF structure and import declarations.
It preserves encoded NIDs/scopes and reports runtime resolution as unchecked.
Malformed ranges are rejected; encrypted/compressed/blocked SELF payloads are
reported as unsupported without decryption. It does not validate relocations,
resolve runtime imports or certify dump completeness. See [inspection details](docs/EXECUTABLES.md).
Keep base/update combinations explicit; this tool does not merge updates.

Each session gets unique ignored directories and an inventory/manifest. Figure
data is copied before use; never point an emulator at the original. Preparation
does not launch anything. To attempt a prepared session when game data is present:

```sh
python3 tools/workspace.py launch-session /absolute/path/to/out/sessions/trap-team-EXAMPLE --timeout 300
```

The baseline launcher rechecks runtime, profile and game identities, disables automatic game
patches, and sets local XDG paths while inferring game content from the executable. It records
stdout/stderr, spawn errors, exit status, elapsed time and timeout/interruption. Attempts are
single-use; prepare a fresh session to retry. Timeouts return 124. Working figures
are **not automatically attached**: load the session's `figures/working.sky`
manually in the runtime. Actual game save/config routing remains unverified;
local path settings and CLI startup are tested, not game behavior. Private output
may contain paths and build metadata. A zero exit is never a playability claim.
On this NVIDIA/Wayland machine the verified stock title boot needed
`SDL_VIDEO_DRIVER=x11` before the launch command. Default Wayland failed during
swapchain creation. This is a local baseline setting, not a game patch.

Profiles deliberately contain no validated builds or patches. Preparation records
the exact-build match result; existing templates remain unverified. Shared profile
validation requires title ID, app version and executable hash to match before
patch selection. Selecting a profile alone does not certify a dump. See
[profile registration](docs/PROFILES.md). A separate patch validator/working-copy writer is implemented;
see [patch format and limits](docs/PATCHES.md). It is deliberately not connected
to automatic launch. No existing game patch has been verified yet.

See [the plan](docs/PLAN.md), [architecture](docs/ARCHITECTURE.md),
[Wii U lessons](docs/WIIU_LESSONS.md), and [reference review](docs/REFERENCES.md).
The latest implementation evidence is in [the framework checkpoint](docs/FRAMEWORK_CHECKPOINT_20261021.md).
Original project material is **GPL-3.0-or-later**; see [LICENSE](LICENSE) and
[license scope](LICENSE_SCOPE.md). Third-party files retain their own terms.
Use the checked source-export workflow in [publication preparation](docs/PUBLICATION.md)
before uploading. This checkout is not a ready-made binary release.

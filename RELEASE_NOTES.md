## SkylandersPC 0.1.0 (beta)

The first public beta. **Skylanders: Trap Team** (US and EU) runs natively on PC
from your own PS4 package files. Expect rough edges and please report them.

> You need your own copy of the game. This release contains no game code, data,
> keys, firmware or artwork.

### What's in this release

| File | For |
| --- | --- |
| `SkylandersPC-v0.1.0-windows.zip` | Windows 10/11, x86-64. Unzip and run `SkylandersPC.exe`; no Python or other install needed. |
| `SkylandersPC-v0.1.0-linux.tar.gz` | Linux. Extract it and run `SkylandersPC.AppImage`; the game host is already built. Needs a recent system (the glibc version is listed in `.local/native-gpu-build/glibc-required.txt`). |
| `Skylanders-Launcher-x86_64.AppImage` | Linux, for source checkouts: the launcher's Python runtime only. |
| `SkylandersPC-v0.1.0-source.tar.gz` | Complete corresponding source for these binaries. |
| `SHA256SUMS` | Checksums for every file above. |

You need a GPU with Vulkan 1.3.

### Highlights

- **Install from PKG**: choose the game and update packages; the launcher unpacks,
  verifies and prepares them, and cleans up after itself.
- **Virtual portal**: place Skylanders, swappers, traps and magic items from
  figure files, create new figures and capture villains from the in-game PC menu
  (F6, Insert or L3+R3), with the game's own portraits. Mixed swappers get their
  in-game names (Wash Ranger), and favourites include swapper combinations.
- **Skylanders Manager**: your collection in one place; edit level, XP, gold and
  nicknames, with a backup before every change. Swappers are one figure each.
- **Physical portals (experimental)**: PS3/PS4/Wii/Wii U portals are passed to the
  game. *Automatic* uses one when it is plugged in.
- **PC settings**: resolution up to 2160p, aspect ratios up to 32:9, shadow
  quality (High by default), anti-aliasing, 30/60 FPS with an automatic mode,
  game language.
- **Controller prompts**: Xbox or Nintendo button icons in the game's prompts,
  including the animated ones, chosen automatically for the controller in use.
  PlayStation controllers keep the game's original prompts.
- **Optional mods** (Trap Team US 01.01), each with its own switches: *No Trap
  Master required* (elemental gates, Traptanium), *Unlock adventure packs* (pack
  access, replayable introductions), skip cutscenes and logos, Nightmare unlocked.
- **Storage**: see what each part uses, cap caches, clear shaders and temporary
  files from Settings.
- **Updates**: the launcher tells you when a newer release is out, and Play
  rebuilds the game host after an update instead of asking for Repair.
- **Trophies and saves** are kept locally, with automatic save snapshots.

### Known issues

- The first visit to a new area can stutter while shaders compile. Later visits
  are smooth while *Save compiled shaders* is on.
- Physical portals have not been tested on real hardware yet. Wired Xbox 360
  portals can be chosen on the Portal page (untested on hardware); Xbox One
  portals are not supported yet.
- Swappers' level, XP and gold cannot be edited in the Manager.
- With the gate mod, a swapper opens gates matching its bottom half; the top half
  has not been checked.
- Only Trap Team is playable. Swap Force, SuperChargers and Imaginators are not yet.
- The prebuilt Linux host needs a recent glibc. On older systems (Ubuntu 24.04,
  Fedora 42, SteamOS) build it from source for now.

### Reporting problems

If the game closes unexpectedly, the launcher offers a crash report you can copy
(home folders and user names are removed). Open an issue with it on GitHub.

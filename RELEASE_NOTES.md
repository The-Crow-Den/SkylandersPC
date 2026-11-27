## SkylandersPC 0.1.2 (beta)

**Sorry about the last release.** 0.1.1 shipped with problems that should have
been caught first: existing installs stopped working after updating,
the Windows launcher could freeze while installing, and 4K and ultrawide screens
crashed. Thank you for your patience and for reporting them. This release fixes
those problems, and every release is now tested on Windows and Linux, with
updates from older versions, before it goes out.

### What's new in 0.1.2

- **Trap Team 01.01 launches again.** After updating to 0.1.1, existing installs
  stopped at "exit code 2" until Repair was run. They now start normally.
- **Automatic updates.** From this version on, the launcher downloads new releases
  in the background, checks them against their published checksum and installs
  them when it closes (or right away with *Restart to update*). Games, saves and
  settings are kept. This version itself still has to be downloaded by hand.
- **Graphics card names.** On Linux, the graphics card setting lists the cards in
  your PC by name instead of by maker.
- After an update, *Play* finishes any setup step that needs redoing instead of
  asking for Repair.
- **Installing on Windows no longer freezes or closes the launcher.** Writing the
  install log failed on some characters, which stopped the launcher partway.
- **The US base game without its update (01.00) now finishes setup**, and most
  mods work on it: *Unlock Nightmare*, *Trap Master*, *Unlock Expansions* and
  Xbox or Nintendo controller prompts. *Skip Cutscenes* still needs the 01.01
  update; mods that don't fit your version are skipped instead of stopping the
  game.
- **60 FPS in the challenges.** On Automatic, Kaos Doom Challenges, arena
  challenges and the other challenge maps stayed at 30 FPS. They now play at 60
  like the story levels.
- **More mods on the EU game (01.00).** Elemental gates and Traptanium without a
  Trap Master, Xbox or Nintendo controller prompts and *Unlock adventure packs*
  now work on it, alongside *Unlock Nightmare* and 60 FPS (not yet played
  through on EU). On EU, Traptanium covers every level and Kaos Doom Challenge
  map. Replayable pack introductions and *Skip
  Cutscenes* are still US-only; on an EU copy they are skipped instead of
  stopping the game.
- **Making mods is easier.** `tools/make_mod.py` turns files you edit into a mod:
  unpack a game archive, change it, and the tool writes the mod for you, fitting
  every game version it can. `profiles/mods/README.md` explains how.
- The launcher has its icon on Windows and in the AppImage, and the Trap Master
  mod now works in release downloads.
- **4K and ultrawide screens no longer crash.** 2160p, and 21:9 or 32:9 at high
  resolutions, ran the game out of video memory shortly after starting. Large sizes
  now render at the biggest size the game can hold and are scaled to your screen.
- **Controller button prompts work on Windows.** The launcher now finds Steam's
  button artwork on Windows, and the image support it needs is included.
  Selecting the mod with a PlayStation pad no longer stops the game from starting.
  The tag button at the bottom of the screen now shows LT or ZL instead of L2,
  and mash prompts are no longer darker than the game's: they keep a light rim
  that pulses like the original.
- **Safer installs.** The launcher warns before an install when the drive is
  short on space, asks before installing a game that can't be played yet, and
  explains how to reinstall a version that is already installed.
- **Choose where to install.** The last install step shows where the game goes,
  with *Change…* to pick another folder or drive. New games go there from then
  on; games you already have stay where they are.
- On Windows, a Games folder on another drive (set in Settings) is now kept;
  before, the launcher quietly went back to its own Games folder.
- Opening the launcher a second time says it is already open instead of starting
  two copies.

## SkylandersPC 0.1.1 (beta)

### What's new in 0.1.1

- **More copies of Trap Team work.** The US base game without its update (01.00),
  and the EU game with the 01.01 update, were wrongly marked as not supported.
- **Request support for other copies.** A copy that still can't be played says so
  plainly, and *Request support* opens a ready-made GitHub post with the game's
  version and fingerprints (nothing personal) so it can be looked at.
- **Game logos** now show in the launcher's library.
- The remaining *SkylandersPS4* names are now *SkylandersPC*.

## SkylandersPC 0.1.0 (beta)

The first public beta. **Skylanders: Trap Team** (US and EU) runs natively on PC
from your own PS4 package files. Expect rough edges and please report them.

> You need your own copy of the game. This release contains no game code, data,
> keys, firmware or artwork.

### What's in this release

| File | For |
| --- | --- |
| `SkylandersPC-v0.1.1-windows.zip` | Windows 10/11, x86-64. Unzip and run `SkylandersPC.exe`; no Python or other install needed. |
| `SkylandersPC-v0.1.1-linux.tar.gz` | Linux (Ubuntu 22.04 or newer, Debian 12, Fedora, Arch, SteamOS). Extract it and run `SkylandersPC.AppImage`; the game host is already built. |
| `Skylanders-Launcher-x86_64.AppImage` | Linux, for source checkouts: the launcher's Python runtime only. |
| `SkylandersPC-v0.1.1-source.tar.gz` | Complete corresponding source for these binaries. |
| `SHA256SUMS` | Checksums for every file above. |

You need a GPU with Vulkan 1.3.

### Highlights

- **Install from PKG**: choose the game and update packages; the launcher unpacks,
  verifies and prepares them, and cleans up after itself.
- **Play without the launcher**: `--play` starts the game with your saved
  settings, for a desktop shortcut or a non-Steam game in Steam.
- **Your data in one place**: saves, trophies, figures and settings live in
  `~/.local/share/SkylandersPC` (Linux) or `Saved Games\SkylandersPC` (Windows).
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

### Reporting problems

If the game closes unexpectedly, the launcher offers a crash report you can copy
(home folders and user names are removed). Open an issue with it on GitHub.

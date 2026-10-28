# Third-party notices

Full retained notices are in `LICENSES/third-party/`; the machine-readable list
and file hashes are in `LICENSES/dependencies.json`. These notices describe the
current build inputs and conditional packaging obligations. They are not a
claim that all listed dependencies are bundled, or a complete binary SBOM.
Upstream source headers and additional nested notices remain authoritative.

| Component | License / retained terms | Current use |
| --- | --- | --- |
| bbport / bloodborne_pc | GPL-2.0-or-later | GPU/platform and selected C runtime; source remains external |
| shadPS4 | GPL-2.0-or-later | Renderer/shader ancestry through bbport; upstream base recorded in `LICENSES/bbport-source.json` |
| shadPS4 PKG/PFS extractor | GPL-2.0-or-later | Python port and entry-name table; pinned source and hashes in `LICENSES/pkg-source.json`; copyright 2024 shadPS4 Emulator Project |
| Cemu portal and adapter | MPL-2.0 | Optional local portal implementation; exact public source pin unresolved |
| LibAtrac9 | MIT | Audio codec compiled into native host |
| Dear ImGui | MIT | In-game PC menu, with project modifications in provider patch |
| DejaVu / Bitstream Vera / Arev | Full DejaVu notice | Embedded provider menu font; retain all supplied font notices |
| sirit | BSD-3-Clause | SPIR-V emitter |
| SPIRV-Headers / Vulkan-Headers | Retained Khronos notices, MIT / Apache-2.0 as applicable | Graphics build inputs |
| AMD GCN / FidelityFX FSR1 headers | MIT notices retained | GPU definitions / shader headers |
| FSR-Vulkan / FidelityFX SDK subset | MIT plus upstream notice | Provider upscaler code; no proprietary DLLs/model assets in source export |
| half / cpp-httplib / robin-map / magic_enum / miniz / VMA | MIT notices retained | Renderer/build dependencies; use varies by target |
| Zydis / Zycore | MIT | Instruction/patch tooling and renderer dependencies |
| Xbyak | BSD-3-Clause | External dependency; target-specific use |
| SDL3 | Zlib | Input, windowing and audio |
| fmt / xxHash / X11 / Boost | MIT / BSD-2-Clause / supplied X11 notices / BSL-1.0 | System/build dependencies |
| PyQt6 | GPL v3 or separate commercial license | Python launcher uses PyQt6, not PySide; this project uses the GPL route |
| PyQt6-sip | BSD-2-Clause | Python binding support |
| Qt | Module-specific GPL/LGPL/commercial and third-party terms | System GUI libraries; bundled Qt needs a separate module inventory |
| CPython (python-build-standalone) | PSF-2.0 and bundled-library notices | Interpreter in the optional standalone launcher AppImage only |
| cryptography / cffi / pycparser | Apache-2.0 or BSD-3-Clause / MIT-0 / BSD-3-Clause | Python packages in the standalone launcher AppImage |
| AppImage type-2 runtime / appimagetool | MIT | Build tool and runtime of the standalone launcher AppImage |
| Pillow | Full Pillow notice retained | Optional one-time image import tools |
| FFmpeg | Build-dependent LGPL/GPL terms | Native provider links installed libav*; inspect the exact binary build before bundling |
| OpenSSL libcrypto | Apache-2.0 | Read-only trap save metadata decoding; system dependency |
| libusb / C++ runtime / libc | Their respective library/system terms | Native/system dependencies; not included in source export |

The launcher does not require purchasing a commercial PyQt license when used
under its applicable GPL terms; see [Riverbank's licensing description](https://en.riverbankcomputing.com/software/pyqt).
MPL source must keep its notices and source availability; combining MPL and GPL
requires the conditions described by [Mozilla](https://www.mozilla.org/en-US/MPL/2.0/combining-mpl-and-gpl/).

## Source provenance and modifications

`LICENSES/bbport-source.json` records the supplied source archive SHA-256, commit
and each modified provider file. `native/dependency-patches/bbport-local-changes.patch`
is the canonical aggregate patch against that snapshot. Apply it once to the
pinned original; do not also apply the historical incremental patches. The
upstream shadPS4 ancestry recorded by bbport is
`b4e7ae776071ceb1dd35004577a8719481e1d258`.

`LICENSES/portal-source.json` records hashes of the local Cemu/adapter inputs.
Hashes identify those files but do not establish an upstream revision or publish
their corresponding source. That gap remains open for a portal-enabled binary.
Source adapters and notices can be published without claiming it resolved.

Reference-only bbhost, bloodborne-recomp and the historical shadPS4 AppImage are
not distributed by this repository. Private igArchiveExtractor/IGZ research
readers remain excluded under `out/` and `.local/`. Their availability locally
must not be mistaken for permission to publish game data they extract.

## Artwork and optional binary components

Steam glyph images, downloaded figure, villain and element portraits and game-derived launcher art
are not covered by the software license and are never part of the source export.
Only import/cache tooling is included. Game names are identifiers, not an
artwork/trademark license. No attribution line substitutes for permission to
redistribute an asset.

Do not attach the private AppImage, console libraries, NVIDIA DLSS/AMD model
payloads, generated packs, shader dumps or vendor binary archives to GitHub
Releases. A later binary release must inventory its actual shipped files,
retain their terms and provide the matching corresponding source. Merely linking
to an unrelated upstream main branch is not sufficient for modified binaries.

Optional trophy XML decryption uses the system Python `cryptography` package
(Apache-2.0 OR BSD-3-Clause); its notices are retained in
`LICENSES/third-party/cryptography.txt`. No keys or decrypted game metadata are
included. Native trophy API layouts and TRP derivation were cross-checked against
shadPS4; local persistence and preparation are implemented in this project.

The offline HTML PC overlay includes Lucide 1.17.0 in
`tools/pc_menu/lucide.js` (ISC, with Feather-derived icons under MIT). Both
notices are retained in `LICENSES/third-party/Lucide-ISC.txt`. The source
export includes the HTML, CSS and JavaScript, excluding private portrait assets.
QtWebEngine/PyQt6-WebEngine are system runtime dependencies for the optional
HTML overlay; exact binary-bundle terms remain part of the outstanding inventory.

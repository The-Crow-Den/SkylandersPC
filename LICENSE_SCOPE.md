# License scope

The project owner's selected license for original project code, documentation,
configuration and tests is **GPL-3.0-or-later**. The full GPL v3 text is in
[LICENSE](LICENSE); the "or later" permission is part of this project notice.
Copyright remains with the respective authors and contributors. No third-party
copyright ownership is claimed.

File-specific notices take precedence for these components:

- `native/dependency-patches/` and `tools/controller_glyphs.py` retain the adopted
  GPL-2.0-or-later component terms. Their code may be combined under the GPL v3
  option; their upstream notices must remain intact.
- `native/hle/portal_library_adapter.cpp` is MPL-2.0. The separately supplied Cemu
  source remains MPL-2.0. Preserve its source notices and the MPL text when
  distributing those files or an executable containing them.
- `LICENSES/` and `tools/licenses/` contain verbatim third-party license/notice
  documents under their respective terms, not a new project license grant.
- Third-party sources, libraries, fonts and optional assets keep their own terms.
  See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
  [LICENSES/dependencies.json](LICENSES/dependencies.json).

This license grants rights only in material the project authors may license. It
neither licenses game assets, game executables, firmware, console modules,
figure/save data, Steam glyph images, downloaded portraits or trademarks, nor
changes their owners' terms. Such material is excluded from source exports.
Minimal expected-byte patch recipes are interoperability metadata, not a grant
of rights in the corresponding game. A profile containing bulk literal game data
is withheld until it can be represented without distributing that data.

The original-code GPL-3.0-or-later grant does not claim that every dependency can
be relicensed to any future GPL version. Choose a mutually permitted version for
a combined distribution and retain every component's own notices.

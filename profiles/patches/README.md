# Public patch metadata

These profiles contain exact-build hashes, expected-byte edits and bounded
interoperability metadata. They do not include replacement game archives.
Original project profiles are GPL-3.0-or-later as described by LICENSE_SCOPE.md;
that license does not grant rights in the target game.

The local file `trap-team-us-01.01-traptanium.experimental.json` is intentionally
withheld from publication: its current serialization includes bulk literal
asset bytes. It remains usable in the developer's private working tree but is
ignored by Git and omitted by the source exporter. It needs conversion to a
source-relative or semantic recipe before public inclusion. A clean source
checkout reports that recipe as unavailable if explicitly selected. Gate and
other data-free profiles remain independent of it.

`trap-team-us-01.01-replay-expansion-intros.experimental.json` is withheld the
same way: its shifted-metadata edits carry about 347 kB of literal before/after
game bytes. A clean checkout reports the replay tweak as unavailable. The
automatic expansion access recipe (`unlock-expansions`) is data-free and tracked.

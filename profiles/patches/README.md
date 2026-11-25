# Public patch metadata

These profiles contain exact-build hashes, expected-byte edits and bounded
interoperability metadata. They do not include replacement game archives.
Original project profiles are GPL-3.0-or-later as described by LICENSE_SCOPE.md;
that license does not grant rights in the target game.

`trap-team-us-01.01-traptanium.experimental.json` ships with the Trap Master
mod. Address shifts and same-chunk moves use add and copy_from edits; its
remaining literal blocks are listed as owner-reviewed in the release audit.

`trap-team-us-01.01-replay-expansion-intros.experimental.json` is data-free:
pointer shifts are little-endian deltas and moved data is copied within the
chunk, both pinned by hashes, so it carries no game bytes. It ships with the
`unlock-expansions` mod, alongside the data-free expansion access recipe.

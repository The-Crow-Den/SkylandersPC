# Contributing

Original contributions use GPL-3.0-or-later, subject to file-specific upstream
terms in LICENSE_SCOPE.md. Preserve existing copyright and license notices;
identify the exact source and license when adopting outside code. No additional
CLA or transfer of copyright is required by this document.

Do not submit game dumps, generated game code/packs, firmware, console modules,
keys, saves, figure dumps, extracted textures/audio, Steam glyph images or other
artwork without established redistribution rights. Use synthetic tests and
source-relative patch recipes. Keep private investigations under ignored local
paths. A new dependency needs a source pin, retained notices and a clear role.

Run `python3 -m unittest discover -s tests -v` and
`python3 tools/release_audit.py --tracked` before proposing a public change.
Native behavior changes also need the relevant native checks and honest runtime
validation. Offline checks do not establish game playability or performance.

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

## Publishing source

Run the source audit before every push; GitHub Actions runs it too:

```sh
python3 -m unittest discover -s tests -v
python3 tools/release_audit.py --tracked     # tracked files
python3 tools/release_audit.py --staged      # the index, before committing
python3 tools/release_audit.py --tree --export out/licensing/source.tar.gz
```

The audit rejects private or unreviewed paths, game/binary/image data, bulk hex
payloads in JSON, missing license identifiers, changed retained notices and key
material. It is a packaging safeguard, not legal clearance. Recipes that still
carry literal game bytes (listed under `withheld` in `release-policy.json`) stay
local until converted to source-relative recipes. A binary release additionally
needs the provenance steps under `binary_release_blockers` in that file.

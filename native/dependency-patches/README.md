# Historical renderer patches

These patches record the renderer changes made before the renderer became the
project's own `skyrender` repository (`.local/skyrender`). That repository's
history now holds them as commits: the unmodified upstream archive, then
`bbport-local-changes.patch`, then the menu and remaining changes, then
`parallel-pipeline-preload`, `compile-split-counters` and `pipeline-prefetch`.
New renderer changes are commits there, not new files here.
`bbport-local-changes.patch` stays as the hash-pinned provenance record in
`LICENSES/bbport-source.json`.

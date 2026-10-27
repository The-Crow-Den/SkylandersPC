# Project instructions

Build a reusable PS4 compatibility framework, first Trap Team, then Swap Force.
Start with the pinned shadPS4 baseline. Do not modify the sibling Wii U project.
Keep game-specific behavior in profiles; keep correct shared platform contracts
in the common runtime. A second title must exercise shared changes early.

Never track game dumps, console modules, keys, firmware, generated game code,
figure/save contents, private traces or reference binaries. Keep local data in
ignored .local/ or out/. Do not copy decompiled game implementation into source.
No reference source has been integrated; retain component licenses on adoption.

Do not infer playability from process exit, archive opens, draw counts or a
title screenshot. Verify visible gameplay, input, saves and device behavior.
Benchmark matched scenes/work with diagnostics off; separate cold/warm caches.
Do not use skipped frames, muted audio or altered timing for normal FPS claims.
Record every known behavior-changing setting. Unknown calls must be diagnosed,
not silently treated as successful. Patches require executable hash and expected
bytes, and must refuse a mismatch. Never apply Wii U addresses/patches to PS4.

Run `python3 -m unittest discover -s tests -v` for tooling changes. No game or GPU
is required for these synthetic tests. Do not claim runtime/game validation from
these tests. Do not spawn parallel agents unless the user requests delegation.

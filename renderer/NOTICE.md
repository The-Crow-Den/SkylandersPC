# skyrender

skyrender is the PS4 GPU, video-out, audio and memory component of the
SkylandersPS4 project. It is a modified fork of bloodborne_pc ("bbport",
https://github.com/deadinside28/bloodborne_pc, commit
8185b88d80573fa300595d5c54450183b4109935), which derives from shadPS4. It is
licensed GPL-2.0-or-later (see LICENSE); bundled third-party components keep
their own licenses and notices under `gpu/third_party/` and `third_party/`.

History: the first commit is the unmodified upstream archive (SHA-256
953c3da81c63915dfa70622289c505a7dd77498ba3cc5bf1bdd16943f80806c3). Later commits
are SkylandersPS4's changes, including the rename from the upstream names
(`bbgpu`, `Bb*`, `BB_*`, `bbport.ini`) to `skyrender`, `Sky*`, `SKY_RENDERER_*`
and `renderer.ini`.

Removed from the upstream tree (still in this repository's history): the
upstream Bloodborne loader (`src/` apart from the runtime files the SkylandersPS4
host compiles), its launcher, packaging, scripts, docs, online module
(`gpu/bbnet*`), Windows probe executable, host tests and tools; and inside the
library, the Bloodborne game profile and menu pointer, its guest-code hooks
(frame-rate unlock, System-menu pages, libGnm entry hooks, effect and FX fixes,
camera API), heap and free-list diagnostics, button prompts, cursor, the
upstream settings window and the toy-pad device. The game-profile mechanism and
the generic guest-code hook mechanism remain, with no profiles registered.
Also removed: the temporal upscalers (`gpu/upscale/`: FSR 3.1, FSR 4, TAA,
DLSS, frame generation, camera and object motion vectors, scene-resolution
proxies), the DLSS bridge (`gpu/dlss_bridge/`, adapted from
IFreemz/shadPS4-Bloodborne-DLSS-FSR), the FSR-Vulkan submodule
(FireBurn/FSR-Vulkan, MIT), the AMD FidelityFX FSR1 headers and the FSR 4
benchmark; SkylandersPS4 sets its resolution in the game instead.

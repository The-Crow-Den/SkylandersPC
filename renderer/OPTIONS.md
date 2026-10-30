# skyrender options

Every `SKY_RENDERER_<name>` environment variable the renderer reads, generated from the code
(`tools/gen_options.py`; run it again after adding or removing an option). The host sets a few
itself (SkylandersPS4 `native/gpu_backend.cpp`); the old `BB_<name>` spellings are taken over at
load (`gpu/shim/legacy_options.cpp`). "Default" is read off the code and may be blank where it
is computed; the description is the comment at the read.

## Behaviour and tuning (127)

| Option | Default | Description | Read in |
|---|---|---|---|
| `ANISO` | `16` | Mipmapped linear samplers of graphics draws get SKY_RENDERER_ANISO (16; 0 = the game's) times. | `gpu/render/raster_textures.cpp` |
| `ASYNC_PIPELINES` | on; `0` turns it off | Only a pass drawn every frame may go without a draw for a frame or two (its render target drawn to in each of the last frames, below). A one-time render compiles at once, as during loading screens (a frame of fewer than 300 draws before this one). The pipeline must not depend on the draw's vertex buffers (VK_EXT_vertex_input_dynamic_state). A size rule (the scene's, the output's) missed most passe | `gpu/render/pipeline_cache.cpp` |
| `ASYNC_PIPELINE_THREADS` |  | Workers (prefetch) and the GPU thread (async passes) share one pool, created once. | `gpu/render/pipeline_cache.cpp` |
| `ASYNC_SUBMIT` |  | SKY_RENDERER_ASYNC_SUBMIT (default on; 0: off): submissions go out from the recording threads once their segments are recorded, instead of this thread waiting for them (~65 us each). | `gpu/render/scheduler.cpp` |
| `AUDIO` |  | (read in sdl_audio) | `src/runtime_audio.c` |
| `BIND_MEMO` | on; `0` turns it off | (read in BufferCache::BindMemoOn) | `gpu/layer/buffer_cache_layer.cpp` |
| `CHUNK_TEXTURES` | on; `0` turns it off | (read in ChunkTextures) | `gpu/buffers/buffer_cache.cpp` |
| `CHUNK_UPLOADS` | on; `0` turns it off | guest chunks (SKY_RENDERER_CHUNK_UPLOADS=0: CPU staging), texture data bound in place whatever its type (SKY_RENDERER_INPLACE_TEXTURES=1; off: by type). | `gpu/buffers/buffer_cache.cpp` |
| `COMPUTE_RELEASE_FLUSH` | on; `0` turns it off | with the rest of the frame (SKY_RENDERER_COMPUTE_RELEASE_FLUSH=0: as before). | `gpu/cp/cp_compute.cpp` |
| `CONFIG` |  | (read in Path) | `gpu/shim/renderer_settings.cpp` |
| `CONSTANTS_IN_PLACE` |  | (read in ConstantsInPlace) | `gpu/buffers/memory_model.cpp` |
| `CONSTRAM_GPU_WAIT` | on; `0` turns it off | SKY_RENDERER_CONSTRAM_GPU_WAIT=0: not waited. | `gpu/render/raster_pipe.cpp` |
| `CONSTRAM_PIPE` | on; `0` turns it off | SKY_RENDERER_CONSTRAM_PIPE=0: a DumpConstRam waits for all queued draws, not only for those reading its bytes. | `gpu/render/raster_pipe.cpp` |
| `COPY_DEST_GAP` | `256` | (read in CopyDestinationGap) | `gpu/render/shader_hle.cpp` |
| `COPY_DEST_PRECISE` | on; `0` turns it off | (read in CopyDestinationsPrecise) | `gpu/render/shader_hle.cpp` |
| `COPY_GPU_BUFFERS` | on | (read in IsCopyGpuBuffers) | `gpu/shim/core/emulator_settings.h` |
| `COPY_MERGE_KB` |  | SKY_RENDERER_COPY_MERGE_KB overrides it. | `gpu/render/shader_hle.cpp` |
| `COPY_THREADS` |  |  | `gpu/shim/renderer_copy.cpp` |
| `DATA_DIR` |  |  | `gpu/cp/cp_diagnostics.cpp` |
| `DIRECT_MEMORY_ACCESS` | on | (read in IsDirectMemoryAccessEnabled) | `gpu/shim/core/emulator_settings.h` |
| `DIRECT_SEGMENT` | on; `0` turns it off | SKY_RENDERER_DIRECT_SEGMENT=0: the wait. | `gpu/render/scheduler.cpp` |
| `DISPLAY` |  | Issue #69: the monitor the window (and fullscreen) goes to. SKY_RENDERER_DISPLAY: its number in SDL's order (1, 2, ...; skyrender-gpu-capabilities --displays lists them) or a part of its name; without it SDL's primary display. The monitors are logged so a report says which one was taken. | `gpu/shim/window.cpp` |
| `DISPLAY_PACING` | on; `0` turns it off | SKY_RENDERER_DISPLAY_PACING=0 presents frames as soon as they are rendered, as before. | `gpu/render/display_pacer.cpp` |
| `DMEM_EXTRA_MB` | `512` | (read in extra_pool_bytes) | `src/runtime_memory.c` |
| `DMEM_MB` | `0` | (read in game_pool_bytes) | `src/runtime_memory.c` |
| `DRAW_PIPE` |  | (read in Rasterizer::DrawPipeWanted) | `gpu/render/raster_pipe.cpp` |
| `FAULT_WINDOW` | `256` | (read in BufferCache::ExtendWriteFault) | `gpu/buffers/buffer_cache.cpp` |
| `FLIP_AHEAD` | `1` | of the buffer, recorded before any later drawing into it. At most SKY_RENDERER_FLIP_AHEAD flips wait to be shown. | `gpu/platform/videoout/display.cpp` |
| `FLIP_RATE` |  | SKY_RENDERER_FLIP_RATE=n: the rate asked for is replaced (0: every vblank; games without frame rate hooks, e.g. 60 FPS where a game asks for 30). | `gpu/platform/videoout/videoout.cpp` |
| `FPS_LIMIT` | `0` | Frames per second the present thread lets through; 0 = no limit (SKY_RENDERER_FPS_LIMIT). | `gpu/shim/core/emulator_settings.h` |
| `FRAMES_AHEAD` | `1` | SKY_RENDERER_FRAMES_AHEAD (default 1): how many guest frames the command processor thread may run ahead of the GPU (0: unbounded). | `gpu/render/presenter.cpp` |
| `FREE_MOUSE` |  | Compatibility hosts without mouse-look must not confine the desktop pointer. | `gpu/shim/window.cpp` |
| `FULLSCREEN` | off; `1` (or a value) turns it on |  | `gpu/shim/window.cpp` |
| `GARLIC_VRAM` |  | (read in GarlicInVram) | `gpu/buffers/buffer_cache.cpp` |
| `GPU_COMMAND_WRITES` | on; `0` turns it off | (read in Rasterizer::WriteDataOnGpu) | `gpu/render/raster_signals.cpp` |
| `GPU_ID` | `-1` | (read in GetGpuId) | `gpu/shim/core/emulator_settings.h` |
| `GPU_LABELS` |  | which also turns them off, fixes it). SKY_RENDERER_GPU_LABELS=1 forces them on. | `gpu/render/raster_signals.cpp` |
| `GPU_LABELS_PORTABLE` | off; `1` (or a value) turns it on |  | `gpu/render/raster_signals.cpp` |
| `GPU_SPIN_US` |  | microseconds. Spin first, with cores to spare (SKY_RENDERER_GPU_SPIN_US, default 200 with 12+ hardware threads, else 0). | `gpu/cp/command_processor.cpp` |
| `GPU_TIMESTAMPS` | on; `0` turns it off | SKY_RENDERER_GPU_TIMESTAMPS=0: written by the CPU (EOP: once the GPU is done; COPY_DATA: when decoded). | `gpu/render/raster_signals.cpp` |
| `GPU_USER_DIR` |  |  | `gpu/common/path_util.cpp` |
| `GPU_WRITES_IN_PLACE` | off; `1` (or a value) turns it on | (no readbacks: SKY_RENDERER_READBACKS was relaxed before too); SKY_RENDERER_GPU_WRITES_IN_PLACE=1 keeps them in place (PCIe, ~9 ms a frame on an RX 7800 XT). | `gpu/buffers/buffer_cache.cpp` |
| `GPU_WRITE_TWINS` | off; `1` (or a value) turns it on | guest wrote them since). Only pages with at most SKY_RENDERER_GPU_WRITE_TWINS_MAX (1024) GPU-written bytes: larger outputs (vertices the CPU reads back, FaceGen) keep waiting for the GPU. Not with SKY_RENDERER_READBACKS=2: a twinned page stays GPU-modified (read-protected) while the guest may write it, a write-only page the page manager cannot make (it stopped at the first cutscene). | `gpu/buffers/buffer_cache.cpp` |
| `GPU_WRITE_TWINS_MAX` | `1024` | (read in TwinsMaxBytes) | `gpu/buffers/buffer_cache.cpp` |
| `GUEST_GPU_MEMORY` | off; `1` (or a value) turns it on | dma-buf guest memory (SKY_RENDERER_GUEST_GPU_MEMORY=1) cannot be write-protected by userfaultfd (anonymous and shmem only): its registration would fail and writes go unseen. | `gpu/memory/page_watch.cpp`, `gpu/shim/renderer_guest_memory.cpp` |
| `GUEST_HOOKS` | on; `0` turns it off | Hooks in the game's own code, from its profile (games/). SKY_RENDERER_GUEST_HOOKS=0: none, as for a game the port knows nothing about. Guards, aspect ratio and input hooks also apply to the old memory model; only GPU-range notifications require memory in place (#214). | `gpu/buffers/buffer_cache.cpp` |
| `GUEST_IN_PLACE` | off; `1` (or a value) turns it on | SKY_RENDERER_GUEST_IN_PLACE (the GPU uses this memory in place) needs it too. | `gpu/buffers/memory_model.cpp`, `gpu/shim/renderer_guest_memory.cpp` |
| `GUEST_MEMORY` |  | SKY_RENDERER_GUEST_MEMORY=dmabuf\|host chooses; else AMD uses dma-buf chunks (tested the most) and other GPUs host memory import first (NVIDIA: its dma-buf maps at offset 0 only, and CPU access through it may be slow). | `gpu/shim/renderer_guest_memory.cpp` |
| `GUEST_UNCACHED` | off; `1` (or a value) turns it on |  | `gpu/vulkan/instance.cpp` |
| `GUEST_WHOLE_CHUNKS` | off; `1` (or a value) turns it on | SKY_RENDERER_GUEST_WHOLE_CHUNKS=1: as if the offset mapping failed (tests the NVIDIA path). | `gpu/shim/renderer_guest_memory.cpp` |
| `HDR` | off | (read in IsHdrAllowed) | `gpu/shim/core/emulator_settings.h` |
| `HONEST_DRAIN_FLUSH` | on; `0` turns it off | SKY_RENDERER_HONEST_DRAIN_FLUSH (default on): also at once when the GPU is on the last submission (everything before it finished): it would run dry before the next batch, and the frame's work recorded meanwhile waited for the interval (~1 ms of GPU idle a frame). | `gpu/render/raster_signals.cpp` |
| `HONEST_FLUSH_US` | `2000` | (read in Rasterizer::SubmitForSignalsNow) | `gpu/render/raster_signals.cpp` |
| `HONEST_IDLE_FLUSH` | on; `0` turns it off | Batched (one submission per SKY_RENDERER_HONEST_FLUSH_US) while the GPU still has work; at once when it has finished everything submitted: holding the work back then only leaves it idle. Not at once while draws are queued for this thread (SKY_RENDERER_HONEST_IDLE_BACKLOG bytes, default 64 KiB): it is then what the GPU waits for, and a submission costs it ~65 us (heavy scenes: 13 a frame; 95 -> 100 | `gpu/render/raster_signals.cpp` |
| `HONEST_IDLE_US` | `200` | this thread has had nothing to do for SKY_RENDERER_HONEST_IDLE_US (0.2 ms): the guest may be waiting. | `gpu/cp/command_processor.cpp` |
| `HONEST_LABELS` | off; `1` (or a value) turns it on | (read in Rasterizer::HonestLabels) | `gpu/render/raster_signals.cpp` |
| `HOST_COPY_WAITS` |  | it (Scheduler::WaitHostCopiesFor). SKY_RENDERER_HOST_COPY_WAITS=all: always (the old behaviour). | `gpu/render/rasterizer.h` |
| `HOT_PAGES` | off; `1` (or a value) turns it on | Hot pages (SKY_RENDERER_HOT_PAGES=1): pages the guest writes again and again (per-frame constants, skinning output) cost a fault in the writer plus a re-watch on every upload; after HotFaults faults a page stays unwatched and counts as always CPU-modified, uploaded on every use instead. The set is rebuilt every HotPeriod. Opt-in: in Hunter's Nightmare it grew to ~14k pages (56 MB), each re-uploade | `gpu/memory/dirty_tracker.h` |
| `IMAGE_TRAPS` | on; `0` turns it off | game's code; the hooks and the libc wrappers only make it sooner. SKY_RENDERER_IMAGE_TRAPS=0: announced writes only. Latched at the first use: the counts must match their traps for the whole run. | `gpu/memory/page_watch.cpp` |
| `INDIRECT_GUARD` | on; `0` turns it off | (read in IndirectGuard::Enabled) | `gpu/render/vk_indirect_guard.cpp` |
| `INDIRECT_GUARD_MAX` |  |  | `gpu/render/vk_indirect_guard.cpp` |
| `INDIRECT_GUARD_MAX_VERTICES` |  |  | `gpu/render/vk_indirect_guard.cpp` |
| `INPLACE_TEXTURES` | off; `1` (or a value) turns it on | Off by default: sampled data looked smeared and ghosted with it (2026-10-04). | `gpu/buffers/buffer_cache.cpp` |
| `INTERNAL_HEIGHT` | `1920` | (read in GetInternalScreenHeight) | `gpu/shim/core/emulator_settings.h` |
| `INTERNAL_WIDTH` | `-1` | (read in GetInternalScreenWidth) | `gpu/shim/core/emulator_settings.h` |
| `INTERP_INT_FIX` |  | Older NVIDIA (Pascal) has no barycentrics; SKY_RENDERER_INTERP_INT_FIX=0/1 overrides. | `gpu/render/pipeline_cache.cpp` |
| `LAYER_GPU_WRITES` | `1` | Anywhere (2) gave exploding vertices and garbage textures: GPU data in a VRAM copy of memory the CPU also uses (the game's buffers, its heap's headers, reused allocations) went stale or was copied back over newer CPU data. Images (render targets) are the GPU's own. | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_MEMORY` |  | (SKY_RENDERER_LAYER_MEMORY=0: the sparse arena; NVIDIA's sparse binding stalls for seconds). | `gpu/shim/renderer_guest_memory.cpp` |
| `LAYER_MIRROR_FLOOR_PERCENT` |  | SKY_RENDERER_LAYER_MIRROR_FLOOR_PERCENT (25) of the driver's VRAM budget: the mirrors' share that the texture collector's mark does not take from them (6 GB: ~1.4 GB, 4 GB: ~0.9 GB). Past it they yield to images; under it images yield (the collector evicts more), up to the budget's SKY_RENDERER_VRAM_PROMOTE_PERCENT. Reading the game's memory over the bus costs far more on NVIDIA. | `gpu/buffers/buffer_cache.cpp` |
| `LAYER_MIRROR_GROWTH_MB` |  | SKY_RENDERER_LAYER_MIRROR_GROWTH_MB (64; 0: none): the most room a growing mirror gets above it. | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_PROBE` | off; `1` (or a value) turns it on | (read in BufferCache::LayerProbeOn) | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_READ_TRAPS` | off; `1` (or a value) turns it on | SKY_RENDERER_LAYER_READ_TRAPS=1: what the GPU writes into a VRAM copy only is no access for the CPU until it is copied back (LayerReadTrapHit): the game or the translator reading it on the CPU would see stale data (on the PS4 the memory is one). Off by default for now. | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_RELOAD_RESET` | on; `0` turns it off | (layer_cpu_hot) stay dynamic. SKY_RENDERER_LAYER_RELOAD_RESET=0: as before. | `gpu/buffers/buffer_cache.cpp` |
| `LAYER_UNMAP_RESET` | on; `0` turns it off | there again starts as new. SKY_RENDERER_LAYER_UNMAP_RESET=0: as before. | `gpu/buffers/buffer_cache.cpp` |
| `LAYER_VOLATILE` | off; `1` (or a value) turns it on | Volatile blocks (SKY_RENDERER_LAYER_VOLATILE=1; off by default): a range with a few unannounced blocks goes into one mirror anyway, those blocks refreshed for every binding that reads them. Off, the range stays mixed (in place). Their refreshes were ~300 MB/s of copies and, in render passes, up to ~100 pass breaks a frame; on a recorded route off was 4.29-4.31 ms of GPU time a frame, on 4.31-4.53  | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_VOLATILE_IN_PASS` | on; `0` turns it off | SKY_RENDERER_LAYER_VOLATILE_IN_PASS=0: refreshed in passes too (as before). | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_WRITE_TRAPS` | on; `0` turns it off | (read in LayerTrapsOn) | `gpu/layer/buffer_cache_layer.cpp` |
| `MEM_SEMAPHORE_ORDER` | on; `0` turns it off | (read in MemSemaphoreInOrder) | `gpu/cp/cp_compute.cpp`, `gpu/cp/cp_graphics.cpp` |
| `MENU_LANGUAGE` |  | launcher's (SKY_RENDERER_MENU_LANGUAGE), else the system's, as the launcher picks its own. | `gpu/shim/renderer_settings.cpp` |
| `NULL_GPU` | off | (read in IsNullGPU) | `gpu/shim/core/emulator_settings.h` |
| `OCCLUSION_LABEL_ORDER` | on; `0` turns it off | A label ahead of results not written yet would let the CPU see the label before them. (Once taken for the cause of slow launches; that was volatile blocks' refresh copies breaking render passes, BufferCache::LayerVolatileAllowed. The game reads its results 2-10 ms after the event and finds them written either way: SKY_RENDERER_OCCLUSION_READ_TRACE.) | `gpu/render/vk_occlusion.cpp` |
| `OCCLUSION_QUERIES` | on; `0` turns it off | Vulkan occlusion queries (SKY_RENDERER_OCCLUSION_QUERIES=0: the fixed sequence written when decoded, everything visible, as in the 0.3 model). | `gpu/render/raster_signals.cpp` |
| `PC_MODEL_ANY_GPU` |  | (only with SKY_RENDERER_PC_MODEL_ANY_GPU=1): its host memory import passes those checks, but each rebinding of the game's memory (vkQueueBindSparse, blocks moved to and from VRAM) held the GPU for 10 s and more, the desktop frozen with it (GTX 1660 Ti, driver 615.71). The Linux driver's sparse binding has slowed down since 555: the time grows with the pages already bound (NVIDIA developer forum, " | `gpu/shim/renderer_guest_memory.cpp` |
| `PIPELINE_CACHE` | off | (read in IsPipelineCacheEnabled) | `gpu/shim/core/emulator_settings.h` |
| `PIPE_SIGNALS` | on; `0` turns it off | (read in Rasterizer::PipeSignals) | `gpu/render/raster_signals.cpp` |
| `PIPE_SPIN_US` |  | game's own threads. SKY_RENDERER_PIPE_SPIN_US overrides. | `gpu/render/vk_draw_pipe.h` |
| `PM4_RECOVER` | on; `0` turns it off | twice is the same as once). SKY_RENDERER_PM4_RECOVER=0: stop as before. | `gpu/cp/cp_graphics.cpp` |
| `PM4_WAIT_US` |  | The game may still be writing this buffer (a packet written after the walk began): it is read again for a few milliseconds before it counts as bad. A buffer that stays bad is reported as before, with the time it was waited. | `gpu/cp/cp_graphics.cpp` |
| `PREFETCH_PIPELINES` | on; `0` turns it off | (read in PipelineCache::PrefetchGraphicsPipeline) | `gpu/render/pipeline_cache.cpp` |
| `PRELOAD_THREADS` |  | threads; the VkPipelineCache is created without EXTERNALLY_SYNCHRONIZED. SKY_RENDERER_PRELOAD_THREADS sets the count (1 keeps the original one-at-a-time preload). | `gpu/render/pipeline_store.cpp` |
| `PREP_WORKERS` |  | (read in DefaultWorkerCount) | `gpu/render/vk_draw_prep.cpp` |
| `PRESENT_AS_READY` | off | (read in std::chrono::nanoseconds) | `gpu/platform/videoout/display.cpp` |
| `PRESENT_MODE` | `1080` | (read in GetPresentMode) | `gpu/shim/core/emulator_settings.h` |
| `PRESENT_REPEAT` | on; `0` turns it off | without). SKY_RENDERER_PRESENT_REPEAT=1 keeps it regardless; =0 leaves it out (RepeatAt). | `gpu/render/display_pacer.cpp`, `gpu/render/presenter.cpp` |
| `PRESENT_THREAD` | on; `0` turns it off |  | `gpu/platform/videoout/display.cpp` |
| `PREUPLOAD` |  | SKY_RENDERER_PREUPLOAD — background upload of the game's GPU memory into the arena ahead of use. 1 (run.sh default): only memory already resident in the arena that the game rewrote, and textures from the arena only where it is resident: no new VRAM. 2: all of the game's GPU memory, textures always from the arena (~3 GB more VRAM, the shared memory on a Steam Deck). 0: off. | `gpu/buffers/buffer_cache.cpp` |
| `PREUPLOAD_MB` |  | uploaded ahead of its use, SKY_RENDERER_PREUPLOAD_MB (16) at most per frame. | `gpu/render/rasterizer.cpp` |
| `READBACKS` |  | Relaxed by default: without readbacks FaceGen reads stale GPU-written vertices (vertex explosions); in Hunter's Nightmare it costs no measurable frame rate. | `gpu/shim/core/emulator_settings.h` |
| `READBACK_LINEAR` | on | (read in IsReadbackLinearImagesEnabled) | `gpu/shim/core/emulator_settings.h` |
| `READBACK_QUEUE` | on; `0` turns it off |  | `gpu/vulkan/instance.cpp` |
| `RESIDENCY_MIX` | off; `1` (or a value) turns it on | SKY_RENDERER_RESIDENCY_MIX=1: bindings per kind (none, in place, mirror, mixed) and written, per 2 s. | `gpu/buffers/buffer_cache.cpp`, `gpu/layer/buffer_cache_layer.cpp` |
| `RESOLVE_WORKERS` | `0` | SKY_RENDERER_RESOLVE_WORKERS=n (stage 2, docs/pipeline_4stage.ru.md): threads that check and copy the constants of draws between the GPU command thread and the recording thread. | `gpu/render/rasterizer.cpp` |
| `SHADOWS` | off; `1` (or a value) turns it on |  | `gpu/buffers/buffer_cache.cpp` |
| `SPECULATIVE_SHADERS` | on; `0` turns it off | SKY_RENDERER_SPECULATIVE_SHADERS=0: workers leave new programs to the GPU thread. | `gpu/render/pipeline_cache.cpp` |
| `STAGING_KEEP_MB` |  | (read in Mapped) | `gpu/vulkan/staging_pool.cpp` |
| `STALL_THREADS` | on; `0` turns it off | SKY_RENDERER_STALL_THREADS=0: the command thread only. | `gpu/cp/command_processor.cpp` |
| `STALL_THREADS_DONE` |  | once per run | `gpu/cp/command_processor.cpp` |
| `SUBMIT_AHEAD` | `2` | (read in SubmitsAheadOption) | `gpu/platform/gnm/gnm_driver.cpp` |
| `SUBMIT_LOCK` |  | (read in SubmitLock) | `gpu/platform/gnm/gnm_driver.cpp` |
| `TEXTURE_HELPER` |  | A spinning helper pays off only with cores to spare (the recording thread spins too). | `gpu/render/raster_bind.cpp` |
| `TILE_BIND_VRAM` | on; `0` turns it off | SKY_RENDERER_TILE_BIND_VRAM=0: read in place. | `gpu/buffers/buffer_cache.cpp` |
| `TOGGLE_FILE` |  | (read in runtime_memory_set_gpu_hooks) | `src/runtime_memory.c` |
| `TRIM_SHADER_WARMUP` | off; `1` (or a value) turns it on | Warm-up releases temporary compiler allocations before returning. Give unused arena pages back once, before gameplay, rather than retaining them. | `gpu/render/pipeline_cache.cpp` |
| `UFFD` |  | dma-buf guest memory (SKY_RENDERER_GUEST_GPU_MEMORY=1) cannot be write-protected by userfaultfd (anonymous and shmem only): its registration would fail and writes go unseen. | `gpu/memory/page_watch.cpp` |
| `VBLANK_HZ` | `60` | uncapped presets (run.sh: SKY_RENDERER_VBLANK_HZ=1000; 0 means 480): vblank runs at 1000 Hz, and a finished frame is presented as soon as it arrives (IsUncappedVblank), not on the next vblank tick (at the display rate frames alternated 10/20 ms at 100 Hz: judder; at 480 Hz they snap to ~2.1 ms steps). The frame rate is not limited unless SKY_RENDERER_FPS_LIMIT (launcher: "FPS limit") asks for it.  | `gpu/shim/core/emulator_settings.h` |
| `VK_RECORD_THREAD` | on; `0` turns it off | SKY_RENDERER_VK_RECORD_THREAD=0 records on the calling thread. | `gpu/render/scheduler.cpp` |
| `VK_RECORD_THREADS` |  | Vulkan recording threads: SKY_RENDERER_VK_RECORD_THREADS, else 2 from 8 hardware threads and 3 from 12. One thread records ~75% of a core at 200 FPS (4 cores / 8 threads); the segments let the stream use more than one. | `gpu/render/scheduler.cpp` |
| `VK_SEGMENT_KB` |  | A segment of ~64 KiB of closures is ~60 draws: a frame of ~700 draws gives each thread several segments, and the render passes a cut reopens stay few. | `gpu/render/scheduler.cpp` |
| `VMA_BLOCK_MB` |  | and held. SKY_RENDERER_VMA_BLOCK_MB=N. | `gpu/vulkan/instance.cpp` |
| `VMA_DEDICATED_MB` |  | Images of SKY_RENDERER_VMA_DEDICATED_MB (4) or more get memory of their own, returned to the driver when they are freed: in shared blocks the collector's evictions left holes a block only returns once wholly empty (~0.9 GB on an RX 7800 XT). | `gpu/textures/image.cpp` |
| `VRAM_ACCESS_TRAP` | off; `1` (or a value) turns it on | (read in VramTrapsEnabled) | `gpu/buffers/buffer_cache.cpp` |
| `VRAM_IDLE_SECONDS` | `60` | SKY_RENDERER_VRAM_IDLE_SECONDS set: on any card. | `gpu/buffers/buffer_cache.cpp` |
| `VRAM_PRESSURE_IDLE_SECONDS` | `3` |  | `gpu/layer/buffer_cache_layer.cpp` |
| `VRAM_PROMOTE_PERCENT` | `90` | VRAM nearly full (past SKY_RENDERER_VRAM_PROMOTE_PERCENT of the driver's budget, default 90): no new copies; the candidates wait, read in place meanwhile (#32: a card with 8 GB). Checked at most once a second (the query goes to the driver). | `gpu/buffers/buffer_cache.cpp` |
| `VRAM_TRAP_RANGE` |  | SKY_RENDERER_VRAM_TRAP_RANGE=addr,size: only blocks over that range, re-armed for every packet, every access counted by site. | `gpu/buffers/buffer_cache.cpp` |
| `WORK_RETIRED` | on; `0` turns it off | (read in CommandProcessor::IsGpuIdle) | `gpu/cp/command_processor.cpp` |
| `WRITE_TRACKING` | `2` | (read in Detail::ComputeWriteTracking) | `gpu/buffers/memory_model.cpp` |

## Diagnostics (off unless set) (93)

| Option | Default | Description | Read in |
|---|---|---|---|
| `AUDIO_CONTROL_TRACE` |  | (read in audio_volume) | `src/runtime_audio.c` |
| `AUDIO_DUMP` |  | (read in fprintf) | `src/runtime_audio.c` |
| `AUDIO_STATS` |  | (read in fprintf) | `src/runtime_audio.c` |
| `AUDIO_TRACE` | off; `1` (or a value) turns it on | (read in ajm_trace) | `src/runtime_ajm.c` |
| `BARRIER_STATS` | off; `1` (or a value) turns it on |  | `gpu/textures/image.cpp` |
| `BREADCRUMBS` |  | (read in Init) | `gpu/render/vk_breadcrumbs.cpp` |
| `BREADCRUMB_READS` |  | few T# and V# reads a draw. SKY_RENDERER_BREADCRUMB_READS=1 / 0: on / off everywhere. | `gpu/render/rasterizer.cpp` |
| `BUFFER_STATS` | off; `1` (or a value) turns it on | SKY_RENDERER_BUFFER_STATS=1: how many earlier frames the GPU has not finished when the GPU thread starts a frame — the lag that decides whether guest memory can be read in place. | `gpu/buffers/buffer_cache.cpp`, `gpu/render/rasterizer.cpp` |
| `CAPTURE_DIR` |  | (read in Write) | `gpu/render/vk_frame_capture.cpp` |
| `CAPTURE_FLIPS` |  | Opt-in: Trap Team writes display buffers more than once per frame. Capture a bounded software-flip interval without treating each such pass as a frame. | `gpu/render/vk_frame_capture.cpp` |
| `CAPTURE_TRIGGER` |  | (read in FrameCapture::OnFlip) | `gpu/render/vk_frame_capture.cpp` |
| `CE_STATS` | off; `1` (or a value) turns it on | (read in Enabled) | `gpu/shim/renderer_ce_stats.h` |
| `CE_WAIT_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_CE_WAIT_LOG=1 (diagnostics): a wait the constant engine did not satisfy (its buffer ended or never started): the draws after it read constants not dumped for them. | `gpu/cp/cp_graphics.cpp` |
| `CE_WATCH` |  | SKY_RENDERER_CE_WATCH=addr (diagnostics): constant RAM dumps and WRITE_DATA packets over that address. | `gpu/cp/cp_graphics.cpp` |
| `CONSTANT_RING_MB` | `0` | 32 MiB; SKY_RENDERER_CONSTANT_RING_MB (diagnostics) another size. | `gpu/render/vk_constant_ring.h` |
| `COPY_SHADER_TRACE` | off; `1` (or a value) turns it on | SKY_RENDERER_COPY_SHADER_TRACE=1 (diagnostics): the copy shader's buffers, every 2 s. | `gpu/render/shader_hle.cpp` |
| `CORPUS_DUMP` |  | SKY_RENDERER_CORPUS_DUMP=<dir>: the recorded SPIR-V and the GCN program of each record, by name. | `tests/test_shader_corpus.cpp` |
| `DCB_STATS` | off | (read in DcbStatsEnabled) | `gpu/cp/cp_diagnostics.cpp` |
| `DISPATCH_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_DISPATCH_LOG=1 (diagnostics): the shape of each kind of real compute dispatch, once: the buffers (size, formatted, written), the groups, and what the image clear detector thinks. | `gpu/render/rasterizer.cpp` |
| `DISPATCH_START_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_DISPATCH_START_LOG=1 (diagnostics, the flicker): dispatches with a nonzero thread group start (COMPUTE_START_X/Y/Z), which the translation does not apply. | `gpu/render/rasterizer.cpp` |
| `DISPLAY_LOG` |  | SKY_RENDERER_DISPLAY_LOG=<file>: one row per presented frame, with when it was shown. | `gpu/render/display_pacer.cpp` |
| `DISPLAY_WATCH` | off; `1` (or a value) turns it on | SKY_RENDERER_DISPLAY_WATCH=1 (diagnostics): every draw into a display buffer, with its sizes and state. | `gpu/render/rasterizer.cpp` |
| `DISPLAY_WATCH_TARGET` |  | SKY_RENDERER_DISPLAY_WATCH_TARGET=addr: also every draw into that color target. | `gpu/render/rasterizer.cpp` |
| `DRAW_WATCH` | off; `1` (or a value) turns it on |  | `gpu/render/rasterizer.cpp` |
| `DRAW_WATCH_TEXTURES` | off; `1` (or a value) turns it on |  | `gpu/render/rasterizer.cpp` |
| `DUMP_DIR` |  | (read in Rasterizer::DumpTracedInputs) | `gpu/render/rasterizer.cpp` |
| `DUMP_SHADERS` | off | (read in IsDumpShaders) | `gpu/shim/core/emulator_settings.h` |
| `DYNAMIC_STATE_ALWAYS` | off; `1` (or a value) turns it on | SKY_RENDERER_DYNAMIC_STATE_ALWAYS=1 (diagnostics): all dynamic state again at every draw. | `gpu/render/rasterizer.cpp` |
| `DYNSTATE_CHECK` | off; `1` (or a value) turns it on | (read in Enabled) | `gpu/render/raster_state.cpp` |
| `FPS_PRINT` | off; `1` (or a value) turns it on | SKY_RENDERER_FPS_PRINT=1: the present rate every 5 s on stdout, without the cost of SKY_RENDERER_FRAME_STATS (its timers are in the draw path): to measure as players run the game. | `gpu/shim/renderer_overlay.cpp` |
| `FRAME_LOG` |  | SKY_RENDERER_FRAME_LOG=path (with SKY_RENDERER_FRAME_STATS): one line per flip, to find what the long frames (stutter) have in common. | `gpu/platform/videoout/frame_stats.cpp` |
| `FRAME_STATS` | off | Stage A: cycles waited per drain site (SKY_RENDERER_FRAME_STATS), keyed by function name and line. | `gpu/platform/videoout/frame_stats.cpp`, `gpu/render/raster_bind.cpp`, `gpu/render/raster_pipe.cpp`, `gpu/render/vk_draw_prep.cpp`, `gpu/shim/renderer_toggles.h` |
| `GAME_PROFILE` |  | (read in Select) | `gpu/games/game_profile.cpp` |
| `GARLIC_VRAM_RANGE` | `0` | Diagnostics: SKY_RENDERER_GARLIC_VRAM_RANGE=begin,end keeps VRAM copies to guest addresses in [begin, end) (finding the block whose copy goes stale by halving the range). | `gpu/buffers/buffer_cache.cpp` |
| `GNM_WRITES_TRACE` | off; `1` (or a value) turns it on | (read in RememberSubmittedCopy) | `gpu/cp/cp_diagnostics.cpp` |
| `GPU_DATA_CHECK` | on; `0` turns it off | the game's memory under it is older (issue #122). SKY_RENDERER_GPU_DATA_CHECK=0: not counted. | `gpu/buffers/buffer_cache.cpp` |
| `GPU_LOG` |  | (read in Threshold) | `gpu/common/logging/log.cpp` |
| `GPU_PROFILE` |  | (read in GpuProfiler::Init) | `gpu/render/vk_gpu_profiler.cpp` |
| `GPU_WRITE_WATCH` | `0` | SKY_RENDERER_GPU_WRITE_WATCH=address (diagnostics): GPU writes noted over the 64 KiB page holding it. | `gpu/buffers/buffer_cache.cpp` |
| `HLE_STATS` | off; `1` (or a value) turns it on | SKY_RENDERER_HLE_STATS=1 (diagnostics): how often the compute shader substitutions fire. | `gpu/render/raster_bind.cpp` |
| `HONEST_IDLE_BACKLOG` |  | once while draws are queued for this thread (SKY_RENDERER_HONEST_IDLE_BACKLOG bytes, default 64 KiB): it is then what the GPU waits for, and a submission costs it ~65 us (heavy scenes: 13 a frame; 95 -> 100 FPS with half as many). | `gpu/render/raster_signals.cpp` |
| `IMAGE_CLEAR_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_IMAGE_CLEAR_LOG=1: why a clear shader (cs 8b355b5a) went to the real shader, once per reason and group count: the number of the failing check in IsComputeImageClear. | `gpu/render/raster_compute_hle.cpp` |
| `IMAGE_COPY_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_IMAGE_COPY_LOG=1 (diagnostics): the copies recognized. | `gpu/render/raster_bind.cpp`, `gpu/render/raster_compute_hle.cpp` |
| `IMAGE_SYNC_LOG` | off; `1` (or a value) turns it on | Only fully overwritten images starting at `address` can be refreshed wholesale. A partial overwrite must preserve the image's other GPU-only texels. | `gpu/textures/texture_cache_track.cpp`, `gpu/textures/texture_cache_upload.cpp` |
| `IMAGE_WATCH` | `0` | (read in TextureCache::WatchImage) | `gpu/textures/texture_cache_track.cpp` |
| `INPLACE_READ_CHECK` | off; `1` (or a value) turns it on | (read in Enabled) | `gpu/render/raster_pipe.cpp` |
| `LAYER_PAGED_STATS` | off; `1` (or a value) turns it on | SKY_RENDERER_LAYER_PAGED_STATS=1 (diagnostics): paged bindings per shader, every 5 s. | `gpu/render/raster_bind.cpp` |
| `LAYER_VERIFY` |  | SKY_RENDERER_LAYER_VERIFY=2: every unannounced change of a mirrored block (refreshes too). | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_WATCH` | on; `0` turns it off | SKY_RENDERER_LAYER_WATCH=1/0 (default 1). The reads over the bus cost far more on NVIDIA's imported host memory than on AMD's dma-buf (GTX 1660 Ti: 30-35 FPS with the module, 60-70 with the model of 0.3; RX 7800 XT: on par). It also replaces most volatile blocks, refreshed for every binding (RX 7800 XT: 1.3 GB/s of copies -> 36 MB/s). Needs the write traps (SKY_RENDERER_LAYER_WRITE_TRAPS). | `gpu/layer/buffer_cache_layer.cpp` |
| `LAYER_WRITE_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_LAYER_WRITE_LOG=1 (diagnostics): large GPU writes kept in place, and the images near them. | `gpu/layer/buffer_cache_layer.cpp` |
| `OCCLUSION_READ_TRACE` | off; `1` (or a value) turns it on | (read in OcclusionQueries::ReadTrace) | `gpu/render/vk_occlusion.cpp` |
| `OCCLUSION_SAMPLES` | `0` | SKY_RENDERER_OCCLUSION_SAMPLES=N (diagnostics): the samples the game read, N queries. | `gpu/render/vk_occlusion.cpp` |
| `OCCLUSION_TRACE` | `0` | SKY_RENDERER_OCCLUSION_TRACE=N (diagnostics): the first N events, with the frame and the render pass. | `gpu/render/vk_occlusion.cpp` |
| `PASS_BREAK_TRACE` | off; `1` (or a value) turns it on | (read in Scheduler::EndRendering) | `gpu/render/scheduler.cpp` |
| `PASS_DUMP` |  | SKY_RENDERER_PASS_DUMP=addr,addr (hex guest addresses of render targets) with SKY_RENDERER_PASS_DUMP_TRIGGER=<file> (diagnostics, the flicker): while the file exists, every 8th row of those images is saved at each display pass (SKY_RENDERER_DUMP_DIR/pNNNNN_<addr>_<w>x<h>_<bits>.raw), little enough not to change the frame's timing much. | `gpu/render/rasterizer.cpp` |
| `PASS_DUMP_AT` |  | SKY_RENDERER_PASS_DUMP_AT=addr (diagnostics): SKY_RENDERER_PASS_DUMP's images also before the first draw of a pass into that color target ('q' files). | `gpu/render/rasterizer.cpp` |
| `PASS_DUMP_STEP` | `8` |  | `gpu/render/rasterizer.cpp` |
| `PASS_DUMP_TRIGGER` |  | (read in Rasterizer::DumpPassImages) | `gpu/render/rasterizer.cpp` |
| `PIPE_VERIFY` | `0` | (read in VerifyInterval) | `gpu/render/raster_pipe.cpp` |
| `PM4_SELFTEST` | off; `1` (or a value) turns it on | (read in Enabled) | `gpu/cp/pm4_selftest.cpp` |
| `PM4_SELFTEST_STEPS` |  | SKY_RENDERER_PM4_SELFTEST_STEPS=mask (diagnostics): the steps run (bit n: step n); others skipped. | `gpu/cp/pm4_selftest.cpp` |
| `PRODUCER_CHECK` | off; `1` (or a value) turns it on | SKY_RENDERER_PRODUCER_CHECK=1 (the launcher's crash diagnostics); off otherwise, the check costs an atomic exchange per recorded command. | `gpu/render/scheduler.h` |
| `READBACK_LOG` |  | SKY_RENDERER_READBACK_LOG=path — every download of GPU-written buffer memory back to guest memory (a CPU write to a range the GPU wrote): who asked, where, how much, how long it took, how old the GPU's newest write there was, and whether the readback queue served it. | `gpu/buffers/buffer_cache.cpp` |
| `RECORDER_TRACE` | off; `1` (or a value) turns it on | (read in Scheduler::TraceDirectRecording) | `gpu/render/scheduler.cpp` |
| `RESIDENCY_REPORT` |  | SKY_RENDERER_RESIDENCY_REPORT=<file>: when the file appears (checked once a second), the blocks bound in place that were used in the last seconds, and why they have no VRAM copy. | `gpu/buffers/buffer_cache.cpp` |
| `RES_STATS` | off; `1` (or a value) turns it on | (read in NoteResStats) | `gpu/render/raster_bind.cpp` |
| `RING_REASONS` | off; `1` (or a value) turns it on | SKY_RENDERER_RING_REASONS=1 (diagnostics): why small read-only bindings were not copied, per 5 s. | `gpu/render/raster_pipe.cpp` |
| `SECTIONS` | off; `1` (or a value) turns it on | (read in Enabled) | `gpu/shim/renderer_sections.h` |
| `SHADER_CAPTURE` |  | (read in Directory) | `gpu/render/shader_capture.cpp` |
| `SKIP_PS` |  | SKY_RENDERER_SKIP_PS=hash[,hash...] (diagnostics): draws with these pixel shaders are left out. | `gpu/render/rasterizer.cpp` |
| `STALL_REPORT` | on; `0` turns it off |  | `gpu/cp/command_processor.cpp` |
| `TARGET_SIZE_TRACE` | off; `1` (or a value) turns it on | Optional bounded inventory of actual bound attachments, not presentation size. | `gpu/render/raster_targets.cpp` |
| `TICK_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_TICK_LOG=1 (diagnostics): the ranges marked written by the GPU most often, per 5 s. | `gpu/buffers/buffer_cache.cpp` |
| `TILE_BACK_LOG` | off; `1` (or a value) turns it on | SKY_RENDERER_TILE_BACK_LOG=1 (diagnostics): each image written back into the game's memory because a texel buffer reads it, with the age of its last GPU write in submissions. | `gpu/buffers/buffer_cache.cpp` |
| `TIMELINE` |  |  | `gpu/shim/renderer_timeline.h` |
| `TIMELINE_START` |  |  | `gpu/shim/renderer_timeline.h` |
| `TRACE_ADDR` |  | SKY_RENDERER_TRACE_ADDR=addr,size: that range is traced from the start (with SKY_RENDERER_TRACE_SIZE set). | `gpu/buffers/buffer_cache.cpp` |
| `TRACE_CB` | `0` | SKY_RENDERER_TRACE_CB=hash (diagnostics): how that shader's constant buffers were bound. | `gpu/render/raster_pipe.cpp` |
| `TRACE_CB_LIST` |  | SKY_RENDERER_TRACE_CB_LIST=hash,hash (diagnostics): their constants against the same draw's last frame. | `gpu/render/raster_pipe.cpp` |
| `TRACE_GPU_INPUTS` | `0` | SKY_RENDERER_TRACE_GPU_INPUTS=vs hash (diagnostics, the flicker): the buffer ranges this draw reads (descriptors and vertex streams), copied by the GPU at the next display pass (DumpPassImages). | `gpu/render/rasterizer.cpp` |
| `TRACE_PIPELINE` | `0` | SKY_RENDERER_TRACE_PIPELINE=vs hash (diagnostics, the flicker): its pipeline handle and push data, printed when they differ from its previous draw. | `gpu/render/rasterizer.cpp` |
| `TRACE_SHADER` |  | SKY_RENDERER_TRACE_SHADER: the draw's counts and streams too, once a second. | `gpu/render/raster_bind.cpp`, `gpu/render/rasterizer.cpp` |
| `TRACE_SIZE` |  | (read in BufferCache::TraceBinding) | `gpu/buffers/buffer_cache.cpp` |
| `TRACE_VERTEX_DATA` | off; `1` (or a value) turns it on | SKY_RENDERER_TRACE_VERTEX_DATA=1 with SKY_RENDERER_TRACE_SHADER: the stream bytes whenever they differ from the traced shader's previous draw (what it reads when this copy is taken). | `gpu/render/raster_bind.cpp` |
| `UPLOAD_DUMP_DIR` |  | SKY_RENDERER_UPLOAD_DUMP_DIR (diagnostics, movie planes): the guest bytes of the first 240 refreshes of images at least 1900 texels wide, as read for the upload, named uNNNN_<addr>_<w>x<h>_fmt<f>_tile<t>_pitch<p>_frame<gpu frame>.raw. | `gpu/textures/texture_cache_upload.cpp` |
| `VK_MARKERS` | off | (read in IsVkGuestMarkersEnabled) | `gpu/shim/core/emulator_settings.h` |
| `VK_VALIDATION` | off | (read in IsVkValidationEnabled) | `gpu/shim/core/emulator_settings.h` |
| `VK_VALIDATION_SYNC` | off | (read in IsVkValidationSyncEnabled) | `gpu/shim/core/emulator_settings.h` |
| `WAIT_TRACE` | off; `1` (or a value) turns it on | (read in Enabled) | `gpu/shim/renderer_wait_trace.cpp` |
| `WARN_META_TEXTURE` | off; `1` (or a value) turns it on | a hash lookup per texture per draw for a diagnostic only. | `gpu/render/raster_textures.cpp` |
| `WATCH` |  | SKY_RENDERER_WATCH=addr,size (diagnostics): what the translator reads from that range on the CPU: user data pointing into it, constants copied from it; printed every 2 s. | `gpu/render/raster_pipe.cpp` |
| `WRITE_LOG` | `0` | (read in Mode) | `gpu/shim/renderer_write_log.cpp` |
| `WRITE_VERIFY` |  | (read in WriteVerify) | `gpu/buffers/memory_model.cpp` |

## Experiments (A/B switches for hunting bugs) (18)

| Option | Default | Description | Read in |
|---|---|---|---|
| `COPY_SHADER_NATIVE` | on; `0` turns it off | copy list when the GPU executes it. SKY_RENDERER_COPY_SHADER_NATIVE=0: the list read on the CPU when the dispatch is recorded, copies of our own (before). Experiment bit 2 inverts it while the game runs. The layer's paged stores now write through to guest memory while keeping the current mirrors in sync, so the original shader is the default here too. | `gpu/render/shader_hle.cpp` |
| `EXP_BARRIER_ALL` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_BARRIER_ALL=1 (experiment): a full memory barrier before every draw and dispatch. | `gpu/render/raster_bind.cpp` |
| `EXP_BARRIER_TARGET` |  | SKY_RENDERER_EXP_BARRIER_TARGET=addr (experiment): a full memory barrier before each draw into that color target (its render pass is ended first). | `gpu/render/rasterizer.cpp` |
| `EXP_CONSTRAM_FINISH` | `0` | SKY_RENDERER_EXP_CONSTRAM_FINISH=1 (experiment): every dump waits until the GPU has run all earlier work. 2: stage B catches up and submits, no GPU wait; 3: waits for the GPU only (work submitted). | `gpu/render/raster_pipe.cpp` |
| `EXP_COPY_SRC_SNAPSHOT` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_COPY_SRC_SNAPSHOT=1 (experiment): the source bytes as they are now, in the stream buffer (what the old memory model did), not read in place when the GPU gets there. | `gpu/render/shader_hle.cpp` |
| `EXP_DMA_UNTRACKED` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_DMA_UNTRACKED=1 (experiment): a stage that reads the game's memory through pointers when the GPU runs it (uses_dma) counts as reading memory it does not list: a constant RAM dump waits for the GPU to have run it. | `gpu/render/raster_pipe.cpp` |
| `EXP_FINISH_BEFORE_TARGET` |  | SKY_RENDERER_EXP_FINISH_BEFORE_TARGET=addr (experiment, the flicker): the GPU runs everything before a draw into that color target before the draw is recorded. | `gpu/render/rasterizer.cpp` |
| `EXP_FINISH_FRAMES` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_FINISH_FRAMES=1 (experiment): the GPU finishes each frame before the next. | `gpu/cp/command_processor.cpp` |
| `EXP_FLIP_FINISH` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_FLIP_FINISH=1 (experiment): the flip is signalled once the GPU has run the frame. | `gpu/cp/cp_tasks.cpp` |
| `EXP_FLIP_LAG` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_FLIP_LAG=1 (experiment): the GPU has finished the frame before this one (one frame in flight at most). | `gpu/cp/cp_tasks.cpp` |
| `EXP_NO_STREAM` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_NO_STREAM=1 (experiment, the flicker): never through the stream buffer. | `gpu/buffers/buffer_cache.cpp` |
| `EXP_PAGED_IN_PLACE` | off; `1` (or a value) turns it on | SKY_RENDERER_EXP_PAGED_IN_PLACE=1 (experiment, missing map geometry after area loads): paged bindings read the game's memory itself, never a VRAM copy. | `gpu/layer/buffer_cache_layer.cpp` |
| `EXP_TRANSIT_TARGET` |  | SKY_RENDERER_EXP_TRANSIT_TARGET=addr (experiment): the target image goes through TransferSrcOptimal before the first draw of a pass into it (what SKY_RENDERER_PASS_DUMP_AT does, without the copy). | `gpu/render/rasterizer.cpp` |
| `GUEST_VRAM` | off; `1` (or a value) turns it on | SKY_RENDERER_GUEST_VRAM=1 (experiment): the game's direct memory in VRAM the CPU maps through the PCI BAR (Resizable BAR), as GDDR is the PS4's one memory: no VRAM copies. | `gpu/shim/renderer_guest_memory.cpp` |
| `HLE_OFF` | `0` | SKY_RENDERER_HLE_OFF=mask (experiment): 1 image copy, 2 metadata clear, 4 image clear run as the game's shaders. | `gpu/render/raster_bind.cpp` |
| `HONEST_FLIPS` | off; `1` (or a value) turns it on | SKY_RENDERER_HONEST_FLIPS=1 (an experiment): the flip completes once the GPU has finished the frame, as on the console (a vblank after the frame's commands end), instead of when it is queued. | `gpu/platform/videoout/display.cpp` |
| `LAYER_WATCH_HOT` | off; `1` (or a value) turns it on | SKY_RENDERER_LAYER_WATCH_HOT=1 (experiment): blocks the CPU writes often (NoteCpuWrite: in 3 of 60 frames) are watched too and uploaded again after every write, as the model of 0.3 uploads them. Off: they go back in place. Uploading them before bindings ended render passes (RX 7800 XT: the GPU's frame 4.8 -> 7.2 ms). | `gpu/layer/buffer_cache_layer.cpp` |
| `PRESENT_QUEUE` | off; `1` (or a value) turns it on | SKY_RENDERER_PRESENT_QUEUE=1 (an experiment): a second queue of the graphics family for presenting, so the copy of a finished frame into the swapchain image runs beside the next frame's work. Measured at 30 FPS fullscreen it made shown intervals less even, so it is off. | `gpu/vulkan/instance.cpp` |

## Test hooks (7)

| Option | Default | Description | Read in |
|---|---|---|---|
| `ARENA_VRAM_ONLY` | off; `1` (or a value) turns it on | SKY_RENDERER_ARENA_VRAM_ONLY=1 (tests): the arena takes VRAM only, as NVIDIA's sparse buffers do (with SKY_RENDERER_RESIDENCY_VRAM_LIMIT_MB: VRAM running out on such a card). | `gpu/buffers/buffer_cache.cpp` |
| `DISPLAY_PHASE` | off; `1` (or a value) turns it on | SKY_RENDERER_DISPLAY_PHASE=1 for testing. | `gpu/render/display_pacer.cpp` |
| `FIXED_ARENA` |  | SKY_RENDERER_FIXED_ARENA=1/0 forces it on/off (tests). Valid once the BufferCache checked the chunks. | `gpu/buffers/buffer_cache.cpp` |
| `LAYER_PAGED` | on; `0` turns it off | SKY_RENDERER_LAYER_PAGED=0 (tests): huge bindings cut in place instead of the page table. | `gpu/layer/buffer_cache_layer.cpp` |
| `MENU_KEYS_FILE` |  | SKY_RENDERER_MENU_KEYS_FILE=<file> (scripted tests): tokens toggle up down left right enter back l1 r1, consumed when the file appears (it is removed), one key press per frame. | `gpu/shim/renderer_overlay.cpp` |
| `RESIDENCY_VRAM_LIMIT_MB` | `0` | Slower, not fatal. SKY_RENDERER_RESIDENCY_VRAM_LIMIT_MB=N (tests): VRAM "full" after N MiB of blocks. | `gpu/buffers/buffer_cache.cpp` |
| `VRAM_LIMIT_MB` | `0` | SKY_RENDERER_VRAM_LIMIT_MB=N (tests): the driver's VRAM budget taken as at most N MiB, at startup and while the game runs, so the texture collector and VRAM copies behave as on a smaller card (a 6 GB GTX 1660 Ti reports ~5600). Allocations themselves are not limited. | `gpu/vulkan/instance.cpp` |

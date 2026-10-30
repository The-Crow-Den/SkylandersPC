// SPDX-License-Identifier: GPL-2.0-or-later
// renderer: SKY_RENDERER_FRAME_STATS=1: every 5 seconds, the flip rate, frame time spread and what the GPU
// side spent its time on; long frames (over 40 ms) get a line of their own. SKY_RENDERER_FRAME_LOG=path:
// one CSV line per flip.

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

#include <dirent.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

#include "renderer_toggles.h"
#include "renderer_wait_trace.h"
#include "core/emulator_settings.h"
#include "platform/kernel/event_queue.h"
#include "platform/videoout/frame_stats.h"
#include "render/vk_breadcrumbs.h"
#include "memory/fault_sites.h"
#include "vulkan/instance.h"
#include "render/scheduler.h"

extern "C" void runtime_sleep_stats(uint64_t* calls, uint64_t* ns);
extern "C" void runtime_wait_report(double frames);

namespace Vulkan {
extern std::atomic<u64> g_sky_compile_ns;
extern std::atomic<u32> g_sky_compiles;
extern std::atomic<u32> g_sky_module_compiles;
extern std::atomic<u64> g_sky_module_compile_ns;
extern std::atomic<u64> g_sky_compile_total_ns;
extern std::atomic<u32> g_sky_prefetch_started;
extern std::atomic<u32> g_sky_prefetch_adopted;
} // namespace Vulkan

namespace SkyVideoOut {

bool FrameStatsEnabled() {
    static const bool enabled = EmulatorSettingsImpl::Flag("SKY_RENDERER_FRAME_STATS", false);
    return enabled;
}

/// renderer: memory per statistics window: the kernel's count for the game (VRAM and GTT of its
/// DRM clients, RSS) and the parts we know of. GTT holds the game's direct memory (fixed).
static void PrintMemory() {
    u64 vram_kib = 0, gtt_kib = 0;
    std::vector<u64> clients;
    if (DIR* dir = opendir("/proc/self/fdinfo")) {
        while (const dirent* entry = readdir(dir)) {
            char path[64];
            std::snprintf(path, sizeof(path), "/proc/self/fdinfo/%s", entry->d_name);
            FILE* file = std::fopen(path, "r");
            if (!file) {
                continue;
            }
            char line[160];
            bool drm = false;
            unsigned long long client = 0, vram = 0, gtt = 0;
            while (std::fgets(line, sizeof(line), file)) {
                drm |= std::strncmp(line, "drm-driver:", 11) == 0;
                std::sscanf(line, "drm-client-id: %llu", &client);
                std::sscanf(line, "drm-memory-vram: %llu", &vram);
                std::sscanf(line, "drm-memory-gtt: %llu", &gtt);
            }
            std::fclose(file);
            // Duplicated descriptors share a client.
            if (drm && std::find(clients.begin(), clients.end(), client) == clients.end()) {
                clients.push_back(client);
                vram_kib += vram;
                gtt_kib += gtt;
            }
        }
        closedir(dir);
    }
    unsigned long long size_pages = 0, rss_pages = 0;
    if (FILE* statm = std::fopen("/proc/self/statm", "r")) {
        if (std::fscanf(statm, "%llu %llu", &size_pages, &rss_pages) != 2) {
            rss_pages = 0;
        }
        std::fclose(statm);
    }
    const u64 rss = u64(rss_pages) * u64(sysconf(_SC_PAGESIZE));
    const u64 device = SkyStats::device_alloc_bytes.load() - SkyStats::device_free_bytes.load();
    u64 vma_blocks = 0, vma_used = 0;
    Vulkan::VmaDeviceUsage(vma_blocks, vma_used);
    std::printf("Memory: VRAM %llu MiB, GTT %llu MiB, RSS %llu MiB; Vulkan memory %llu MiB "
                "allocated (VMA blocks %llu MiB, %llu MiB of them used); Vulkan images %llu MiB; "
                "cached images %llu MiB in %llu; guest blocks in VRAM %llu MiB allocated, "
                "%llu MiB of it unused (%llu MiB moved back idle, %llu MiB unmapped, %llu MiB freed; %llu chunks, %llu emptied, blocks kept: %llu GPU-written, %llu not direct memory); texture collector: usage %llu MiB, starts at %llu MiB, %llu images freed, %llu GPU-written kept\n",
                (unsigned long long)(vram_kib >> 10), (unsigned long long)(gtt_kib >> 10),
                (unsigned long long)(rss >> 20), (unsigned long long)(device >> 20),
                (unsigned long long)(vma_blocks >> 20), (unsigned long long)(vma_used >> 20),
                (unsigned long long)(SkyStats::vk_image_bytes.load() >> 20),
                (unsigned long long)(SkyStats::live_image_bytes.load() >> 20),
                (unsigned long long)SkyStats::live_images.load(),
                (unsigned long long)(SkyStats::residency_alloc_bytes.load() >> 20),
                (unsigned long long)(SkyStats::residency_unused_bytes.load() >> 20),
                (unsigned long long)(SkyStats::vram_idle_bytes.exchange(0) >> 20),
                (unsigned long long)(SkyStats::vram_unmapped_bytes.exchange(0) >> 20),
                (unsigned long long)(SkyStats::vram_chunks_freed_bytes.exchange(0) >> 20),
                (unsigned long long)SkyStats::residency_chunk_count.load(),
                (unsigned long long)SkyStats::evacuations.exchange(0),
                (unsigned long long)SkyStats::evac_kept_gpu.exchange(0),
                (unsigned long long)SkyStats::evac_kept_other.exchange(0),
                (unsigned long long)(SkyStats::gc_used_bytes.load() >> 20),
                (unsigned long long)(SkyStats::gc_trigger_bytes.load() >> 20),
                (unsigned long long)SkyStats::gc_freed_images.exchange(0),
                (unsigned long long)SkyStats::gc_kept_images.exchange(0));
}

void OnFlipStats() {
    using Clock = std::chrono::steady_clock;
    static Clock::time_point window_start = Clock::now(), last = window_start;
    static u32 frames;
    static double worst_ms;
    const auto now = Clock::now();
    const double frame_ms = std::chrono::duration<double, std::milli>(now - last).count();
    worst_ms = std::max(worst_ms, frame_ms);
    static std::vector<double> intervals;
    intervals.push_back(frame_ms);
    last = now;
    // Stall diagnostics: what happened during a long frame.
    static u64 last_gpu_ns, last_images, last_image_bytes, last_buffer_bytes;
    static u64 last_t[6], last_minflt, last_sigf, last_pc, last_pp, last_rc, last_rp;
    const u64 pc = SkyStats::protect_calls.load(), pp = SkyStats::protect_pages.load(),
              rc = SkyStats::protect_revoke_calls.load(), rp = SkyStats::protect_revoke_pages.load();
    const u64 minflt = SkyStats::gpu_minor_faults.load(), sigf = SkyStats::gpu_signal_faults.load();
    static u64 last_copy_cpu, last_copy_sys, last_copy_flt;
    const u64 copy_cpu = SkyStats::t_copy_cpu.load(), copy_sys = SkyStats::copy_sys_us.load(),
              copy_flt = SkyStats::copy_minflt.load();
    static u64 last_proc_flt, last_copy_ns, last_copy_bytes, last_rf, last_trf, last_twf;
    const u64 rf = SkyStats::read_faults.load(), trf = SkyStats::t_read_faults.load(),
              twf = SkyStats::t_write_faults.load();
    if (frame_ms > 40.0 && last_gpu_ns != 0) {
        std::printf("       fault handlers: %llu read faults %.1f ms, write faults %.1f ms\n",
                    static_cast<unsigned long long>(rf - last_rf), (trf - last_trf) / 1e6,
                    (twf - last_twf) / 1e6);
    }
    last_rf = rf;
    last_trf = trf;
    last_twf = twf;
    const u64 copy_ns = SkyStats::t_copy.load(), copy_bytes = SkyStats::copy_bytes.load();
    u64 proc_flt = 0;
    if (rusage usage{}; getrusage(RUSAGE_SELF, &usage) == 0) {
        proc_flt = usage.ru_minflt;
    }
    const u64 t_now[6] = {SkyStats::t_resident.load(), SkyStats::t_protect.load(),
                          SkyStats::t_image_create.load(), SkyStats::t_refresh.load(),
                          SkyStats::t_staging.load(), SkyStats::t_host_wait.load()};
    static u64 last_draws, last_dispatches, last_subs, last_sys, last_user, last_invol, last_vol;
    const u64 draws = SkyStats::draws.load(), dispatches = SkyStats::dispatches.load(),
              subs = SkyStats::submissions.load(), sys_us = SkyStats::gpu_sys_us.load(),
              user_us = SkyStats::gpu_user_us.load(), invol = SkyStats::gpu_invol_switches.load(),
              vol = SkyStats::gpu_vol_switches.load();
    u64 gpu_ns = 0;
    if (const int clock = SkyStats::gpu_thread_clock.load(); clock != -1) {
        timespec ts{};
        clock_gettime(static_cast<clockid_t>(clock), &ts);
        gpu_ns = u64(ts.tv_sec) * 1000000000ull + u64(ts.tv_nsec);
    }
    const u64 images = SkyStats::images_registered.load();
    const u64 image_bytes = SkyStats::image_upload_bytes.load();
    const u64 buffer_bytes = SkyStats::buffer_upload_bytes.load();
    if (frame_ms > 40.0 && last_gpu_ns != 0) {
        std::printf("Stall: %.1f ms frame; GPU thread on CPU %.1f ms; %llu images registered, "
                    "%.1f MB image uploads, %.1f MB buffer uploads\n",
                    frame_ms, (gpu_ns - last_gpu_ns) / 1e6,
                    static_cast<unsigned long long>(images - last_images),
                    (image_bytes - last_image_bytes) / 1e6,
                    (buffer_bytes - last_buffer_bytes) / 1e6);
        std::printf("       %llu draws, %llu dispatches, %llu submissions; GPU thread user %.1f ms, "
                    "kernel %.1f ms, %llu preempted, %llu waits\n",
                    static_cast<unsigned long long>(draws - last_draws),
                    static_cast<unsigned long long>(dispatches - last_dispatches),
                    static_cast<unsigned long long>(subs - last_subs), (user_us - last_user) / 1e3,
                    (sys_us - last_sys) / 1e3, static_cast<unsigned long long>(invol - last_invol),
                    static_cast<unsigned long long>(vol - last_vol));
    }
    if (frame_ms > 40.0 && last_gpu_ns != 0) {
        std::printf("       ms in: resident %.1f, protect %.1f, image create %.1f, "
                    "image refresh %.1f, staging %.1f, waiting for host copies %.1f\n",
                    (t_now[0] - last_t[0]) / 1e6, (t_now[1] - last_t[1]) / 1e6,
                    (t_now[2] - last_t[2]) / 1e6, (t_now[3] - last_t[3]) / 1e6,
                    (t_now[4] - last_t[4]) / 1e6, (t_now[5] - last_t[5]) / 1e6);
    }
    static std::array<u64, 12> last_layer{};
    static u64 last_mprotects = 0, last_entries = 0;
    std::array<u64, 12> layer_now{};
    for (size_t i = 0; i < layer_now.size(); ++i) {
        layer_now[i] = SkyStats::t_layer[i].load(std::memory_order_relaxed);
    }
    const u64 mprotects = SkyStats::layer_mprotects.load(std::memory_order_relaxed);
    const u64 entries = SkyStats::layer_entries_written.load(std::memory_order_relaxed);
    if (frame_ms > 40.0 && last_gpu_ns != 0 && layer_now != last_layer) {
        const auto ms = [&](size_t i) { return (layer_now[i] - last_layer[i]) / 1e6; };
        std::printf("       layer memory ms: traps set/cleared %.1f (%llu mprotect), "
                    "to VRAM %.1f, back in place %.1f, trap hits %.1f, yield %.1f, "
                    "volatile %.1f, republish %.1f (%llu entries: staging %.1f, guest view %.1f, "
                    "mirrors %.1f, copy %.1f), paged uploads %.1f\n",
                    ms(0), static_cast<unsigned long long>(mprotects - last_mprotects), ms(1),
                    ms(2), ms(3), ms(4), ms(5), ms(6),
                    static_cast<unsigned long long>(entries - last_entries), ms(8), ms(9),
                    ms(10), ms(11), ms(7));
    }
    last_layer = layer_now;
    last_mprotects = mprotects;
    last_entries = entries;
    if (frame_ms > 40.0 && last_gpu_ns != 0) {
        std::printf("       GPU thread page faults %llu (process %llu), protection faults %llu; "
                    "protect calls %llu (%llu pages), of which write-revoking %llu (%llu pages)\n",
                    static_cast<unsigned long long>(minflt - last_minflt),
                    static_cast<unsigned long long>(proc_flt - last_proc_flt),
                    static_cast<unsigned long long>(sigf - last_sigf),
                    static_cast<unsigned long long>(pc - last_pc),
                    static_cast<unsigned long long>(pp - last_pp),
                    static_cast<unsigned long long>(rc - last_rc),
                    static_cast<unsigned long long>(rp - last_rp));
    }
    last_pc = pc;
    last_pp = pp;
    last_rc = rc;
    last_rp = rp;
    last_minflt = minflt;
    if (frame_ms > 40.0 && last_gpu_ns != 0 && copy_ns > last_copy_ns) {
        std::printf("       guest copies %.1f MB in %.1f thread-ms, %.1f ms on CPU (kernel %.1f ms, "
                    "%llu page faults in large copies) (%.2f GB/s per thread)\n",
                    (copy_bytes - last_copy_bytes) / 1e6, (copy_ns - last_copy_ns) / 1e6,
                    (copy_cpu - last_copy_cpu) / 1e6, (copy_sys - last_copy_sys) / 1e3,
                    static_cast<unsigned long long>(copy_flt - last_copy_flt),
                    double(copy_bytes - last_copy_bytes) / double(copy_ns - last_copy_ns));
    }
    // renderer: SKY_RENDERER_FRAME_LOG=path (with SKY_RENDERER_FRAME_STATS): one line per flip, to find what the
    // long frames (stutter) have in common.
    static FILE* const frame_log = [] () -> FILE* {
        const char* path = std::getenv("SKY_RENDERER_FRAME_LOG");
        FILE* file = path && *path ? std::fopen(path, "w") : nullptr;
        if (file) {
            std::fprintf(file, "t_s,frame_ms,present_wait_ms,tick_wait_ms,stage_a_cpu_ms,"
                               "images,image_mb,buffer_mb,protect_ms,resident_ms,create_ms,"
                               "refresh_ms,write_fault_ms,read_faults,guest_copy_mb,draws,"
                               "dispatches,submissions,compiles,preupload_mb,kernel_ms,alloc_mb,"
                               "free_mb,monotonic_us,module_compiles,module_compile_ms,"
                               "compile_ms,prefetch_started,prefetch_adopted\n");
        }
        return file;
    }();
    if (frame_log) {
        static const auto log_start = now;
        static u64 log_twf, log_tick, log_present, log_compiles, log_rf, log_preupload;
        static u64 log_alloc, log_free;
        static u64 log_module_compiles, log_module_ns, log_compile_total_ns;
        static u64 log_prefetch_started, log_prefetch_adopted;
        const u64 tick = SkyStats::tick_wait_ns.load(), present = SkyStats::present_wait_ns.load();
        const u64 compiles_now = Vulkan::g_sky_compiles.load();
        // tick_wait_ns and the compile count are reset every stats window.
        const auto delta = [](u64 now_value, u64& last_value) {
            const u64 d = now_value >= last_value ? now_value - last_value : now_value;
            last_value = now_value;
            return d;
        };
        timespec stamp{};
        clock_gettime(CLOCK_MONOTONIC, &stamp);
        const auto monotonic_us = static_cast<unsigned long long>(stamp.tv_sec) * 1000000ull +
                                  static_cast<unsigned long long>(stamp.tv_nsec) / 1000ull;
        std::fprintf(frame_log,
                     "%.4f,%.2f,%.2f,%.2f,%.2f,%llu,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%llu,"
                     "%.2f,%llu,%llu,%llu,%llu,%.2f,%.2f,%.1f,%.1f,%llu,%llu,%.2f,%.2f,%llu,%llu\n",
                     std::chrono::duration<double>(now - log_start).count(), frame_ms,
                     delta(present, log_present) / 1e6, delta(tick, log_tick) / 1e6,
                     last_gpu_ns ? (gpu_ns - last_gpu_ns) / 1e6 : 0.0,
                     static_cast<unsigned long long>(images - last_images),
                     (image_bytes - last_image_bytes) / 1e6,
                     (buffer_bytes - last_buffer_bytes) / 1e6, (t_now[1] - last_t[1]) / 1e6,
                     (t_now[0] - last_t[0]) / 1e6, (t_now[2] - last_t[2]) / 1e6,
                     (t_now[3] - last_t[3]) / 1e6, delta(twf, log_twf) / 1e6,
                     static_cast<unsigned long long>(delta(rf, log_rf)),
                     (copy_bytes - last_copy_bytes) / 1e6,
                     static_cast<unsigned long long>(draws - last_draws),
                     static_cast<unsigned long long>(dispatches - last_dispatches),
                     static_cast<unsigned long long>(subs - last_subs),
                     static_cast<unsigned long long>(delta(compiles_now, log_compiles)),
                     delta(SkyStats::preupload_bytes.load(), log_preupload) / 1e6,
                     last_gpu_ns ? (sys_us - last_sys) / 1e3 : 0.0,
                     delta(SkyStats::device_alloc_bytes.load(), log_alloc) / 1e6,
                     delta(SkyStats::device_free_bytes.load(), log_free) / 1e6, monotonic_us,
                     static_cast<unsigned long long>(
                         delta(Vulkan::g_sky_module_compiles.load(), log_module_compiles)),
                     delta(Vulkan::g_sky_module_compile_ns.load(), log_module_ns) / 1e6,
                     delta(Vulkan::g_sky_compile_total_ns.load(), log_compile_total_ns) / 1e6,
                     static_cast<unsigned long long>(
                         delta(Vulkan::g_sky_prefetch_started.load(), log_prefetch_started)),
                     static_cast<unsigned long long>(
                         delta(Vulkan::g_sky_prefetch_adopted.load(), log_prefetch_adopted)));
        static u32 unflushed = 0;
        if (++unflushed >= 120) {
            std::fflush(frame_log);
            unflushed = 0;
        }
    }
    last_copy_ns = copy_ns;
    last_copy_cpu = copy_cpu;
    last_copy_sys = copy_sys;
    last_copy_flt = copy_flt;
    last_copy_bytes = copy_bytes;
    last_proc_flt = proc_flt;
    last_sigf = sigf;
    std::copy(std::begin(t_now), std::end(t_now), std::begin(last_t));
    last_draws = draws;
    last_dispatches = dispatches;
    last_subs = subs;
    last_sys = sys_us;
    last_user = user_us;
    last_invol = invol;
    last_vol = vol;
    last_gpu_ns = gpu_ns;
    last_images = images;
    last_image_bytes = image_bytes;
    last_buffer_bytes = buffer_bytes;
    ++frames;
    const double window = std::chrono::duration<double>(now - window_start).count();
    if (window >= 5.0) {
        const u32 compiles = Vulkan::g_sky_compiles.exchange(0);
        const u64 compile_ns = Vulkan::g_sky_compile_ns.exchange(0);
        const u64 direct = Vulkan::Scheduler::direct_recordings.exchange(0);
        const u64 faults = SkyStats::tracker_faults.exchange(0);
        // GPU command thread CPU time per draw: comparable between builds even when the scene
        // (and so the frame rate) differs a little.
        static u64 window_draws = 0, window_gpu_us = 0;
        const u64 all_draws = SkyStats::draws.load();
        const u64 gpu_us = SkyStats::gpu_user_us.load() + SkyStats::gpu_sys_us.load();
        const double us_per_draw = all_draws > window_draws
                                       ? double(gpu_us - window_gpu_us) / (all_draws - window_draws)
                                       : 0.0;
        const double draws_per_frame = frames ? double(all_draws - window_draws) / frames : 0.0;
        window_draws = all_draws;
        window_gpu_us = gpu_us;
        std::printf("Frame stats: %.1f FPS, worst frame %.1f ms (vblank %u Hz); "
                    "%u shader/pipeline compiles, %.1f ms; %llu recorder syncs; "
                    "%.0f write faults/s, %lld hot pages; GPU thread %.2f us/draw, "
                    "%.0f draws/frame, idle %.1f%%; blocked: recorder %.1f%%, host copies "
                    "%.1f%% (%.0f/frame, %.0f/frame not needed), copy threads %.1f%%, GPU ticks %.1f%%; "
                    "reduced-size draws %.0f/frame of %.0f in the scene\n",
                    frames / window, worst_ms, EmulatorSettings.GetVblankFrequency(), compiles,
                    compile_ns / 1e6, static_cast<unsigned long long>(direct),
                    faults / window, static_cast<long long>(SkyStats::hot_pages.load()),
                    us_per_draw, draws_per_frame,
                    SkyStats::gpu_idle_ns.exchange(0) / (window * 1e7),
                    SkyStats::sync_recording_ns.exchange(0) / (window * 1e7),
                    SkyStats::host_copies_wait_ns.exchange(0) / (window * 1e7),
                    frames ? double(SkyStats::host_copy_waits.exchange(0)) / frames : 0.0,
                    frames ? double(SkyStats::host_copy_waits_skipped.exchange(0)) / frames : 0.0,
                    SkyStats::copy_threads_wait_ns.exchange(0) / (window * 1e7),
                    SkyStats::tick_wait_ns.exchange(0) / (window * 1e7),
                    frames ? double(SkyStats::reduced_draws.exchange(0)) / frames : 0.0,
                    frames ? double(SkyStats::scene_draws.exchange(0)) / frames : 0.0);
        SkyMem::FaultSites::Report();
        if (const u64 notes = SkyStats::cpu_write_notes.exchange(0)) {
            std::printf("Write notices: %.0f/s, %.2f MB/s (libc copies over pages the GPU side "
                        "watches)\n",
                        notes / window, SkyStats::cpu_write_note_bytes.exchange(0) / (window * 1e6));
        }
        Vulkan::Breadcrumbs::PrintProgress();
        PrintMemory();
        if (const u64 in_place = SkyStats::bound_in_place_bytes.exchange(0)) {
            std::printf("Buffer bindings: %.1f MB/frame in place (%.1f GPU-written), %.1f MB/frame "
                        "VRAM copies\n",
                        in_place / (frames * 1e6),
                        SkyStats::bound_in_place_written_bytes.exchange(0) / (frames * 1e6),
                        SkyStats::bound_vram_bytes.exchange(0) / (frames * 1e6));
        }
        {
            const u64 updates = SkyStats::gpu_data_updates.exchange(0);
            const u64 copied_back = SkyStats::copied_back_blocks.exchange(0);
            const u64 readbacks = SkyStats::readbacks.exchange(0);
            const u64 late = SkyStats::late_vram_writes.exchange(0);
            if (updates + copied_back + readbacks + late != 0) {
                std::printf("GPU data in VRAM: %.1f command writes/s put into it, %.1f exact writes/s "
                            "(labels, CPU bytes beside GPU data), %.1f blocks/s copied back, "
                            "%.1f readbacks/s\n",
                            updates / window, late / window, copied_back / window,
                            readbacks / window);
            }
        }
        SkyKernel::ReportEqueueWaits(frames);
        runtime_wait_report(frames);
        for (std::size_t i = 0; i < SkyStats::range_allocators.size(); ++i) {
            if (const u64 a = SkyStats::range_allocators[i].load()) {
                std::printf("%s %#llx: %llu live, %.1f MB", i ? ";" : "GPU range allocators:",
                            (unsigned long long)a, (unsigned long long)SkyStats::range_live[i].load(),
                            SkyStats::range_bytes[i].load() / 1e6);
            }
        }
        if (SkyStats::range_allocators[0].load()) {
            std::printf("\n");
        }
        std::printf("Gnm: %.1f sceGnmSubmitDone/frame, %.1f sceGnmAreSubmitsAllowed/frame, %.1f refused/frame; "
                    "guest waited for the previous frame %.1fx %.2f ms/frame; %.1f compute queue submissions/frame\n",
                    SkyStats::submit_done_calls.exchange(0) / double(frames),
                    SkyStats::submits_allowed_queries.exchange(0) / double(frames),
                    SkyStats::submits_refused.exchange(0) / double(frames),
                    SkyStats::gnm_frame_waits.exchange(0) / double(frames),
                    SkyStats::gnm_frame_wait_ns.exchange(0) / (1e6 * double(frames)),
                    SkyStats::asc_submits.exchange(0) / double(frames));
        std::printf("EOP fences: %llu decoded, %llu labels written, %lld pending; %.1f labels/frame "
                    "written by the GPU\n",
                    (unsigned long long)SkyStats::eop_decoded.load(),
                    (unsigned long long)SkyStats::eop_written.load(),
                    (long long)(SkyStats::eop_decoded.load() - SkyStats::eop_written.load()),
                    SkyStats::gpu_labels.exchange(0) / double(frames));
        const u64 early = SkyStats::idle_flushes.exchange(0);
        const u64 draining = SkyStats::drain_flushes.exchange(0);
        if (early || draining) {
            std::printf("Honest labels: %.1f submissions/frame sent early (GPU idle), %.1f as the "
                        "GPU reached the last one\n",
                        early / double(frames), draining / double(frames));
        }
        {
            uint64_t sleeps = 0, sleep_ns = 0;
            runtime_sleep_stats(&sleeps, &sleep_ns);
            if (sleeps != 0 && frames != 0) {
                std::printf("Guest sleeps per frame: %.1f, %.2f ms\n", sleeps / double(frames),
                            sleep_ns / (frames * 1e6));
            }
        }
        if (const u64 copies = SkyStats::shadow_copies.exchange(0)) {
            std::printf("Shadow copies: %.0f/frame, %.1f MB/frame (in-place data the CPU writes, "
                        "copied into VRAM for reading)\n",
                        copies / double(frames), SkyStats::shadow_bytes.exchange(0) / (frames * 1e6));
        }
        if (const u64 allocs = SkyStats::gpu_range_allocs.exchange(0)) {
            std::printf("Guest GPU memory: %.0f ranges/s handed out, %.2f MB/s\n", allocs / window,
                        SkyStats::gpu_range_alloc_bytes.exchange(0) / (window * 1e6));
        }
        // renderer: parallel Vulkan recording (vk_scheduler.h): command buffer segments.
        if (const u64 submits = Vulkan::Scheduler::recorded_submissions.exchange(0)) {
            const u64 segments = Vulkan::Scheduler::recorded_segments.exchange(0);
            std::printf("Recording: %.1f submissions/frame, %.2f command buffers each\n",
                        frames ? double(submits) / frames : 0.0, double(segments) / submits);
        }
        SkyWaitTrace::Report(window);
        // Frame pacing: spread of the guest flip intervals (judder that the mean hides).
        if (intervals.size() > 2) {
            std::vector<double> sorted = intervals;
            std::sort(sorted.begin(), sorted.end());
            const double median = sorted[sorted.size() / 2];
            double sum = 0, sq = 0;
            u32 spikes = 0;
            for (const double ms : intervals) {
                sum += ms;
                sq += ms * ms;
                spikes += ms > 1.5 * median;
            }
            const double mean = sum / intervals.size();
            std::printf("Frame pacing: median %.2f ms, stddev %.2f ms, p99 %.2f ms, "
                        "%u frames over 1.5x median\n",
                        median, std::sqrt(std::max(0.0, sq / intervals.size() - mean * mean)),
                        sorted[std::min(sorted.size() - 1, sorted.size() * 99 / 100)], spikes);
        }
        intervals.clear();
        window_start = now;
        frames = 0;
        worst_ms = 0;
    }
}

} // namespace SkyVideoOut

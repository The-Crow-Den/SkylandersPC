// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Opt-in per-frame guest profile (SKY_FRAME_PROFILE=path). Writes one CSV row
// per guest flip: game-thread CPU time and time spent inside host services,
// keyed by CLOCK_MONOTONIC microseconds like the renderer's BB_FRAME_LOG.
// Disabled, every entry point is a single predictable branch.
#include <cstdint>

namespace FrameProfile {
enum class Bucket : unsigned { Gpu, Sync, Clock, File, Other, Count };
bool enabled() noexcept;
// Opens the CSV from SKY_FRAME_PROFILE; call once before guest threads start.
void configure();
// Each guest thread registers for CPU accounting for its lifetime.
void thread_started(bool main_thread);
void thread_finished();
std::uint64_t now_ns() noexcept;
void record(Bucket bucket, std::uint64_t nanoseconds) noexcept;
// Ends the current frame; called after a guest flip service returns.
void frame() noexcept;
}

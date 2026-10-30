// SPDX-License-Identifier: GPL-2.0-or-later
#include "render/display_pacer.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>

#include "common/thread.h"
#include "vulkan/swapchain.h"

// Host exports (native/pc_settings.hpp); absent outside the native host.
extern "C" long long sky_pc_frame_period_ns() __attribute__((weak));
extern "C" long long sky_pc_display_refresh_ns() __attribute__((weak));

namespace Vulkan {

namespace {

s64 Now() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

/// SKY_RENDERER_DISPLAY_PACING=0 presents frames as soon as they are rendered, as before.
bool PacingEnabled() {
    static const bool enabled = [] {
        const char* env = std::getenv("SKY_RENDERER_DISPLAY_PACING");
        return !env || env[0] != '0';
    }();
    return enabled;
}

} // namespace

DisplayPacer::DisplayPacer(const Swapchain& swapchain_) : swapchain{swapchain_} {
    // SKY_RENDERER_DISPLAY_LOG=<file>: one row per presented frame, with when it was shown.
    if (const char* path = std::getenv("SKY_RENDERER_DISPLAY_LOG"); path && *path) {
        log = std::fopen(path, "w");
        if (log) {
            std::fprintf(log, "present_id,ready_us,slot_us,issued_us,shown_us,shown_ms,refreshes,"
                              "expected_refreshes,on_slot\n");
        }
    }
    waiter = std::jthread([this](std::stop_token stop) { WaitThread(stop); });
}

DisplayPacer::~DisplayPacer() {
    waiter.request_stop();
    cv.notify_all();
    if (waiter.joinable()) {
        waiter.join();
    }
    if (log) {
        std::fclose(log);
    }
}

void DisplayPacer::BeforePresent() {
    const s64 period = sky_pc_frame_period_ns ? sky_pc_frame_period_ns() : 0;
    const s64 refresh = sky_pc_display_refresh_ns ? sky_pc_display_refresh_ns() : 0;
    const s64 ready = Now();
    current = {.ready_ns = ready, .slot_ns = ready, .issued_ns = ready, .period_ns = period,
               .refresh_ns = refresh, .on_slot = false};
    // Only low capped rates are paced: at 60 FPS on 240 Hz waiting for the slot cost ~11 ms of
    // latency and made shown intervals no steadier (measured), so such frames go out when ready.
    if (!PacingEnabled() || period < 25'000'000) {
        anchored = false;
        return;
    }
    s64 shift = 0;
    {
        std::scoped_lock lock{mutex};
        std::swap(shift, phase_shift_ns);
    }
    // A new grid when pacing starts, the cap changes or the guest fell a whole frame behind.
    if (!anchored || period != last_period_ns || ready > next_slot_ns + period) {
        anchored = true;
        last_period_ns = period;
        next_slot_ns = ready + period;
        slack_frames = 0;
        return;
    }
    s64 slot = next_slot_ns + shift;
    if (ready > slot) {
        slot = ready; // rendered late: shown as soon as possible, and the grid moves with it
    } else {
        std::this_thread::sleep_for(std::chrono::nanoseconds(slot - ready));
        current.on_slot = true;
    }
    current.slot_ns = slot;
    current.issued_ns = Now();
    next_slot_ns = slot + period;

    // Latency: if every frame of the last 2 seconds was ready more than a refresh before its slot,
    // move the grid earlier by whole refreshes (one shorter interval, once).
    const s64 slack = slot - ready;
    min_slack_ns = slack_frames == 0 ? slack : std::min(min_slack_ns, slack);
    if (++slack_frames >= u32(2'000'000'000 / period)) {
        const s64 margin = 1'000'000;
        if (refresh > 0 && min_slack_ns > refresh + margin) {
            next_slot_ns -= (min_slack_ns - margin) / refresh * refresh;
        }
        slack_frames = 0;
    }
}

void DisplayPacer::AfterPresent(u64 present_id) {
    if (present_id == 0 || (!log && !(PacingEnabled() && current.period_ns > 0))) {
        return;
    }
    {
        std::scoped_lock lock{mutex};
        current.id = present_id;
        if (pending.size() < 16) {
            pending.push_back(current);
        }
    }
    cv.notify_one();
}

s64 DisplayPacer::RepeatAt() const {
    static const bool repeat = [] {
        const char* env = std::getenv("SKY_RENDERER_PRESENT_REPEAT");
        return !env || env[0] != '0';
    }();
    if (!repeat || !current.on_slot) {
        return 0;
    }
    return current.slot_ns + current.period_ns / 2;
}

void DisplayPacer::WaitUntil(s64 when) {
    const s64 now = Now();
    if (when > now) {
        std::this_thread::sleep_for(std::chrono::nanoseconds(when - now));
    }
}

void DisplayPacer::WaitThread(std::stop_token stop) {
    Common::SetCurrentThreadName("sky:PresentWait");
    s64 previous_shown = 0;
    bool previous_on_slot = false;
    while (!stop.stop_requested()) {
        Pending item;
        {
            std::unique_lock lock{mutex};
            if (!cv.wait(lock, stop, [this] { return !pending.empty(); })) {
                return;
            }
            item = pending.front();
            pending.pop_front();
        }
        // Short waits: the swapchain may be recreated meanwhile (a retired id never completes).
        bool shown = false;
        for (int tries = 0; tries < 100 && !stop.stop_requested() && !shown; ++tries) {
            shown = swapchain.WaitPresented(item.id, 5'000'000);
        }
        if (!shown) {
            previous_shown = 0;
            continue;
        }
        const s64 now = Now();
        const s64 interval = previous_shown ? now - previous_shown : 0;
        const s64 refresh = item.refresh_ns;
        const s64 refreshes = refresh > 0 && interval ? (interval + refresh / 2) / refresh : 0;
        const s64 expected =
            refresh > 0 && item.period_ns > 0 ? (item.period_ns + refresh / 2) / refresh : 0;
        // Phase feedback (moving slots off a refresh boundary) needs present-wait to report scanout.
        // Under a compositor (windowed XWayland) it reports the compositor's receipt, ~2.5 ms after
        // the present whatever the refresh phase, so it is only enabled with
        // SKY_RENDERER_DISPLAY_PHASE=1 for testing.
        static const bool phase_feedback = [] {
            const char* env = std::getenv("SKY_RENDERER_DISPLAY_PHASE");
            return env && env[0] == '1';
        }();
        if (phase_feedback && expected && refreshes && refreshes != expected && item.on_slot &&
            previous_on_slot) {
            std::scoped_lock lock{mutex};
            phase_shift_ns += refresh / 3;
        }
        if (log) {
            std::fprintf(log, "%llu,%lld,%lld,%lld,%lld,%.3f,%lld,%lld,%d\n",
                         static_cast<unsigned long long>(item.id), item.ready_ns / 1000,
                         item.slot_ns / 1000, item.issued_ns / 1000, now / 1000, interval / 1e6,
                         refreshes, expected, item.on_slot ? 1 : 0);
        }
        previous_shown = now;
        previous_on_slot = item.on_slot;
    }
}

} // namespace Vulkan

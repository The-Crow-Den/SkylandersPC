// SPDX-License-Identifier: GPL-2.0-or-later
// renderer: present pacing for a guest capped at 40 FPS or less. The host paces the guest to a whole number of
// display refreshes (sky_pc_frame_period_ns); frames still finish rendering with some jitter, and
// presented as soon as ready, that jitter decides which refresh shows them: at 30 FPS on 240 Hz
// some frames were shown for 7 or 9 refreshes instead of 8. Frames are presented on a grid of
// that period instead, and VK_KHR_present_wait reports when each one reached the display: a
// frame presented on time but shown a refresh early or late moves the grid's phase off the
// refresh boundary it sat on.
#pragma once

#include <condition_variable>
#include <cstdio>
#include <deque>
#include <mutex>
#include <thread>

#include "common/types.h"

namespace Vulkan {

class Swapchain;

class DisplayPacer {
public:
    explicit DisplayPacer(const Swapchain& swapchain);
    ~DisplayPacer();
    DisplayPacer(const DisplayPacer&) = delete;
    DisplayPacer& operator=(const DisplayPacer&) = delete;

    /// Present thread: a rendered guest frame is about to be presented; waits for its slot.
    void BeforePresent();
    /// Present thread: the frame went out (its present id, 0 if it was skipped).
    void AfterPresent(u64 present_id);
    /// Present thread, after AfterPresent: when to show the same frame once more (0: not), half a
    /// period after its slot. Below ~40 FPS a variable-refresh display otherwise doubles frames
    /// itself (low framerate compensation) and a new frame arriving during a repeated scanout waits
    /// for it: shown intervals at 30 FPS spread over 28-39 ms. Repeated here, the display runs at
    /// twice the rate in its range and new frames still come every period. The presenter leaves the
    /// repeat out where presents cost much CPU (Presenter::RepeatAffordable).
    s64 RepeatAt() const;
    /// Present thread: waits until `when` (a time from RepeatAt).
    static void WaitUntil(s64 when);

private:
    struct Pending {
        u64 id;
        s64 ready_ns, slot_ns, issued_ns, period_ns, refresh_ns;
        bool on_slot; ///< presented at its slot (not late, not a new grid)
    };
    void WaitThread(std::stop_token stop);

    const Swapchain& swapchain;
    // Present thread only.
    bool anchored = false;
    s64 next_slot_ns = 0, last_period_ns = 0;
    s64 min_slack_ns = 0;
    u32 slack_frames = 0;
    Pending current{};
    // Shared with the wait thread.
    std::mutex mutex;
    std::condition_variable_any cv;
    std::deque<Pending> pending;
    s64 phase_shift_ns = 0; ///< requested by the wait thread after a missed refresh
    FILE* log = nullptr;
    std::jthread waiter;
};

} // namespace Vulkan

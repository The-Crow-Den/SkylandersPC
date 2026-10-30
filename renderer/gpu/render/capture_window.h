// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>

namespace Vulkan {
// A diagnostic interval in software flip counts, not a GPU/scanout frame boundary.
class CaptureWindow {
public:
    enum class Action { None, Begin, FinishFlips, FinishBudget };
    static constexpr unsigned MaxPolls = 8192;
    Action Advance(bool armed, std::uint64_t flips, unsigned desired) {
        if (desired < 1 || desired > 4) return Action::None;
        if (armed) {
            start = flips;
            polls = 0;
            running = true;
            return Action::Begin;
        }
        if (!running) return Action::None;
        if (flips >= start && flips - start >= desired) {
            running = false;
            return Action::FinishFlips;
        }
        if (++polls >= MaxPolls) {
            running = false;
            return Action::FinishBudget;
        }
        return Action::None;
    }
    std::uint64_t Start() const { return start; }
private:
    std::uint64_t start{};
    unsigned polls{};
    bool running{};
};
} // namespace Vulkan

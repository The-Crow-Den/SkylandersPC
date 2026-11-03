// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_clock.hpp"
#include <cerrno>
#include <ctime>
namespace SkyHost {
bool clock_time(Clock clock, ClockTime& output) noexcept {
    clockid_t id;
    switch (clock) {
    case Clock::Realtime: id = CLOCK_REALTIME; break;
    case Clock::Monotonic: id = CLOCK_MONOTONIC; break;
    case Clock::ThreadCpu: id = CLOCK_THREAD_CPUTIME_ID; break;
    case Clock::ProcessCpu: id = CLOCK_PROCESS_CPUTIME_ID; break;
    default: return false;
    }
    timespec now{};
    if (clock_gettime(id, &now)) return false;
    output = {static_cast<std::int64_t>(now.tv_sec), static_cast<std::int32_t>(now.tv_nsec)};
    return true;
}
bool timezone_minutes_west(std::int32_t& output, bool* dst_active) noexcept {
    const auto now = time(nullptr);
    tm local{};
    if (!localtime_r(&now, &local)) return false;
    output = static_cast<std::int32_t>(-local.tm_gmtoff / 60);
    if (dst_active) *dst_active = local.tm_isdst > 0;
    return true;
}
SleepResult sleep_microseconds(std::uint32_t duration, bool restart) noexcept {
    timespec wait{duration / 1000000, static_cast<long>(duration % 1000000) * 1000};
    while (nanosleep(&wait, &wait)) {
        if (errno != EINTR) return SleepResult::Failed;
        if (!restart) return SleepResult::Interrupted;
    }
    return SleepResult::Completed;
}
}

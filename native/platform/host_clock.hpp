// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
namespace SkyHost {
enum class Clock { Realtime, Monotonic, ThreadCpu, ProcessCpu };
struct ClockTime {
    std::int64_t seconds = 0;
    std::int32_t nanoseconds = 0;
};
// Realtime uses the Unix epoch; the other origins are host-defined. Output
// changes only on success, with nanoseconds in [0, 1000000000).
bool clock_time(Clock clock, ClockTime& output) noexcept;
// Current effective local offset, minutes west of UTC, including active DST.
// Optional daylight output reports whether the current offset includes DST.
// Neither output changes on failure.
bool timezone_minutes_west(std::int32_t& output, bool* dst_active = nullptr) noexcept;
enum class SleepResult { Completed, Interrupted, Failed };
// restart resumes the remaining POSIX duration after EINTR (calibration only).
// Windows waits on a high-resolution timer and does not synthesize POSIX signals.
SleepResult sleep_microseconds(std::uint32_t duration, bool restart = false) noexcept;
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_clock.hpp"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <timeapi.h>
#include <limits>
namespace SkyHost {
namespace {
// Guest timed waits (pthread condition/mutex timeouts, semaphore and event-flag
// waits) end in Windows waits with millisecond timeouts, which the system rounds
// to its timer tick: 15.6 ms by default. A guest "wait up to 1 ms" on the frame
// path could then take a whole 60 FPS frame. Request a 1 ms tick for the life
// of the process (per process on Windows 11), as games do. Linux needs nothing.
struct TimerResolution {
    bool raised = timeBeginPeriod(1) == TIMERR_NOERROR;
    ~TimerResolution() { if (raised) timeEndPeriod(1); }
};
const TimerResolution timer_resolution;
std::uint64_t ticks(const FILETIME& value) noexcept {
    return (static_cast<std::uint64_t>(value.dwHighDateTime) << 32) | value.dwLowDateTime;
}
ClockTime from_ticks(std::uint64_t value) noexcept {
    // FILETIME and CPU-accounting units are 100 ns. The quotient always fits
    // int64 even when all 64 input bits are set.
    return {static_cast<std::int64_t>(value / 10000000), static_cast<std::int32_t>((value % 10000000) * 100)};
}
}
bool clock_time(Clock clock, ClockTime& output) noexcept {
    ClockTime result{};
    switch (clock) {
    case Clock::Realtime: {
        FILETIME now{};
        GetSystemTimePreciseAsFileTime(&now);
        result = from_ticks(ticks(now));
        result.seconds -= 11644473600LL; // 1601-01-01 to Unix epoch.
        break;
    }
    case Clock::Monotonic: {
        LARGE_INTEGER count{}, frequency{};
        if (!QueryPerformanceCounter(&count) || !QueryPerformanceFrequency(&frequency) ||
            count.QuadPart < 0 || frequency.QuadPart <= 0) return false;
        result.seconds = count.QuadPart / frequency.QuadPart;
        const auto remainder = static_cast<std::uint64_t>(count.QuadPart % frequency.QuadPart);
        result.nanoseconds = static_cast<std::int32_t>(
            (static_cast<unsigned __int128>(remainder) * 1000000000) / static_cast<std::uint64_t>(frequency.QuadPart));
        break;
    }
    case Clock::ThreadCpu: case Clock::ProcessCpu: {
        FILETIME created{}, exited{}, kernel{}, user{};
        const auto success = clock == Clock::ThreadCpu
            ? GetThreadTimes(GetCurrentThread(), &created, &exited, &kernel, &user)
            : GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user);
        if (!success) return false;
        const auto kernel_ticks = ticks(kernel), user_ticks = ticks(user);
        if (kernel_ticks > std::numeric_limits<std::uint64_t>::max() - user_ticks) return false;
        result = from_ticks(kernel_ticks + user_ticks);
        break;
    }
    default: return false;
    }
    output = result;
    return true;
}
bool timezone_minutes_west(std::int32_t& output, bool* dst_active) noexcept {
    DYNAMIC_TIME_ZONE_INFORMATION zone{};
    const auto state = GetDynamicTimeZoneInformation(&zone);
    if (state == TIME_ZONE_ID_INVALID) return false;
    std::int64_t bias = zone.Bias;
    if (state == TIME_ZONE_ID_DAYLIGHT) bias += zone.DaylightBias;
    else if (state == TIME_ZONE_ID_STANDARD) bias += zone.StandardBias;
    if (bias < std::numeric_limits<std::int32_t>::min() || bias > std::numeric_limits<std::int32_t>::max()) return false;
    output = static_cast<std::int32_t>(bias);
    if (dst_active) *dst_active = state == TIME_ZONE_ID_DAYLIGHT;
    return true;
}
SleepResult sleep_microseconds(std::uint32_t duration, bool restart) noexcept {
    (void)restart; // No POSIX signal interruption exists on this host.
    if (!duration) { Sleep(0); return SleepResult::Completed; }
    // Windows 10 1803+ high-resolution timers. Refuse unavailable timers;
    // do not replace guest microsecond sleeps with millisecond rounding.
    HANDLE timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                         TIMER_MODIFY_STATE | SYNCHRONIZE);
    if (!timer) return SleepResult::Failed;
    LARGE_INTEGER due{};
    due.QuadPart = -static_cast<LONGLONG>(duration) * 10;
    const bool armed = SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE) != 0;
    const auto wait = armed ? WaitForSingleObject(timer, INFINITE) : WAIT_FAILED;
    const bool closed = CloseHandle(timer) != 0;
    return armed && wait == WAIT_OBJECT_0 && closed ? SleepResult::Completed : SleepResult::Failed;
}
}

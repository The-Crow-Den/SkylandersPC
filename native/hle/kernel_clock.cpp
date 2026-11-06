// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_clock.hpp"
#include <array>
#include <cpuid.h>
#include <stdexcept>
#include "../platform/host_clock.hpp"
#include <x86intrin.h>
#include "../thread_context.hpp"

namespace {
using U = std::uint64_t;
U monotonic() {
    SkyHost::ClockTime now{};
    if (!SkyHost::clock_time(SkyHost::Clock::Monotonic, now)) throw std::runtime_error("cannot read monotonic clock");
    return static_cast<U>(now.seconds) * 1000000000 + static_cast<U>(now.nanoseconds);
}
U tsc() { _mm_lfence(); const auto value = __rdtsc(); _mm_lfence(); return value; }
constexpr std::array<std::string_view, 7> names{
    "1j3S3n-tTW4#libkernel#libkernel", "-2IRUCO--PM#libkernel#libkernel",
    "4J2sUJmuHZQ#libkernel#libkernel", "QBi7HCK03hw#libkernel#libkernel",
    "1jfXLRVzisc#libkernel#libkernel", "kOcnerypnQA#libkernel#libkernel",
    "ejekcaNQNq0#libkernel#libkernel"};
}
KernelClock::KernelClock() : started_(monotonic()) {}
bool KernelClock::supports(std::string_view identity) noexcept {
    if (identity == "n88vx3C5nW8#libScePosix#libkernel" || identity == "n88vx3C5nW8#libkernel#libkernel") return true;
    if (identity == "lLMT9vJAck0#libkernel#libkernel" || identity == "lLMT9vJAck0#libScePosix#libkernel") return true;
    for (auto name : names) if (identity == name) return true;
    return false;
}
U KernelClock::call(std::string_view identity, const U* a) {
    if (identity == "n88vx3C5nW8#libScePosix#libkernel" || identity == "n88vx3C5nW8#libkernel#libkernel") {
        auto status = a[0] ? call(names[6], a) : 0;
        if (!status && a[1]) {
            const std::array<U, 6> zone_arguments{a[1]};
            status = call(names[5], zone_arguments.data());
        }
        if (!status) return 0;
        if (auto* context = GuestThreadContext::current()) *context->error_pointer() = static_cast<std::int32_t>(status & 0xffff);
        return ~U{0};
    }
    if (identity == names[5]) {
        if (!a[0]) return 0x80020016;
        std::int32_t west = 0;
        if (!SkyHost::timezone_minutes_west(west)) throw std::runtime_error("cannot read guest timezone");
        auto* out = reinterpret_cast<std::int32_t*>(a[0]);
        out[0] = west; out[1] = 0;
        return 0;
    }
    if (identity == names[6]) {
        if (!a[0]) return 0x80020016;
        SkyHost::ClockTime now{};
        if (!SkyHost::clock_time(SkyHost::Clock::Realtime, now)) throw std::runtime_error("cannot read wall clock");
        auto* out = reinterpret_cast<std::int64_t*>(a[0]);
        out[0] = now.seconds; out[1] = now.nanoseconds / 1000;
        return 0;
    }
    if (identity == "lLMT9vJAck0#libkernel#libkernel" || identity == "lLMT9vJAck0#libScePosix#libkernel") {
        const auto status = call(names[3], a);
        if (!status) return 0;
        if (auto* context = GuestThreadContext::current()) *context->error_pointer() = static_cast<std::int32_t>(status & 0xffff);
        return ~U{0};
    }
    if (identity == names[0]) {
        std::lock_guard lock(lock_);
        if (!tsc_frequency_) {
            unsigned denominator = 0, numerator = 0, crystal = 0, unused = 0;
            if (__get_cpuid(0x15, &denominator, &numerator, &crystal, &unused) && denominator && numerator && crystal)
                tsc_frequency_ = static_cast<U>(crystal) * numerator / denominator;
            else {
                const auto before = monotonic(), first = tsc();
                if (SkyHost::sleep_microseconds(20000, true) != SkyHost::SleepResult::Completed)
                    throw std::runtime_error("TSC calibration sleep failed");
                const auto last = tsc(), after = monotonic();
                tsc_frequency_ = static_cast<U>(static_cast<long double>(last - first) * 1000000000 / (after - before));
            }
            if (!tsc_frequency_) throw std::runtime_error("cannot determine TSC frequency");
        }
        return tsc_frequency_;
    }
    if (identity == names[1]) return tsc();
    if (identity == names[2]) return (monotonic() - started_) / 1000;
    if (identity == names[3]) {
        if (!a[1]) return 0x80020016;
        SkyHost::Clock clock;
        switch (a[0]) {
            case 0: case 9: case 10: case 13: clock = SkyHost::Clock::Realtime; break;
            case 4: case 5: case 7: case 8: case 11: case 12: clock = SkyHost::Clock::Monotonic; break;
            case 14: clock = SkyHost::Clock::ThreadCpu; break;
            case 15: clock = SkyHost::Clock::ProcessCpu; break;
            default: return 0x80020016;
        }
        SkyHost::ClockTime now{};
        if (!SkyHost::clock_time(clock, now)) throw std::runtime_error("guest clock read failed");
        if (a[0] == 13) now.nanoseconds = 0;
        auto* out = reinterpret_cast<std::int64_t*>(a[1]);
        out[0] = now.seconds; out[1] = now.nanoseconds;
        return 0;
    }
    if (identity == names[4]) {
        const auto usec = static_cast<std::uint32_t>(a[0]);
        switch (SkyHost::sleep_microseconds(usec)) {
        case SkyHost::SleepResult::Completed: return 0;
        case SkyHost::SleepResult::Interrupted: return 0x80020004;
        case SkyHost::SleepResult::Failed: throw std::runtime_error("guest sleep failed");
        }
    }
    throw std::runtime_error("unsupported clock import");
}

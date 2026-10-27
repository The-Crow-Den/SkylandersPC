// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_clock.hpp"
#include <array>
#include <cerrno>
#include <cpuid.h>
#include <stdexcept>
#include <time.h>
#include <x86intrin.h>
#include "../thread_context.hpp"

namespace {
using U = std::uint64_t;
U monotonic() {
    timespec now{};
    if (clock_gettime(CLOCK_MONOTONIC, &now)) throw std::runtime_error("cannot read monotonic clock");
    return static_cast<U>(now.tv_sec) * 1000000000 + static_cast<U>(now.tv_nsec);
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
        const auto now = time(nullptr);
        tm local{};
        if (!localtime_r(&now, &local)) throw std::runtime_error("cannot read guest timezone");
        auto* out = reinterpret_cast<std::int32_t*>(a[0]);
        out[0] = static_cast<std::int32_t>(-local.tm_gmtoff / 60); out[1] = 0;
        return 0;
    }
    if (identity == names[6]) {
        if (!a[0]) return 0x80020016;
        timespec now{};
        if (clock_gettime(CLOCK_REALTIME, &now)) throw std::runtime_error("cannot read wall clock");
        auto* out = reinterpret_cast<std::int64_t*>(a[0]);
        out[0] = now.tv_sec; out[1] = now.tv_nsec / 1000;
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
                timespec wait{0, 20000000};
                while (nanosleep(&wait, &wait)) if (errno != EINTR) throw std::runtime_error("TSC calibration sleep failed");
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
        clockid_t clock;
        switch (a[0]) {
            case 0: case 9: case 10: case 13: clock = CLOCK_REALTIME; break;
            case 4: case 5: case 7: case 8: case 11: case 12: clock = CLOCK_MONOTONIC; break;
            case 14: clock = CLOCK_THREAD_CPUTIME_ID; break;
            case 15: clock = CLOCK_PROCESS_CPUTIME_ID; break;
            default: return 0x80020016;
        }
        timespec now{};
        if (clock_gettime(clock, &now)) throw std::runtime_error("guest clock read failed");
        if (a[0] == 13) now.tv_nsec = 0;
        auto* out = reinterpret_cast<std::int64_t*>(a[1]);
        out[0] = now.tv_sec; out[1] = now.tv_nsec;
        return 0;
    }
    if (identity == names[4]) {
        const auto usec = static_cast<std::uint32_t>(a[0]);
        timespec wait{usec / 1000000, static_cast<long>(usec % 1000000) * 1000};
        if (!nanosleep(&wait, nullptr)) return 0;
        if (errno == EINTR) return 0x80020004;
        throw std::runtime_error("guest sleep failed");
    }
    throw std::runtime_error("unsupported clock import");
}

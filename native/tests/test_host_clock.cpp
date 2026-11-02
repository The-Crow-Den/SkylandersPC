// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/host_clock.hpp"
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <stdexcept>
#include <thread>
#ifndef _WIN32
#include <csignal>
#include <sys/time.h>
#endif
namespace {
void require(bool value) { if (!value) throw std::runtime_error("host clock assertion failed"); }
std::int64_t ns(const SkyHost::ClockTime& time) {
    require(time.nanoseconds >= 0 && time.nanoseconds < 1000000000);
    return time.seconds * 1000000000 + time.nanoseconds;
}
SkyHost::ClockTime read(SkyHost::Clock id) {
    SkyHost::ClockTime result{};
    require(SkyHost::clock_time(id, result));
    (void)ns(result);
    return result;
}
#ifndef _WIN32
volatile sig_atomic_t interrupted = 0;
void interrupt(int) { interrupted = 1; }
void arm_interrupt() {
    interrupted = 0;
    itimerval timer{};
    timer.it_value.tv_usec = 10000;
    require(setitimer(ITIMER_REAL, &timer, nullptr) == 0);
}
#endif
}
int main() {
    using namespace SkyHost;
    ClockTime unchanged{123,456};
    require(!clock_time(static_cast<Clock>(99), unchanged));
    require(unchanged.seconds == 123 && unchanged.nanoseconds == 456);
    const auto wall_before = std::chrono::system_clock::now();
    const auto wall = read(Clock::Realtime);
    const auto wall_after = std::chrono::system_clock::now();
    const auto system_ns = [](auto time) {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(time.time_since_epoch()).count();
    };
    // A small tolerance accommodates the standard library clock's resolution.
    require(ns(wall) >= system_ns(wall_before) - 1000000 && ns(wall) <= system_ns(wall_after) + 1000000);
    std::int32_t west = 0;
    require(timezone_minutes_west(west) && west >= -1440 && west <= 1440);
    const auto before = read(Clock::Monotonic);
    const auto cpu_before = read(Clock::ThreadCpu), process_before = read(Clock::ProcessCpu);
    require(sleep_microseconds(0) == SleepResult::Completed);
    require(sleep_microseconds(20000) == SleepResult::Completed);
    require(ns(read(Clock::Monotonic)) - ns(before) >= 20000000);
    require(ns(read(Clock::ThreadCpu)) >= ns(cpu_before));
    require(ns(read(Clock::ProcessCpu)) >= ns(process_before));
    std::atomic<unsigned> failures = 0;
    std::array<std::thread,4> workers;
    for (auto& worker : workers) worker = std::thread([&] {
        const auto start = read(Clock::ThreadCpu);
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        // Demand a real advancing CPU clock, without requiring a performance
        // threshold or pretending its accounting resolution is nanoseconds.
        while (ns(read(Clock::ThreadCpu)) == ns(start)) {
            std::atomic_signal_fence(std::memory_order_seq_cst);
            if (std::chrono::steady_clock::now() >= deadline) { ++failures; return; }
        }
        if (sleep_microseconds(1000,true) != SleepResult::Completed) ++failures;
    });
    for (auto& worker : workers) worker.join();
    require(failures == 0 && ns(read(Clock::ProcessCpu)) > ns(process_before));
#ifndef _WIN32
    // Real signal interruption and remaining-duration restart, not an injected
    // fake nanosleep result. This test process has no other signal consumers.
    struct sigaction action{}, previous{};
    action.sa_handler = &interrupt;
    sigemptyset(&action.sa_mask);
    require(sigaction(SIGALRM, &action, &previous) == 0);
    arm_interrupt();
    require(sleep_microseconds(200000) == SleepResult::Interrupted && interrupted);
    const auto restart_begin = read(Clock::Monotonic);
    arm_interrupt();
    require(sleep_microseconds(20000,true) == SleepResult::Completed && interrupted);
    require(ns(read(Clock::Monotonic)) - ns(restart_begin) >= 20000000);
    require(sigaction(SIGALRM, &previous, nullptr) == 0);
#endif
}

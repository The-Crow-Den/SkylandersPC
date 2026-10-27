// SPDX-License-Identifier: GPL-3.0-or-later
#include "frame_profile.hpp"
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <pthread.h>
#include <time.h>
#include <vector>

namespace {
using U = std::uint64_t;
constexpr auto kBuckets = static_cast<std::size_t>(FrameProfile::Bucket::Count);
bool active = false;
FILE* output = nullptr;
// Service time summed over all guest threads, and over the main thread only.
std::array<std::atomic<U>, kBuckets> all_ns{}, main_ns{};
std::atomic<U> calls{0};
thread_local bool is_main = false;

struct Clock { clockid_t id; bool main; };
std::mutex threads_lock; // Guards the live table, retired totals and the writer.
std::vector<std::pair<pthread_t, Clock>> live;
U retired_worker_ns = 0, retired_main_ns = 0;

U read_clock(clockid_t id) {
    timespec value{};
    if (clock_gettime(id, &value)) return 0;
    return static_cast<U>(value.tv_sec) * 1000000000ull + static_cast<U>(value.tv_nsec);
}
struct Previous {
    U stamp_ns = 0, main_cpu = 0, worker_cpu = 0, calls = 0;
    std::array<U, kBuckets> all{}, main{};
} previous;
}

namespace FrameProfile {
bool enabled() noexcept { return active; }
U now_ns() noexcept { return read_clock(CLOCK_MONOTONIC); }
void configure() {
    const char* path = std::getenv("SKY_FRAME_PROFILE");
    if (!path || !*path) return;
    output = std::fopen(path, "w");
    if (!output) { std::fprintf(stderr, "frame profile: cannot open %s\n", path); return; }
    std::fprintf(output, "monotonic_us,frame_ms,main_cpu_ms,worker_cpu_ms,guest_threads,service_calls,"
        "main_gpu_ms,main_sync_ms,main_clock_ms,main_file_ms,main_other_ms,"
        "all_gpu_ms,all_sync_ms,all_clock_ms,all_file_ms,all_other_ms\n");
    previous.stamp_ns = now_ns();
    active = true;
    std::fprintf(stderr, "{\"event\":\"frame-profile\",\"enabled\":true}\n");
}
void thread_started(bool main_thread) {
    if (!active) return;
    is_main = main_thread;
    clockid_t id{};
    if (pthread_getcpuclockid(pthread_self(), &id)) return;
    std::lock_guard lock(threads_lock);
    live.emplace_back(pthread_self(), Clock{id, main_thread});
}
void thread_finished() {
    if (!active) return;
    std::lock_guard lock(threads_lock);
    for (auto it = live.begin(); it != live.end(); ++it) {
        if (!pthread_equal(it->first, pthread_self())) continue;
        (it->second.main ? retired_main_ns : retired_worker_ns) += read_clock(it->second.id);
        live.erase(it);
        return;
    }
}
void record(Bucket bucket, U nanoseconds) noexcept {
    const auto index = static_cast<std::size_t>(bucket);
    all_ns[index].fetch_add(nanoseconds, std::memory_order_relaxed);
    if (is_main) main_ns[index].fetch_add(nanoseconds, std::memory_order_relaxed);
    calls.fetch_add(1, std::memory_order_relaxed);
}
void frame() noexcept {
    if (!active) return;
    std::lock_guard lock(threads_lock);
    const U stamp = now_ns();
    U main_cpu = retired_main_ns, worker_cpu = retired_worker_ns;
    for (const auto& [thread, clock] : live) (clock.main ? main_cpu : worker_cpu) += read_clock(clock.id);
    std::array<U, kBuckets> all{}, main{};
    for (std::size_t i = 0; i < kBuckets; ++i) {
        all[i] = all_ns[i].load(std::memory_order_relaxed);
        main[i] = main_ns[i].load(std::memory_order_relaxed);
    }
    const U total_calls = calls.load(std::memory_order_relaxed);
    const auto ms = [](U now, U before) { return now >= before ? static_cast<double>(now - before) / 1e6 : 0.0; };
    std::fprintf(output, "%llu,%.3f,%.3f,%.3f,%zu,%llu", static_cast<unsigned long long>(stamp / 1000),
        ms(stamp, previous.stamp_ns), ms(main_cpu, previous.main_cpu), ms(worker_cpu, previous.worker_cpu),
        live.size(), static_cast<unsigned long long>(total_calls - previous.calls));
    for (std::size_t i = 0; i < kBuckets; ++i) std::fprintf(output, ",%.3f", ms(main[i], previous.main[i]));
    for (std::size_t i = 0; i < kBuckets; ++i) std::fprintf(output, ",%.3f", ms(all[i], previous.all[i]));
    std::fputc('\n', output);
    static unsigned unflushed = 0;
    if (++unflushed >= 60) { std::fflush(output); unflushed = 0; }
    previous = {stamp, main_cpu, worker_cpu, total_calls, all, main};
}
}

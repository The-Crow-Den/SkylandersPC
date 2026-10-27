// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_semaphore.hpp"
#include "../thread_context.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <condition_variable>
#include <list>
#include <map>
#include <mutex>
#include <stdexcept>

namespace {
using U = std::uint64_t;
constexpr std::array<std::string_view, 7> posix_nids{
    "pDuPEf3m4fI", "cDW233RAwWo", "YCV5dGGBcCo", "WBWzsRifCEA", "IKP8typ0QUk", "Bq+LRV-N6Hk", "w5IHyvahg-o"};
std::size_t posix_operation(std::string_view identity) {
    const auto split = identity.find('#');
    if (split == identity.npos) return posix_nids.size();
    const auto scope = identity.substr(split);
    if (scope != "#libScePosix#libkernel" && scope != "#libkernel#libkernel") return posix_nids.size();
    return std::find(posix_nids.begin(), posix_nids.end(), identity.substr(0, split)) - posix_nids.begin();
}
U posix_error(int error) {
    if (auto* context = GuestThreadContext::current()) *context->error_pointer() = error;
    return static_cast<U>(-1);
}
constexpr std::array<std::string_view, 6> names{
    "188x57JYp0g#libkernel#libkernel", "Zxa0VhQVTsk#libkernel#libkernel",
    "4czppHBiriw#libkernel#libkernel", "12wOHk8ywb0#libkernel#libkernel",
    "4DM06U2BNEY#libkernel#libkernel", "R1Jvn8bSCW8#libkernel#libkernel"};
struct Waiter { std::int32_t need; int priority; bool done = false; U result = 0; };
struct Semaphore {
    std::int32_t count, initial, maximum;
    bool priority_order;
    std::condition_variable event;
    std::list<Waiter*> waiters;
    void wake(U error) {
        for (auto* waiter : waiters) { waiter->done = true; waiter->result = error; }
        waiters.clear(); event.notify_all();
    }
};
}
struct KernelSemaphore::Impl {
    std::mutex lock;
    std::map<std::uint32_t, std::shared_ptr<Semaphore>> semaphores;
    std::map<U, std::shared_ptr<Semaphore>> posix_semaphores;
    U next_posix = 0x53504f5300000001;
    std::uint32_t next = 1;
};
KernelSemaphore::KernelSemaphore() : impl_(std::make_unique<Impl>()) {}
KernelSemaphore::~KernelSemaphore() = default;
bool KernelSemaphore::supports(std::string_view identity) noexcept {
    return posix_operation(identity) != posix_nids.size() || std::find(names.begin(), names.end(), identity) != names.end();
}
U KernelSemaphore::call(std::string_view identity, const U* a, int caller_priority) {
    const auto posix = posix_operation(identity);
    if (posix != posix_nids.size()) {
        std::unique_lock lock(impl_->lock);
        if (!a[0]) return posix_error(22);
        auto* handle = reinterpret_cast<U*>(a[0]);
        if (posix == 0) {
            // Only process-local semaphores are supported. Guest sem_t is an
            // opaque pointer-sized token; never expose the host sem_t layout.
            if (a[1]) return posix_error(78); // ENOSYS, process-shared unavailable.
            if (static_cast<std::uint32_t>(a[2]) > 0x7fffffff) return posix_error(22);
            auto sem = std::make_shared<Semaphore>();
            sem->count = sem->initial = static_cast<std::uint32_t>(a[2]);
            sem->maximum = 0x7fffffff; sem->priority_order = false;
            const auto token = impl_->next_posix++;
            impl_->posix_semaphores.emplace(token, std::move(sem));
            *handle = token;
            return 0;
        }
        const auto found = impl_->posix_semaphores.find(*handle);
        if (found == impl_->posix_semaphores.end()) return posix_error(22);
        auto sem = found->second;
        if (posix == 1) {
            if (!sem->waiters.empty()) return posix_error(16);
            impl_->posix_semaphores.erase(found); *handle = 0; return 0;
        }
        if (posix == 5) {
            if (!a[1]) return posix_error(22);
            *reinterpret_cast<std::int32_t*>(a[1]) = sem->count; return 0;
        }
        if (posix == 4) {
            if (sem->count == sem->maximum) return posix_error(84); // EOVERFLOW.
            if (sem->waiters.empty()) ++sem->count;
            else {
                auto* waiter = sem->waiters.front(); sem->waiters.pop_front();
                waiter->done = true; sem->event.notify_all();
            }
            return 0;
        }
        if (sem->count > 0) { --sem->count; return 0; }
        if (posix == 3) return posix_error(35); // EAGAIN.
        Waiter waiter{1, caller_priority};
        std::chrono::system_clock::time_point deadline;
        if (posix == 6) {
            if (!a[1]) return posix_error(22);
            const auto* time = reinterpret_cast<const std::int64_t*>(a[1]);
            if (time[0] < 0 || time[1] < 0 || time[1] >= 1000000000) return posix_error(22);
            // Avoid overflow converting the guest's int64 seconds to host ns.
            constexpr auto maximum = std::chrono::nanoseconds::max().count();
            if (time[0] > (maximum - time[1]) / 1000000000)
                deadline = std::chrono::system_clock::time_point::max();
            else deadline = std::chrono::system_clock::time_point(std::chrono::nanoseconds(time[0] * 1000000000 + time[1]));
        }
        sem->waiters.push_back(&waiter);
        if (posix == 6) {
            if (!sem->event.wait_until(lock, deadline, [&] { return waiter.done; })) {
                sem->waiters.remove(&waiter);
                return posix_error(60); // ETIMEDOUT; never leave a stale waiter.
            }
        } else sem->event.wait(lock, [&] { return waiter.done; });
        return 0;
    }
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    if (operation == static_cast<std::ptrdiff_t>(names.size())) throw std::runtime_error("unsupported semaphore import");
    std::unique_lock lock(impl_->lock);
    if (operation == 0) {
        const auto initial = static_cast<std::int32_t>(a[3]), maximum = static_cast<std::int32_t>(a[4]);
        if (!a[0] || !a[1] || a[2] > 2 || initial < 0 || maximum <= 0 || initial > maximum) return 0x80020016;
        if (a[5]) throw std::runtime_error("semaphore options are unsupported");
        const auto id = impl_->next++;
        auto sem = std::make_shared<Semaphore>();
        sem->count = sem->initial = initial; sem->maximum = maximum;
        sem->priority_order = a[2] == 2;
        impl_->semaphores.emplace(id, std::move(sem));
        *reinterpret_cast<std::uint32_t*>(a[0]) = id;
        return 0;
    }
    auto found = impl_->semaphores.find(static_cast<std::uint32_t>(a[0]));
    if (found == impl_->semaphores.end()) return 0x80020003;
    auto sem = found->second;
    const auto count = static_cast<std::int32_t>(a[1]);
    if (operation == 1 || operation == 3) {
        if (count <= 0 || count > sem->maximum) return 0x80020016;
        if (sem->waiters.empty() && sem->count >= count) { sem->count -= count; return 0; }
        if (operation == 3) return 0x80020010;
        auto* timeout = reinterpret_cast<std::uint32_t*>(a[2]);
        if (timeout && !*timeout) return 0x8002003c;
        Waiter waiter{count, caller_priority};
        auto position = sem->waiters.end();
        if (sem->priority_order) position = std::find_if(sem->waiters.begin(), sem->waiters.end(),
            [&](const auto* queued) { return queued->priority > caller_priority; });
        sem->waiters.insert(position, &waiter);
        if (timeout) {
            const auto end = std::chrono::steady_clock::now() + std::chrono::microseconds(*timeout);
            if (!sem->event.wait_until(lock, end, [&] { return waiter.done; })) {
                sem->waiters.remove(&waiter);
                waiter.result = 0x8002003c;
            }
            const auto remaining = std::chrono::duration_cast<std::chrono::microseconds>(end - std::chrono::steady_clock::now()).count();
            *timeout = static_cast<std::uint32_t>(std::max<std::int64_t>(0, remaining));
        } else sem->event.wait(lock, [&] { return waiter.done; });
        return waiter.result;
    }
    if (operation == 2) {
        if (count <= 0 || count > sem->maximum - sem->count) return 0x80020016;
        sem->count += count;
        while (!sem->waiters.empty() && sem->waiters.front()->need <= sem->count) {
            auto* waiter = sem->waiters.front(); sem->waiters.pop_front();
            sem->count -= waiter->need; waiter->done = true;
        }
        sem->event.notify_all();
        return 0;
    }
    if (operation == 4) {
        if (count > sem->maximum) return 0x80020016;
        if (a[2]) *reinterpret_cast<std::int32_t*>(a[2]) = static_cast<std::int32_t>(sem->waiters.size());
        sem->count = count < 0 ? sem->initial : count;
        sem->wake(0x80020055);
        return 0;
    }
    sem->wake(0x8002000d);
    impl_->semaphores.erase(found);
    return 0;
}

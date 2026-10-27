// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_event.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <list>
#include <map>
#include <mutex>
#include <stdexcept>

namespace {
using U = std::uint64_t;
constexpr std::array<std::string_view, 7> names{
    "BpFoboUJoZU#libkernel#libkernel", "8mql9OcQnd4#libkernel#libkernel",
    "IOnSvHzqu6A#libkernel#libkernel", "7uhBFWRAS60#libkernel#libkernel",
    "JTvBflhYazQ#libkernel#libkernel", "9lvj5DjHZiA#libkernel#libkernel",
    "PZku4ZrXJqg#libkernel#libkernel"};
struct Waiter { U bits, mode; int priority; bool done = false; U result = 0, pattern = 0; };
struct Event {
    U bits;
    bool multiple, priority;
    std::condition_variable changed;
    std::list<Waiter*> waiters;
    bool acquire(Waiter& waiter) {
        const auto present = bits & waiter.bits;
        if ((waiter.mode & 3) == 1 ? present != waiter.bits : !present) return false;
        waiter.pattern = bits; waiter.done = true;
        if (waiter.mode & 0x10) bits = 0;
        if (waiter.mode & 0x20) bits &= ~waiter.bits;
        return true;
    }
    void wake(U error) {
        for (auto* waiter : waiters) { waiter->result = error; waiter->pattern = bits; waiter->done = true; }
        waiters.clear(); changed.notify_all();
    }
};
}
struct KernelEvent::Impl {
    std::mutex lock;
    U next = 0x55000000;
    std::map<U, std::shared_ptr<Event>> events;
};
KernelEvent::KernelEvent() : impl_(std::make_unique<Impl>()) {}
KernelEvent::~KernelEvent() = default;
bool KernelEvent::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
U KernelEvent::call(std::string_view identity, const U* a, int priority) {
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    if (operation == static_cast<std::ptrdiff_t>(names.size())) throw std::runtime_error("unsupported event flag import");
    std::unique_lock lock(impl_->lock);
    if (operation == 0) {
        if (!a[0] || !a[1] || (a[2] & ~0x33ull) || (a[2] & 3) == 3 || (a[2] & 0x30) == 0x30 || a[4]) return 0x80020016;
        if (strnlen(reinterpret_cast<const char*>(a[1]), 32) == 32) return 0x8002003f;
        auto event = std::make_shared<Event>();
        event->bits = a[3]; event->multiple = a[2] & 0x20; event->priority = (a[2] & 3) == 2;
        const auto id = impl_->next++; impl_->events.emplace(id, event);
        *reinterpret_cast<U*>(a[0]) = id;
        return 0;
    }
    auto found = impl_->events.find(a[0]);
    if (found == impl_->events.end()) return 0x80020003;
    auto event = found->second;
    if (operation == 1) { event->wake(0x8002000d); impl_->events.erase(found); return 0; }
    if (operation == 2) {
        event->bits |= a[1];
        for (auto it = event->waiters.begin(); it != event->waiters.end();) {
            if (event->acquire(**it)) it = event->waiters.erase(it); else ++it;
        }
        event->changed.notify_all(); return 0;
    }
    if (operation == 3) { event->bits &= a[1]; return 0; }
    if (operation == 6) {
        if (a[2]) *reinterpret_cast<int*>(a[2]) = static_cast<int>(event->waiters.size());
        event->bits = a[1]; event->wake(0x80020055); return 0;
    }
    if (!a[1] || (a[2] & ~0x33ull) || (a[2] & 3) == 0 || (a[2] & 3) == 3 || (a[2] & 0x30) == 0x30) return 0x80020016;
    if (!event->multiple && !event->waiters.empty()) return 0x80020001;
    Waiter waiter{a[1], a[2], priority};
    if (!event->acquire(waiter)) {
        auto* timeout = operation == 4 ? reinterpret_cast<std::uint32_t*>(a[4]) : nullptr;
        if (operation == 5 || (timeout && !*timeout)) {
            if (a[3]) *reinterpret_cast<U*>(a[3]) = event->bits;
            return operation == 5 ? 0x80020010 : 0x8002003c;
        }
        auto position = event->waiters.end();
        if (event->priority) position = std::find_if(event->waiters.begin(), event->waiters.end(),
            [&](auto* queued) { return queued->priority > priority; });
        event->waiters.insert(position, &waiter);
        if (timeout) {
            const auto end = std::chrono::steady_clock::now() + std::chrono::microseconds(*timeout);
            if (!event->changed.wait_until(lock, end, [&] { return waiter.done; })) {
                event->waiters.remove(&waiter); waiter.result = 0x8002003c; waiter.pattern = event->bits;
            }
            const auto left = std::chrono::duration_cast<std::chrono::microseconds>(end - std::chrono::steady_clock::now()).count();
            *timeout = static_cast<std::uint32_t>(std::max<std::int64_t>(left, 0));
        } else event->changed.wait(lock, [&] { return waiter.done; });
    }
    if (a[3]) *reinterpret_cast<U*>(a[3]) = waiter.pattern;
    return waiter.result;
}

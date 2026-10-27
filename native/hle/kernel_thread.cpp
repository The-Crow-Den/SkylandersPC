// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_thread.hpp"
#include "../guest_start.hpp"
#include "../frame_profile.hpp"
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unistd.h>

namespace {
using U = std::uint64_t;
bool posix_getschedparam(std::string_view identity) {
    return identity == "P41kTWUS3EI#libkernel#libkernel" ||
           identity == "P41kTWUS3EI#libScePosix#libkernel";
}
bool posix_setschedparam(std::string_view identity) {
    return identity == "oIRFTjoILbg#libkernel#libkernel" ||
           identity == "oIRFTjoILbg#libScePosix#libkernel" ||
           identity == "Xs9hdiD7sAA#libkernel#libkernel" ||
           identity == "Xs9hdiD7sAA#libScePosix#libkernel";
}
constexpr std::array<std::string_view, 26> names{
    "nsYoNRywwNg#libkernel#libkernel", "62KCwEMmzcM#libkernel#libkernel",
    "x1X76arYMxU#libkernel#libkernel", "8+s5BzZjxSg#libkernel#libkernel",
    "UTXzJbWhhTE#libkernel#libkernel", "-Wreprtu0Qs#libkernel#libkernel",
    "4+h9EzwKF4I#libkernel#libkernel", "DzES9hQF4f4#libkernel#libkernel",
    "3qxgM4ezETA#libkernel#libkernel", "eXbUSpEaTsA#libkernel#libkernel",
    "JaRMy+QcpeU#libkernel#libkernel", "-fA+7ZlGDQs#libkernel#libkernel",
    "FXPWHNk8Of0#libkernel#libkernel", "El+cQ20DynU#libkernel#libkernel",
    "6UgtwV+0zb4#libkernel#libkernel", "onNY9Byn-W8#libkernel#libkernel",
    "4qGrR6eoP9Y#libkernel#libkernel", "T72hz6ffq08#libkernel#libkernel",
    "1tKyG7RlMJo#libkernel#libkernel", "W0Hpm2X0uPE#libkernel#libkernel",
    "bt3CTBKmGyI#libkernel#libkernel", "rcrVFJsQWRY#libkernel#libkernel",
    "GBUY7ywdULE#libkernel#libkernel", "3PtV6p3QNX4#libkernel#libkernel",
    "aI+OeCz8xrQ#libkernel#libkernel", "3kg7rT0NQIs#libkernel#libkernel"};
struct Attributes {
    U stack = 1024 * 1024, guard = 4096, affinity = 0x7f;
    int detached = 0, policy = 1, priority = 700, inherit = 4;
};
struct Thread {
    Attributes attr;
    std::unique_ptr<GuestThreadContext> owned_context;
    std::thread host;
    std::string name;
    U result = 0;
    bool joining = false, detached = false, finished = false;
};
}
struct KernelThread::Impl {
    mutable std::mutex lock;
    SkyBootPlan boot;
    std::function<void(GuestThreadContext&)> finalizer;
    U next_attr = 0x54000000;
    std::map<U, Attributes> attributes;
    std::map<U, std::shared_ptr<Thread>> threads;
    ~Impl() { for (auto& [id, thread] : threads) if (thread->host.joinable()) thread->host.join(); }
    // Caller holds lock. The record's context is freed with the last
    // shared_ptr, after its guest entry has returned.
    void release(const std::shared_ptr<Thread>& record) {
        if (record->host.joinable()) record->host.detach();
        for (auto it = threads.begin(); it != threads.end(); ++it)
            if (it->second == record) { threads.erase(it); break; }
    }
};
KernelThread::KernelThread() : impl_(std::make_unique<Impl>()) {}
KernelThread::~KernelThread() = default;
void KernelThread::configure(const SkyBootPlan& boot, std::function<void(GuestThreadContext&)> finalizer) {
    impl_->boot = boot; impl_->finalizer = std::move(finalizer);
}
void KernelThread::attach_main(GuestThreadContext& context) {
    auto record = std::make_shared<Thread>();
    record->name = "main"; record->attr.stack = 8 * 1024 * 1024;
    impl_->threads.emplace(context.handle(), std::move(record));
}
bool KernelThread::supports(std::string_view identity) noexcept {
    return posix_getschedparam(identity) || posix_setschedparam(identity) || std::find(names.begin(), names.end(), identity) != names.end();
}
int KernelThread::current_priority() const {
    auto* context = GuestThreadContext::current();
    if (!context) return 700;
    std::lock_guard lock(impl_->lock);
    const auto thread = impl_->threads.find(context->handle());
    return thread == impl_->threads.end() ? 700 : thread->second->attr.priority;
}
U KernelThread::call(std::string_view identity, const U* a) {
    if (posix_setschedparam(identity)) {
        if (!a[0] || !a[2]) return 22;
        // The current virtual scheduler supports the default FIFO policy.
        if (a[1] != 1) return 45; // ENOTSUP, do not claim another policy.
        const auto priority = *reinterpret_cast<const std::int32_t*>(a[2]);
        if (priority < 256 || priority > 767) return 22;
        std::lock_guard lock(impl_->lock);
        const auto found = impl_->threads.find(a[0]);
        if (found == impl_->threads.end() || found->second->finished) return 3;
        found->second->attr.policy = 1;
        found->second->attr.priority = priority;
        return 0;
    }
    if (posix_getschedparam(identity)) {
        if (!a[1] || !a[2]) return 22;
        std::lock_guard lock(impl_->lock);
        const auto found = impl_->threads.find(a[0]);
        if (found == impl_->threads.end() || found->second->finished) return 3;
        // Guest policy and sched_param.sched_priority are each int32.
        // These describe virtual guest scheduling, not Linux scheduling.
        *reinterpret_cast<std::int32_t*>(a[1]) = found->second->attr.policy;
        *reinterpret_cast<std::int32_t*>(a[2]) = found->second->attr.priority;
        return 0;
    }
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    if (operation == static_cast<std::ptrdiff_t>(names.size())) throw std::runtime_error("unsupported thread import");
    if (operation == 25) sky_guest_thread_exit(a[0]);
    if (operation == 24) return GuestThreadContext::current()->handle();
    if (operation == 23) return a[0] == a[1];
    if (operation == 17) { std::this_thread::yield(); return 0; }
    std::unique_lock lock(impl_->lock);
    if (operation == 0) {
        if (!a[0]) return 0x80020016;
        const auto id = impl_->next_attr++;
        impl_->attributes.emplace(id, Attributes{});
        *reinterpret_cast<U*>(a[0]) = id;
        return 0;
    }
    if (operation < 14) {
        if (!a[0]) return 0x80020016;
        auto* slot = reinterpret_cast<U*>(a[0]);
        if (operation == 2) {
            auto thread = impl_->threads.find(a[0]);
            if (thread == impl_->threads.end() || !a[1]) return 0x80020016;
            slot = reinterpret_cast<U*>(a[1]);
            auto attr = impl_->attributes.find(*slot);
            if (attr == impl_->attributes.end()) return 0x80020016;
            attr->second = thread->second->attr;
            return 0;
        }
        auto attr = impl_->attributes.find(*slot);
        if (attr == impl_->attributes.end()) return 0x80020016;
        auto& value = attr->second;
        switch (operation) {
        case 1: impl_->attributes.erase(attr); *slot = 0; return 0;
        case 3: if (!a[1]) return 0x80020016; *reinterpret_cast<U*>(a[1]) = value.affinity; return 0;
        case 4: if (a[1] < 16384 || a[1] > 64 * 1024 * 1024) return 0x80020016; value.stack = a[1]; return 0;
        case 5: if (a[1] > 1) return 0x80020016; value.detached = static_cast<int>(a[1]); return 0;
        case 6: if (a[1] < 1 || a[1] > 3) return 0x80020016; value.policy = static_cast<int>(a[1]); return 0;
        case 7: if (!a[1]) return 0x80020016; value.priority = *reinterpret_cast<const int*>(a[1]); return 0;
        case 8: if (!a[1] || (a[1] & ~0x7full)) return 0x80020016; value.affinity = a[1]; return 0;
        case 9: if (a[1] != 0 && a[1] != 4) return 0x80020016; value.inherit = static_cast<int>(a[1]); return 0;
        case 10: if (!a[1]) return 0x80020016; *reinterpret_cast<int*>(a[1]) = value.detached; return 0;
        case 11: if (!a[1]) return 0x80020016; *reinterpret_cast<U*>(a[1]) = value.stack; return 0;
        case 12: if (!a[1]) return 0x80020016; *reinterpret_cast<int*>(a[1]) = value.priority; return 0;
        case 13: if (a[1] > 1024 * 1024) return 0x80020016; value.guard = a[1]; return 0;
        default: throw std::runtime_error("invalid thread attribute operation");
        }
    }
    if (operation == 14) {
        if (!a[0] || !a[2]) return 0x80020016;
        auto record = std::make_shared<Thread>();
        if (a[1]) {
            auto attr = impl_->attributes.find(*reinterpret_cast<const U*>(a[1]));
            if (attr == impl_->attributes.end()) return 0x80020016;
            record->attr = attr->second;
        }
        if (record->attr.inherit == 4 && GuestThreadContext::current()) {
            auto parent = impl_->threads.find(GuestThreadContext::current()->handle());
            if (parent != impl_->threads.end()) {
                record->attr.priority = parent->second->attr.priority;
                record->attr.policy = parent->second->attr.policy;
            }
        }
        record->owned_context = std::make_unique<GuestThreadContext>(impl_->boot, record->attr.stack, record->attr.guard);
        const auto id = record->owned_context->handle();
        record->name = a[4] ? std::string(reinterpret_cast<const char*>(a[4]), strnlen(reinterpret_cast<const char*>(a[4]), 31)) : "guest";
        record->detached = record->attr.detached != 0;
        impl_->threads.emplace(id, record);
        *reinterpret_cast<U*>(a[0]) = id;
        const auto entry = a[2], argument = a[3];
        try {
            record->host = std::thread([this, record, entry, argument] {
                try {
                    FrameProfile::thread_started(false);
                    const auto result = record->owned_context->run(entry, reinterpret_cast<const void*>(argument));
                    FrameProfile::thread_finished();
                    if (impl_->finalizer) impl_->finalizer(*record->owned_context);
                    std::lock_guard guard(impl_->lock);
                    record->result = result; record->finished = true;
                    // Nobody may join a detached thread: release its record,
                    // stack and TLS now instead of at process teardown.
                    if (record->detached) impl_->release(record);
                } catch (const std::exception& e) {
                    dprintf(STDERR_FILENO, "guest thread failed: %s\n", e.what()); _exit(74);
                }
            });
        } catch (const std::system_error&) { impl_->threads.erase(id); return 0x80020023; }
        return 0;
    }
    auto found = impl_->threads.find(a[0]);
    if (found == impl_->threads.end()) return 0x80020003;
    auto record = found->second;
    if (operation == 15) {
        if (!record->host.joinable() || record->detached || record->joining) return 0x80020016;
        if (GuestThreadContext::current() && GuestThreadContext::current()->handle() == a[0]) return 0x8002000b;
        record->joining = true;
        lock.unlock(); record->host.join(); lock.lock();
        if (a[1]) *reinterpret_cast<U*>(a[1]) = record->result;
        impl_->threads.erase(a[0]);
        return 0;
    }
    if (operation == 16) {
        if (record->detached || record->joining) return 0x80020016;
        record->detached = true;
        // A running thread releases itself when it finishes.
        if (record->finished) impl_->release(record);
        return 0;
    }
    if (operation == 18) { if (!a[1]) return 0x80020016; *reinterpret_cast<int*>(a[1]) = record->attr.priority; return 0; }
    if (operation == 19) { record->attr.priority = static_cast<int>(a[1]); return 0; }
    if (operation == 20) { if (!a[1] || (a[1] & ~0x7full)) return 0x80020016; record->attr.affinity = a[1]; return 0; }
    if (operation == 21) { if (!a[1]) return 0x80020016; *reinterpret_cast<U*>(a[1]) = record->attr.affinity; return 0; }
    if (operation == 22) { if (!a[1]) return 0x80020016; record->name = reinterpret_cast<const char*>(a[1]); return 0; }
    throw std::runtime_error("unimplemented thread operation");
}

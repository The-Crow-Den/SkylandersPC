// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <memory>

namespace SkyHost {
std::size_t thread_page_size() noexcept;

// Zeroed, private RW storage for guest stacks, thread blocks and data. Low placement
// retains the existing below-2-GiB guest-thread policy. This is an anywhere
// allocation within that range, not a fixed-address mapping request.
class ThreadMemory {
public:
    ThreadMemory() = default;
    ~ThreadMemory();
    ThreadMemory(const ThreadMemory&) = delete;
    ThreadMemory& operator=(const ThreadMemory&) = delete;
    bool allocate(std::size_t size, bool low = true) noexcept;
    // Exact page-aligned subrange, no rounding. Guards stay permanently
    // inaccessible until this allocation is released; these are not one-shot
    // Windows PAGE_GUARD pages.
    bool protect_none(std::size_t offset, std::size_t size) noexcept;
    bool protect_readonly(std::size_t offset, std::size_t size) noexcept;
    void* data() const noexcept { return data_; }
    std::size_t size() const noexcept { return size_; }
private:
    void* data_ = nullptr;
    std::size_t size_ = 0;
};

enum class FaultStackMode { AlternateSignalStack, NativeExceptionStack };
// Fault-stack lifecycle for a single context, one host thread at a time.
// POSIX installs/restores a private sigaltstack. Windows VEH runs on the
// interrupted stack; no alternate stack is claimed or emulated. Exhaustion of
// a Windows guest stack is fatal, not a recoverable fault-stack operation.
class ThreadFaultContext {
public:
    ThreadFaultContext();
    ~ThreadFaultContext();
    ThreadFaultContext(const ThreadFaultContext&) = delete;
    ThreadFaultContext& operator=(const ThreadFaultContext&) = delete;
    FaultStackMode mode() const noexcept;
    bool enter() noexcept;
    bool leave() noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}

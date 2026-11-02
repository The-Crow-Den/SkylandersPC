// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_thread.hpp"
#include <csignal>
#include <cstdlib>
#include <pthread.h>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>

namespace SkyHost {
std::size_t thread_page_size() noexcept {
    const auto size = sysconf(_SC_PAGESIZE);
    return size > 0 ? static_cast<std::size_t>(size) : 0;
}
ThreadMemory::~ThreadMemory() { if (data_) munmap(data_, size_); }
bool ThreadMemory::allocate(std::size_t size, bool low) noexcept {
    if (data_ || !size) return false;
    void* data = mmap(nullptr, size, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS | (low ? MAP_32BIT : 0), -1, 0);
    if (data == MAP_FAILED) return false;
    data_ = data;
    size_ = size;
    return true;
}
bool ThreadMemory::protect_none(std::size_t offset, std::size_t size) noexcept {
    const auto page = thread_page_size();
    if (!data_ || !page || !size || offset > size_ || size > size_ - offset || offset % page || size % page)
        return false;
    return mprotect(static_cast<unsigned char*>(data_) + offset, size, PROT_NONE) == 0;
}
bool ThreadMemory::protect_readonly(std::size_t offset, std::size_t size) noexcept {
    const auto page = thread_page_size();
    if (!data_ || !page || !size || offset > size_ || size > size_ - offset || offset % page || size % page)
        return false;
    return mprotect(static_cast<unsigned char*>(data_) + offset, size, PROT_READ) == 0;
}
struct ThreadFaultContext::Impl {
    ThreadMemory memory;
    stack_t previous{};
    pthread_t owner{};
    bool active = false;
    Impl() {
        if (!memory.allocate(128 * 1024, false)) throw std::runtime_error("cannot allocate thread signal stack");
    }
};
ThreadFaultContext::ThreadFaultContext() : impl_(std::make_unique<Impl>()) {}
ThreadFaultContext::~ThreadFaultContext() { if (impl_->active && !leave()) std::abort(); }
FaultStackMode ThreadFaultContext::mode() const noexcept { return FaultStackMode::AlternateSignalStack; }
bool ThreadFaultContext::enter() noexcept {
    if (impl_->active) return false;
    stack_t stack{};
    stack.ss_sp = impl_->memory.data();
    stack.ss_size = impl_->memory.size();
    if (sigaltstack(&stack, &impl_->previous)) return false;
    impl_->owner = pthread_self();
    impl_->active = true;
    return true;
}
bool ThreadFaultContext::leave() noexcept {
    if (!impl_->active || !pthread_equal(impl_->owner, pthread_self())) return false;
    if (sigaltstack(&impl_->previous, nullptr)) return false;
    impl_->active = false;
    return true;
}
}

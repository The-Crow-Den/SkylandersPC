// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_thread.hpp"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <algorithm>
#include <cstdlib>
#include <cstdint>
#include <limits>
#include <string>

namespace SkyHost {
bool set_current_thread_name(const char* name) noexcept {
    if (!name) return false;
    const auto size = MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,name,-1,nullptr,0);
    if (!size) return false;
    try {
        std::wstring wide(static_cast<std::size_t>(size),L'\0');
        if (MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,name,-1,wide.data(),size) != size) return false;
        return SUCCEEDED(SetThreadDescription(GetCurrentThread(),wide.c_str()));
    } catch (...) { return false; }
}
std::size_t thread_page_size() noexcept {
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    return info.dwPageSize;
}
ThreadMemory::~ThreadMemory() { if (data_) VirtualFree(data_, 0, MEM_RELEASE); }
bool ThreadMemory::allocate(std::size_t size, bool low) noexcept {
    return allocate_impl(size, low, false);
}
bool ThreadMemory::allocate_inaccessible(std::size_t size, bool low) noexcept {
    return allocate_impl(size, low, true);
}
bool ThreadMemory::allocate_impl(std::size_t size, bool low, bool inaccessible) noexcept {
    if (data_ || !size) return false;
    const auto allocate_at = [&](std::uintptr_t address) {
        void* data = VirtualAlloc(reinterpret_cast<void*>(address), size, MEM_RESERVE | MEM_COMMIT,
                                  inaccessible ? PAGE_NOACCESS : PAGE_READWRITE);
        if (!data) return false;
        if (address && reinterpret_cast<std::uintptr_t>(data) != address) {
            VirtualFree(data, 0, MEM_RELEASE);
            return false;
        }
        data_ = data;
        size_ = size;
        return true;
    };
    if (!low) return allocate_at(0);
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    const std::uintptr_t granularity = info.dwAllocationGranularity;
    constexpr std::uintptr_t limit = 0x80000000;
    if (granularity != 65536 || size >= limit) return false;
    const auto reserved = (size + granularity - 1) & ~(granularity - 1);
    auto address = granularity;
    while (address < limit && reserved <= limit - address) {
        MEMORY_BASIC_INFORMATION region{};
        if (!VirtualQuery(reinterpret_cast<void*>(address), &region, sizeof(region))) return false;
        const auto begin = reinterpret_cast<std::uintptr_t>(region.BaseAddress);
        if (region.RegionSize > std::numeric_limits<std::uintptr_t>::max() - begin) return false;
        const auto end = std::min(begin + region.RegionSize, limit);
        if (end <= address) return false;
        if (region.State == MEM_FREE && reserved <= end - address) {
            if (allocate_at(address)) return true;
            // A racing reservation may have taken this candidate. Re-query
            // the next exact 64-KiB candidate; never accept a moved address.
            address += granularity;
        } else {
            if (end > limit - (granularity - 1)) return false;
            address = (end + granularity - 1) & ~(granularity - 1);
        }
    }
    return false;
}
bool ThreadMemory::protect_none(std::size_t offset, std::size_t size) noexcept {
    const auto page = thread_page_size();
    if (!data_ || !page || !size || offset > size_ || size > size_ - offset || offset % page || size % page)
        return false;
    DWORD previous = 0;
    return VirtualProtect(static_cast<unsigned char*>(data_) + offset, size, PAGE_NOACCESS, &previous) != 0;
}
bool ThreadMemory::protect_readonly(std::size_t offset, std::size_t size) noexcept {
    const auto page = thread_page_size();
    if (!data_ || !page || !size || offset > size_ || size > size_ - offset || offset % page || size % page)
        return false;
    DWORD previous = 0;
    return VirtualProtect(static_cast<unsigned char*>(data_) + offset, size, PAGE_READONLY, &previous) != 0;
}
struct ThreadFaultContext::Impl {
    DWORD owner = 0;
    bool active = false;
};
ThreadFaultContext::ThreadFaultContext() : impl_(std::make_unique<Impl>()) {}
ThreadFaultContext::~ThreadFaultContext() { if (impl_->active && !leave()) std::abort(); }
FaultStackMode ThreadFaultContext::mode() const noexcept { return FaultStackMode::NativeExceptionStack; }
bool ThreadFaultContext::enter() noexcept {
    if (impl_->active) return false;
    // VEH uses the current stack. This only owns the entry lifecycle; it does
    // not install a POSIX signal stack or promise stack-exhaustion recovery.
    impl_->owner = GetCurrentThreadId();
    impl_->active = true;
    return true;
}
bool ThreadFaultContext::leave() noexcept {
    if (!impl_->active || impl_->owner != GetCurrentThreadId()) return false;
    impl_->active = false;
    impl_->owner = 0;
    return true;
}
}

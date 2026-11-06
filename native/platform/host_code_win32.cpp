// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_code.hpp"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <limits>

namespace SkyHost {
CodeMemory::~CodeMemory() { if (data_) VirtualFree(data_, 0, MEM_RELEASE); }
bool CodeMemory::allocate(std::size_t size, std::uint64_t near_address) noexcept {
    if (data_ || !size || size > 0x40000000) return false;
    auto allocate_at = [&](std::uint64_t address) {
        void* memory = VirtualAlloc(reinterpret_cast<void*>(address), size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (!memory) return false;
        if (address && reinterpret_cast<std::uintptr_t>(memory) != address) {
            VirtualFree(memory, 0, MEM_RELEASE); return false;
        }
        data_ = static_cast<std::uint8_t*>(memory); size_ = size; return true;
    };
    if (!near_address) return allocate_at(0);
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    const std::uint64_t step = info.dwAllocationGranularity;
    if (step != 65536) return false;
    const auto base = near_address & ~(step - 1);
    const auto reach = 0x7fff0000ULL - size;
    for (std::uint64_t distance = step; distance < reach; distance += step) {
        if (base <= std::numeric_limits<std::uint64_t>::max() - distance - size && allocate_at(base + distance)) return true;
        if (base > distance && allocate_at(base - distance)) return true;
    }
    return false;
}
bool CodeMemory::seal() noexcept {
    if (!data_ || sealed_) return false;
    DWORD previous = 0;
    if (!VirtualProtect(data_, size_, PAGE_EXECUTE_READ, &previous)) return false;
    sealed_ = true;
    return FlushInstructionCache(GetCurrentProcess(), data_, size_) != 0;
}
}

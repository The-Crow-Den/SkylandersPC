// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_code.hpp"
#include <sys/mman.h>
#include <limits>

namespace SkyHost {
CodeMemory::~CodeMemory() { if (data_) munmap(data_, size_); }
bool CodeMemory::allocate(std::size_t size, std::uint64_t near_address) noexcept {
    if (data_ || !size || size > 0x40000000) return false;
    auto allocate_at = [&](std::uint64_t address, bool fixed) {
        void* memory = mmap(reinterpret_cast<void*>(address), size, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS | (fixed ? MAP_FIXED_NOREPLACE : 0), -1, 0);
        if (memory == MAP_FAILED) return false;
        if (fixed && reinterpret_cast<std::uintptr_t>(memory) != address) {
            munmap(memory, size); return false;
        }
        data_ = static_cast<std::uint8_t*>(memory); size_ = size; return true;
    };
    if (!near_address) return allocate_at(0, false);
    const auto base = near_address & ~std::uint64_t{65535};
    // Bound the whole allocation, not just its first byte, within jump reach.
    const auto reach = 0x7fff0000ULL - size;
    for (std::uint64_t distance = 65536; distance < reach; distance += 65536) {
        if (base <= std::numeric_limits<std::uint64_t>::max() - distance - size && allocate_at(base + distance, true)) return true;
        if (base > distance && allocate_at(base - distance, true)) return true;
    }
    return false;
}
bool CodeMemory::seal() noexcept {
    if (!data_ || sealed_ || mprotect(data_, size_, PROT_READ | PROT_EXEC)) return false;
    __builtin___clear_cache(reinterpret_cast<char*>(data_), reinterpret_cast<char*>(data_ + size_));
    sealed_ = true;
    return true;
}
}

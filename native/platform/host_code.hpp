// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <span>

namespace SkyHost {
// Host-owned trampoline memory: writable during construction, RX after seal.
// near_address requests an arena within rel32 reach, not a fixed placement.
// Individual fixed-address guest mappings remain the responsibility of host_memory.
class CodeMemory {
public:
    CodeMemory() = default;
    ~CodeMemory();
    CodeMemory(const CodeMemory&) = delete;
    CodeMemory& operator=(const CodeMemory&) = delete;
    bool allocate(std::size_t size, std::uint64_t near_address = 0) noexcept;
    bool seal() noexcept;
    std::span<std::uint8_t> writable() noexcept {
        return sealed_ ? std::span<std::uint8_t>{} : std::span<std::uint8_t>{data_, size_};
    }
    std::uint64_t address() const noexcept { return reinterpret_cast<std::uintptr_t>(data_); }
private:
    std::uint8_t* data_ = nullptr;
    std::size_t size_ = 0;
    bool sealed_ = false;
};
}

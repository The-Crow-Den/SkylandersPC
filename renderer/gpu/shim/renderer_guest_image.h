// SPDX-License-Identifier: GPL-2.0-or-later
// renderer: where the game's executable is mapped, as the host reports it (runtime_guest_image).
// Fault and trap reports tell the game's code from the host's by it, and give the game's code as
// offsets into its image. (The upstream loader mapped its game at 0x800000000; a host loads the
// executable at the base its ELF asks for.)
#pragma once
#include <atomic>
#include <cstdint>

extern "C" void runtime_guest_image(std::uint64_t* base, std::uint64_t* size);

namespace SkyGuestImage {

struct Range {
    std::uint64_t begin = 0, end = 0;
};

/// Asked once the host has mapped the image; empty until then. Lock-free: fault handlers ask.
inline Range Get() {
    static std::atomic<std::uint64_t> begin{0}, end{0};
    if (end.load(std::memory_order_acquire) == 0) {
        std::uint64_t base = 0, size = 0;
        runtime_guest_image(&base, &size);
        if (size == 0) {
            return {};
        }
        begin.store(base, std::memory_order_relaxed);
        end.store(base + size, std::memory_order_release);
    }
    return {begin.load(std::memory_order_relaxed), end.load(std::memory_order_relaxed)};
}

inline bool Contains(std::uint64_t address) {
    const Range range = Get();
    return address >= range.begin && address < range.end;
}

inline std::uint64_t Base() {
    return Get().begin;
}

} // namespace SkyGuestImage

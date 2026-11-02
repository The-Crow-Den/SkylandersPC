// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_random.hpp"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <bcrypt.h>
namespace SkyHost {
bool random_bytes(std::span<std::uint8_t> output) noexcept {
    while (!output.empty()) {
        const auto chunk = output.first(output.size() > 256 ? 256 : output.size());
        if (BCryptGenRandom(nullptr, chunk.data(), static_cast<ULONG>(chunk.size()),
                            BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0) return false;
        output = output.subspan(chunk.size());
    }
    return true;
}
}

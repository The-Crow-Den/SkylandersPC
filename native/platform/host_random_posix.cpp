// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_random.hpp"
#include <cerrno>
#include <sys/random.h>
namespace SkyHost {
bool random_bytes(std::span<std::uint8_t> output) noexcept {
    // Small bounded requests also avoid size_t/ssize_t conversion limits.
    while (!output.empty()) {
        const auto chunk = output.first(output.size() > 256 ? 256 : output.size());
        const auto count = getrandom(chunk.data(), chunk.size(), 0);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0 || static_cast<std::size_t>(count) > chunk.size()) return false;
        output = output.subspan(static_cast<std::size_t>(count));
    }
    return true;
}
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <span>
namespace SkyHost {
// Fill the entire buffer from the host's cryptographic system RNG. A failure
// may have partially changed the output; callers must discard it. No fallback
// seed, deterministic value or guest data substitutes for an unavailable RNG.
bool random_bytes(std::span<std::uint8_t> output) noexcept;
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "guest_code.hpp"
#include <functional>
#include <optional>

namespace GuestCode::Detail {
// Internal recognizer. Ranges/tail must come from validated discovery, not
// untrusted guesses at instruction starts. Unknown forms return no evidence.
std::optional<SwitchTable>
recognize_switch(std::span<const std::uint8_t> executable, std::span<const GuestTls::CodeRange> ranges,
                 std::span<const GuestTls::CodeRange> tail,
                 const std::function<std::optional<std::uint64_t>(std::uint64_t, unsigned)> &known_base);
std::optional<SwitchTable> recognize_cfg_switch(std::span<const std::uint8_t> executable,
    std::span<const GuestTls::CodeRange> ranges, std::span<const GuestTls::CodeRange> tail,
    const std::function<std::optional<std::uint64_t>(std::uint64_t,unsigned)>& known_base,
    const std::function<std::optional<std::uint64_t>(std::uint64_t,unsigned)>& known_bound);
} // namespace GuestCode::Detail

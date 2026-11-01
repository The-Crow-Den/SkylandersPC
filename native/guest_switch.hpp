// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "guest_code.hpp"
#include <optional>

namespace GuestCode::Detail {
// Internal recognizer. Ranges/tail must come from validated discovery, not
// untrusted guesses at instruction starts. Unknown forms return no evidence.
std::optional<SwitchTable> recognize_switch(std::span<const std::uint8_t> executable,
                                            std::span<const GuestTls::CodeRange> ranges,
                                            std::span<const GuestTls::CodeRange> tail);
} // namespace GuestCode::Detail

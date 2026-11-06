// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "guest_code.hpp"
#include <map>
#include <optional>
#include <set>

namespace GuestCode::Detail {
// Backward invariant query over known control-flow edges only. Stops at roots,
// register writes, ABI-clobbering calls, conflicting definitions or its budget.
// Reaching a loop twice imposes no new definition; a proof still requires at
// least one RIP-relative LEA and all finite incoming paths must agree.
std::optional<std::uint64_t>
known_rip_base(std::span<const std::uint8_t> executable,
               const std::map<std::uint64_t, GuestTls::CodeRange> &instructions,
               const std::multimap<std::uint64_t, std::uint64_t> &branch_predecessors,
               const std::set<std::uint64_t> &entries, const std::set<std::uint64_t> &terminating_calls,
               std::uint64_t read_address, unsigned gpr);
} // namespace GuestCode::Detail

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "guest_constants.hpp"

namespace GuestCode::Detail {
// Exclusive unsigned upper bound (1..65536) over all currently known incoming
// paths. Roots, unmodeled writes and volatile calls refuse. JA/JAE fallthrough
// and JB/JBE taken edges bound an index; their opposite edges do not. A branch
// targeting its own fallthrough cannot constrain values. Callers must repeat
// the query after adding control-flow edges.
// Register copies and immediate AND masks retain the queried expression. A
// guarded copied/masked alias must agree along a unique path without changing
// the queried source; a mask alone does not classify a table. Alias walk:64 nodes.
// Limits: 65,536 states per walk and 262,144 decodes shared with nested checks.
std::optional<std::uint64_t>
known_index_bound(std::span<const std::uint8_t> executable,
                  const std::map<std::uint64_t, GuestTls::CodeRange> &instructions,
                  const std::multimap<std::uint64_t, std::uint64_t> &branch_predecessors,
                  const std::set<std::uint64_t> &entries, const std::set<std::uint64_t> &terminating_calls,
                  std::uint64_t read_address, unsigned gpr);
} // namespace GuestCode::Detail

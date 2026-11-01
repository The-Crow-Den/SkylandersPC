// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "guest_tls.hpp"
#include <cstddef>

namespace GuestCode {
enum class ExitKind { IndirectJump, IndirectCall, ExternalBranch, ExternalCall, Trap };
struct Exit {
    std::uint64_t address;
    ExitKind kind;
    std::uint64_t target; // Zero for unknown indirect destinations and traps.
};
struct NoReturnTarget {
    std::uint64_t address;
    std::vector<std::uint8_t> expected_bytes;
};
struct SwitchTable {
    std::uint64_t entry_address;
    std::uint64_t guard_address;
    std::uint64_t dispatch_address;
    std::uint64_t table_address;
    std::uint64_t table_size;
    std::vector<std::uint64_t> targets;
};
struct Analysis {
    std::vector<GuestTls::CodeRange> instructions;
    std::vector<Exit> unresolved;
    // Guarded relative tables for known roots/edges, not a completeness claim.
    std::vector<SwitchTable> switch_tables;
};
// Diagnostic evidence only: roots do not prove that every possible entry was
// supplied. Follow direct control flow without decoding unreachable inline
// pools. Refine supported bounded relative switches. Record other indirect/external exits; never assume their targets or skip
// undecodable reachable bytes. Reject instruction overlaps and interior entries.
// A caller may provide metadata-verified nonreturning import thunks, guarded by
// original thunk bytes as well as the executable hash. No guessed noreturns.
// No code is modified and this analysis alone cannot authorize a TLS profile.
Analysis discover(std::span<const std::uint8_t> executable,
                  std::span<const GuestTls::CodeRange> executable_ranges,
                  std::span<const std::uint64_t> roots, const std::string& expected_sha256,
                  std::size_t max_instructions = 4'000'000,
                  std::span<const NoReturnTarget> no_return = {});
}

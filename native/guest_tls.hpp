// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <span>
#include <string>
#include <vector>
#include "platform/host_tls.hpp"

namespace GuestTls {
struct CodeRange {
    std::uint64_t file_offset;
    std::uint64_t address;
    std::uint64_t size;
};
struct Site {
    std::uint64_t address;
    std::vector<std::uint8_t> expected_bytes;
    unsigned destination_register; // Architectural GPR number, RAX=0 .. R15=15.
    std::int64_t displacement;
};
struct Manifest {
    std::string executable_sha256;
    std::string sites_sha256;
    std::vector<Site> sites;
};
struct Profile {
    std::string executable_sha256;
    std::uint64_t site_count;
    std::string sites_sha256;
};
// Read-only preflight for a future rewriter. Decodes every byte of each supplied
// executable range. Unsupported FS forms or undecodable bytes throw, never skip.
// Ranges must describe original executable bytes, before any other patching.
Manifest inspect(std::span<const std::uint8_t> executable, std::span<const CodeRange> ranges);
// Requires a reviewed executable hash AND a deterministic count/site digest.
// This validates authorization only; neither function modifies executable code.
void verify(const Manifest& manifest, const Profile& profile);
struct Patch {
    std::uint64_t address;
    std::vector<std::uint8_t> expected_bytes;
    std::vector<std::uint8_t> replacement;
};
struct WritableCode {
    std::span<std::uint8_t> bytes;
};
class RewritePlan {
public:
    const std::vector<Patch>& patches() const noexcept { return patches_; }
    const std::vector<std::uint8_t>& trampolines() const noexcept { return trampolines_; }
private:
    RewritePlan() = default;
    std::uint64_t arena_address_{};
    std::vector<Patch> patches_;
    std::vector<std::uint8_t> trampolines_;
    friend RewritePlan prepare(std::span<const std::uint8_t>, std::span<const CodeRange>,
                               const Profile&, std::uint64_t, std::size_t, SkyHost::TlsAccess);
    friend void apply(const RewritePlan&, std::span<const WritableCode>, std::span<std::uint8_t>);
};
// Re-inspects original bytes and verifies the profile before emitting anything.
// Both rel32 jumps must fit exactly; arena addresses are never rounded/moved.
RewritePlan prepare(std::span<const std::uint8_t> executable, std::span<const CodeRange> ranges,
                    const Profile& profile, std::uint64_t arena_address, std::size_t arena_capacity,
                    SkyHost::TlsAccess access);
// Caller owns these writable, nonexecuting mappings and must exclude execution
// and concurrent writes. Validates ALL site bytes and destinations before any
// write. After success, caller seals code RX and flushes its instruction cache.
void apply(const RewritePlan& plan, std::span<const WritableCode> code, std::span<std::uint8_t> arena);
}

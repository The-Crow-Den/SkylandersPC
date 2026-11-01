// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <span>
#include <string>
#include <vector>

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
}

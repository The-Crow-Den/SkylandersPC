// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_tls.hpp"
#include <Zydis/Zydis.h>
#include <openssl/evp.h>
#include <algorithm>
#include <array>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace GuestTls {
namespace {
std::string sha256(std::span<const std::uint8_t> data) {
    std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
    unsigned size = 0;
    if (!EVP_Digest(data.data(), data.size(), digest.data(), &size, EVP_sha256(), nullptr) || size != 32)
        throw std::runtime_error("TLS manifest SHA-256 failed");
    std::ostringstream out;
    for (unsigned i = 0; i < size; ++i) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(digest[i]);
    return out.str();
}
void append_u64(std::vector<std::uint8_t>& output, std::uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) output.push_back(static_cast<std::uint8_t>(value >> (i * 8)));
}
[[noreturn]] void reject(std::uint64_t address, std::span<const std::uint8_t> bytes, const char* reason) {
    std::ostringstream out;
    out << "guest TLS at 0x" << std::hex << address << ": " << reason << " [";
    for (auto byte : bytes.first(std::min<std::size_t>(bytes.size(), 15)))
        out << std::setw(2) << std::setfill('0') << unsigned(byte);
    throw std::runtime_error(out.str() + "]");
}
bool valid_hash(const std::string& value) {
    return value.size() == 64 && value.find_first_not_of("0123456789abcdef") == std::string::npos;
}
}
void verify_executable(std::span<const std::uint8_t> executable, const std::string& expected_sha256) {
    if (!valid_hash(expected_sha256) || sha256(executable) != expected_sha256)
        throw std::runtime_error("guest executable SHA-256 mismatch before code analysis");
}
Manifest inspect(std::span<const std::uint8_t> executable, std::span<const CodeRange> ranges) {
    if (ranges.empty()) throw std::runtime_error("guest TLS requires executable code ranges");
    std::vector<CodeRange> sorted(ranges.begin(), ranges.end());
    std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) { return a.address < b.address; });
    std::uint64_t end = 0;
    for (const auto& range : sorted) {
        if (!range.size || range.file_offset > executable.size() || range.size > executable.size() - range.file_offset ||
            range.address > std::numeric_limits<std::uint64_t>::max() - range.size || range.address < end)
            throw std::runtime_error("invalid or overlapping guest TLS code range");
        end = range.address + range.size;
    }
    ZydisDecoder decoder{};
    if (!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, ZYDIS_MACHINE_MODE_LONG_64, ZYDIS_STACK_WIDTH_64)))
        throw std::runtime_error("cannot initialize guest TLS decoder");
    Manifest result{sha256(executable), {}, {}};
    // Versioned, architecture-independent encoding: domain, then address, byte
    // count and original instruction bytes for each site in address order.
    std::vector<std::uint8_t> encoded{'S','K','Y','-','F','S',1};
    for (const auto& range : sorted) {
        auto code = executable.subspan(static_cast<std::size_t>(range.file_offset), static_cast<std::size_t>(range.size));
        std::uint64_t address = range.address;
        while (!code.empty()) {
            ZydisDecodedInstruction instruction{};
            ZydisDecodedOperand operands[ZYDIS_MAX_OPERAND_COUNT]{};
            if (!ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, code.data(), code.size(), &instruction, operands)))
                reject(address, code, "cannot decode instruction");
            const auto bytes = code.first(instruction.length);
            if (instruction.attributes & ZYDIS_ATTRIB_HAS_SEGMENT_FS) {
                // First supported form: MOV r64, FS:[absolute disp32]. Other
                // forms must be implemented and tested before being accepted.
                if (instruction.mnemonic != ZYDIS_MNEMONIC_MOV || instruction.operand_count_visible != 2 ||
                    instruction.address_width != 64 || instruction.length < 5 ||
                    operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER || operands[0].size != 64 ||
                    operands[0].reg.value < ZYDIS_REGISTER_RAX || operands[0].reg.value > ZYDIS_REGISTER_R15 ||
                    operands[0].reg.value == ZYDIS_REGISTER_RSP ||
                    operands[1].type != ZYDIS_OPERAND_TYPE_MEMORY || operands[1].size != 64 ||
                    operands[1].mem.segment != ZYDIS_REGISTER_FS || operands[1].mem.base != ZYDIS_REGISTER_NONE ||
                    operands[1].mem.index != ZYDIS_REGISTER_NONE || instruction.raw.disp.size != 32)
                    reject(address, bytes, "unsupported FS instruction form");
                result.sites.push_back({address, {bytes.begin(), bytes.end()},
                    static_cast<unsigned>(operands[0].reg.value - ZYDIS_REGISTER_RAX), operands[1].mem.disp.value});
                append_u64(encoded, address);
                append_u64(encoded, bytes.size());
                encoded.insert(encoded.end(), bytes.begin(), bytes.end());
            }
            code = code.subspan(instruction.length);
            address += instruction.length;
        }
    }
    result.sites_sha256 = sha256(encoded);
    return result;
}
void verify(const Manifest& manifest, const Profile& profile) {
    if (!valid_hash(profile.executable_sha256) || !valid_hash(profile.sites_sha256) ||
        manifest.executable_sha256 != profile.executable_sha256 || manifest.sites.size() != profile.site_count ||
        manifest.sites_sha256 != profile.sites_sha256)
        throw std::runtime_error("guest TLS profile hash/count/site digest mismatch");
}
}

namespace GuestTls {
namespace {
void append_u32(std::vector<std::uint8_t>& output, std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) output.push_back(static_cast<std::uint8_t>(value >> (i * 8)));
}
std::uint64_t checked_add(std::uint64_t a, std::uint64_t b) {
    if (b > std::numeric_limits<std::uint64_t>::max() - a)
        throw std::runtime_error("guest TLS address overflow");
    return a + b;
}
void jump(std::vector<std::uint8_t>& output, std::uint64_t pc, std::uint64_t target) {
    const auto next = checked_add(pc, 5);
    const auto delta = target >= next ? target - next : next - target;
    if (delta > (target >= next ? 0x7fffffffULL : 0x80000000ULL))
        throw std::runtime_error("guest TLS trampoline is outside rel32 range");
    const auto bits = static_cast<std::uint32_t>(delta);
    output.push_back(0xe9);
    append_u32(output, target >= next ? bits : 0u - bits);
}
// MOV dst, [dst + disp32]. Only dst is changed, and flags/stack are untouched.
void load(std::vector<std::uint8_t>& output, unsigned reg, std::int32_t displacement) {
    output.push_back(static_cast<std::uint8_t>(0x48 | (reg >= 8 ? 5 : 0)));
    output.push_back(0x8b);
    output.push_back(static_cast<std::uint8_t>(0x80 | ((reg & 7) << 3) | (reg & 7)));
    if ((reg & 7) == 4) output.push_back(0x24); // R12 requires a SIB byte.
    append_u32(output, static_cast<std::uint32_t>(displacement));
}
}
RewritePlan prepare(std::span<const std::uint8_t> executable, std::span<const CodeRange> ranges,
                    const Profile& profile, std::uint64_t arena_address, std::size_t arena_capacity,
                    SkyHost::TlsAccess access) {
    const auto manifest = inspect(executable, ranges);
    verify(manifest, profile);
    if (!arena_address) throw std::runtime_error("guest TLS arena address is null");
    const auto arena_end = checked_add(arena_address, arena_capacity);
    for (const auto& range : ranges) {
        if (arena_address < checked_add(range.address, range.size) && range.address < arena_end)
            throw std::runtime_error("guest TLS arena overlaps guest code");
    }
    RewritePlan plan;
    plan.arena_address_ = arena_address;
    for (const auto& site : manifest.sites) {
        const auto start = checked_add(arena_address, plan.trampolines_.size());
        const auto reg = site.destination_register;
        // MOV dst, FS/GS:[disp32] (absolute SIB form, no RIP-relative addressing).
        auto& out = plan.trampolines_;
        out.push_back(access.use_gs ? 0x65 : 0x64);
        out.push_back(static_cast<std::uint8_t>(0x48 | (reg >= 8 ? 4 : 0)));
        out.push_back(0x8b);
        out.push_back(static_cast<std::uint8_t>(((reg & 7) << 3) | 4));
        out.push_back(0x25);
        append_u32(out, static_cast<std::uint32_t>(access.displacement));
        if (access.indirect) load(out, reg, 8); // TlsState::guest_tcb.
        load(out, reg, static_cast<std::int32_t>(site.displacement));
        jump(out, checked_add(arena_address, out.size()), checked_add(site.address, site.expected_bytes.size()));
        if (out.size() > arena_capacity) throw std::runtime_error("guest TLS trampoline arena is too small");
        Patch patch{site.address, site.expected_bytes, {}};
        jump(patch.replacement, site.address, start);
        patch.replacement.resize(site.expected_bytes.size(), 0x90);
        plan.patches_.push_back(std::move(patch));
    }
    return plan;
}
void apply(const RewritePlan& plan, std::span<const WritableCode> code, std::span<std::uint8_t> arena) {
    if (reinterpret_cast<std::uintptr_t>(arena.data()) != plan.arena_address_ ||
        arena.size() < plan.trampolines_.size())
        throw std::runtime_error("guest TLS trampoline mapping mismatch");
    const auto arena_end = checked_add(plan.arena_address_, arena.size());
    for (std::size_t i = 0; i < code.size(); ++i) {
        const auto start = reinterpret_cast<std::uintptr_t>(code[i].bytes.data());
        const auto end = checked_add(start, code[i].bytes.size());
        if (start < arena_end && plan.arena_address_ < end)
            throw std::runtime_error("guest TLS writable mappings overlap arena");
        for (std::size_t j = 0; j < i; ++j) {
            const auto other = reinterpret_cast<std::uintptr_t>(code[j].bytes.data());
            if (start < checked_add(other, code[j].bytes.size()) && other < end)
                throw std::runtime_error("guest TLS writable mappings overlap");
        }
    }
    std::vector<std::span<std::uint8_t>> destinations;
    destinations.reserve(plan.patches_.size());
    for (const auto& patch : plan.patches_) {
        std::span<std::uint8_t> destination;
        for (const auto& mapping : code) {
            const auto start = reinterpret_cast<std::uintptr_t>(mapping.bytes.data());
            if (patch.address >= start && patch.address - start <= mapping.bytes.size() &&
                patch.expected_bytes.size() <= mapping.bytes.size() - (patch.address - start)) {
                destination = mapping.bytes.subspan(static_cast<std::size_t>(patch.address - start), patch.expected_bytes.size());
                break;
            }
        }
        if (destination.size() != patch.expected_bytes.size() ||
            !std::equal(destination.begin(), destination.end(), patch.expected_bytes.begin()))
            throw std::runtime_error("guest TLS original site bytes mismatch");
        destinations.push_back(destination);
    }
    // All validation/allocation completed above: a late mismatch leaves every
    // code site AND the trampoline arena untouched.
    std::copy(plan.trampolines_.begin(), plan.trampolines_.end(), arena.begin());
    for (std::size_t i = 0; i < destinations.size(); ++i)
        std::copy(plan.patches_[i].replacement.begin(), plan.patches_[i].replacement.end(), destinations[i].begin());
}
}

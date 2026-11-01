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

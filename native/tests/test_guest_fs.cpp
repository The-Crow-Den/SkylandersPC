// SPDX-License-Identifier: GPL-3.0-or-later
#include "../guest_fs.hpp"
#include <array>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool value, const char* what) { if (!value) throw std::runtime_error(what); }
using Bytes = std::vector<std::uint8_t>;
Bytes load(std::uint8_t rex, std::uint8_t modrm, std::int32_t displacement) {
    Bytes code{0x64, rex, 0x8b, modrm, 0x25};
    for (unsigned i = 0; i < 4; ++i) code.push_back(static_cast<std::uint8_t>(static_cast<std::uint32_t>(displacement) >> (8 * i)));
    return code;
}
std::uint8_t modrm_for(unsigned reg) { return static_cast<std::uint8_t>(((reg & 7u) << 3) | 0x04); }
std::uint8_t rex_for(unsigned reg) { return reg >= 8 ? 0x4c : 0x48; }
}

int main() {
    try {
        GuestFs::Load decoded{};
        // Every destination except RSP, low and negative displacements.
        for (unsigned reg = 0; reg < 16; ++reg) {
            for (std::int32_t displacement : {0, 0x10, 0x7ff8, -8}) {
                const auto code = load(rex_for(reg), modrm_for(reg), displacement);
                const bool ok = GuestFs::decode(code.data(), code.size(), decoded);
                if (reg == 4) { require(!ok, "RSP destination admitted"); continue; }
                require(ok && decoded.destination == reg && decoded.displacement == displacement &&
                        decoded.length == 9, "admitted FS load not decoded");
            }
        }
        require(GuestFs::fault_address({0, 0x10, 9}) == 0x10, "positive fault address");
        require(GuestFs::fault_address({0, -8, 9}) == ~std::uint64_t{0}, "noncanonical fault address");
        // Refused encodings: each differs from an admitted one in one detail.
        const std::array<Bytes, 9> refused{{
            {0x64, 0x48, 0xa1, 0, 0, 0, 0, 0, 0, 0, 0},       // MOV RAX, moffs64
            {0x65, 0x48, 0x8b, 0x04, 0x25, 0, 0, 0, 0},       // GS, not FS
            {0x64, 0x40, 0x8b, 0x04, 0x25, 0, 0, 0, 0},       // 32-bit operand
            {0x64, 0x4a, 0x8b, 0x04, 0x25, 0, 0, 0, 0},       // REX.X: R12 index
            {0x64, 0x49, 0x8b, 0x04, 0x25, 0, 0, 0, 0},       // REX.B
            {0x64, 0x48, 0x89, 0x04, 0x25, 0, 0, 0, 0},       // store
            {0x64, 0x48, 0x8b, 0x44, 0x25, 0},                // mod=01 (RBP-relative)
            {0x64, 0x48, 0x8b, 0x04, 0x24},                   // SIB base RSP
            {0x64, 0x48, 0x8b, 0x04, 0x25, 0, 0, 0},          // truncated
        }};
        for (const auto& code : refused) require(!GuestFs::decode(code.data(), code.size(), decoded), "refused form decoded");

        // Emulation against a synthetic fault: the instruction is this buffer.
        alignas(16) std::array<std::uint64_t, 4> tcb{0x1111, 0x2222, 0x3333, 0x4444};
        const auto r13 = load(rex_for(13), modrm_for(13), 0x10);
        SkyHost::Fault fault{};
        fault.kind = SkyHost::FaultKind::access;
        fault.access = SkyHost::FaultAccess::read;
        fault.address = 0x10;
        fault.cpu.pc = reinterpret_cast<std::uintptr_t>(r13.data());
        fault.cpu.gpr[3] = 77;
        const auto start = fault.cpu.pc;
        require(GuestFs::emulate(fault, reinterpret_cast<std::uintptr_t>(tcb.data())), "load not emulated");
        require(fault.cpu.gpr[13] == 0x3333 && fault.cpu.pc == start + 9 && fault.cpu.gpr[3] == 77, "wrong emulation");
        auto mismatch = fault;
        mismatch.cpu.pc = start;
        mismatch.address = 0x18;
        require(!GuestFs::emulate(mismatch, reinterpret_cast<std::uintptr_t>(tcb.data())), "other address emulated");
        mismatch.address = 0x10;
        mismatch.access = SkyHost::FaultAccess::write;
        require(!GuestFs::emulate(mismatch, reinterpret_cast<std::uintptr_t>(tcb.data())), "write emulated");
        mismatch.access = SkyHost::FaultAccess::read;
        require(!GuestFs::emulate(mismatch, 0), "missing TCB emulated");

        // Windows: a real FS:[0] load must fault and be emulated (zero FS base).
        require(GuestFs::install(), "FS loads are not emulable in this process");
#ifdef _WIN32
        require(GuestFs::emulated_loads() == 1, "probe not counted");
#endif
        std::puts("guest FS load emulation passed");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "guest FS test failed: %s\n", error.what());
        return 1;
    }
}

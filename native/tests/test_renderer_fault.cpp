// SPDX-License-Identifier: GPL-3.0-or-later
#include "../../renderer/gpu/shim/fault_context.h"
#include <stdexcept>
namespace {
void require(bool value) { if (!value) throw std::runtime_error("renderer fault context assertion failed"); }
void unchanged(const SkyRenderAccessFault& a, const SkyRenderAccessFault& b) {
    for (unsigned i = 0; i < 16; ++i) require(a.gpr[i] == b.gpr[i]);
    require(a.pc == b.pc && a.flags == b.flags && a.address == b.address && a.access == b.access);
}
}
int main() {
    constexpr std::array registers{REG_RAX,REG_RCX,REG_RDX,REG_RBX,REG_RSP,REG_RBP,REG_RSI,REG_RDI,
                                    REG_R8,REG_R9,REG_R10,REG_R11,REG_R12,REG_R13,REG_R14,REG_R15};
    SkyRenderAccessFault original{};
    for (unsigned i = 0; i < 16; ++i) original.gpr[i] = 0xfedcba9876540000ULL + i;
    original.pc = 0x123456780;
    original.flags = 0x247;
    original.address = 0x234567890;
    for (std::uint32_t access = 0; access <= 3; ++access) {
        auto fault = original;
        fault.access = access;
        const auto before = fault;
        bool called = false;
        require(SkyRender::DispatchAccessFault(&fault, [&](void* raw, void* address) {
            called = true;
            auto& context = *static_cast<ucontext_t*>(raw);
            auto& g = context.uc_mcontext.gregs;
            require(reinterpret_cast<std::uintptr_t>(address) == original.address);
            require(g[REG_RIP] == static_cast<greg_t>(original.pc) && g[REG_EFL] == static_cast<greg_t>(original.flags));
            require(g[REG_ERR] == (access == 2 ? 2 : access == 3 ? 16 : 0));
            require(context.uc_mcontext.fpregs == nullptr);
            for (unsigned i = 0; i < 16; ++i) {
                require(static_cast<std::uint64_t>(g[registers[i]]) == original.gpr[i]);
                g[registers[i]] = static_cast<greg_t>(original.gpr[i] ^ (0x100ULL << i));
            }
            g[REG_RIP] += 3;
            g[REG_EFL] ^= 1;
            return true;
        }));
        require(called && fault.pc == original.pc + 3 && fault.flags == (original.flags ^ 1));
        for (unsigned i = 0; i < 16; ++i) require(fault.gpr[i] == (original.gpr[i] ^ (0x100ULL << i)));
        require(fault.address == before.address && fault.access == before.access);
        fault = before;
        require(!SkyRender::DispatchAccessFault(&fault, [](void* raw, void*) {
            auto& g = static_cast<ucontext_t*>(raw)->uc_mcontext.gregs;
            for (auto& value : g) value = 0;
            return false;
        }));
        unchanged(fault,before);
    }
    auto invalid = original;
    invalid.access = 4;
    const auto before = invalid;
    auto never = [](void*, void*) { require(false); return true; };
    require(!SkyRender::DispatchAccessFault(&invalid,never));
    unchanged(invalid,before);
    require(!SkyRender::DispatchAccessFault(nullptr,never));
}

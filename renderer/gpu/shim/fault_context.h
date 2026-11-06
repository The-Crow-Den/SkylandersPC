// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "../skyrender.h"
#include <array>
#include <cstdint>
#include <sys/ucontext.h>

namespace SkyRender {
// The existing access handlers use GPRs, RIP, flags and access direction only.
// Adapt those fields to their internal context layout, never expose the host's
// live native context or fabricate a signal/system call. If the registry
// declines the fault, all register edits made during dispatch are discarded.
// FP/vector handlers require an explicit extension of this interface.
template<class Dispatch>
bool DispatchAccessFault(SkyRenderAccessFault* fault, Dispatch dispatch) {
    if (!fault || fault->access > 3) return false;
    constexpr std::array registers{REG_RAX,REG_RCX,REG_RDX,REG_RBX,REG_RSP,REG_RBP,REG_RSI,REG_RDI,
                                    REG_R8,REG_R9,REG_R10,REG_R11,REG_R12,REG_R13,REG_R14,REG_R15};
    ucontext_t context{};
    auto& g = context.uc_mcontext.gregs;
    for (unsigned i = 0; i < registers.size(); ++i) g[registers[i]] = static_cast<greg_t>(fault->gpr[i]);
    g[REG_RIP] = static_cast<greg_t>(fault->pc);
    g[REG_EFL] = static_cast<greg_t>(fault->flags);
    // Internal handler predicate Common::IsWriteError uses bit 1. This is an
    // adapter for the supplied access direction, not a native fault error code.
    g[REG_ERR] = fault->access == 2 ? 2 : fault->access == 3 ? 16 : 0;
    if (!dispatch(&context, reinterpret_cast<void*>(static_cast<std::uintptr_t>(fault->address)))) return false;
    for (unsigned i = 0; i < registers.size(); ++i) fault->gpr[i] = static_cast<std::uint64_t>(g[registers[i]]);
    fault->pc = static_cast<std::uint64_t>(g[REG_RIP]);
    fault->flags = static_cast<std::uint64_t>(g[REG_EFL]);
    return true;
}
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_fault.hpp"
#include "../guest_start.hpp"
#include <atomic>
#include <csignal>
#include <cstdlib>
#include <ucontext.h>

namespace SkyHost {
namespace {
std::atomic<FaultHandler> handler{nullptr};
static_assert(decltype(handler)::is_always_lock_free);
constexpr std::array signals{SIGSEGV,SIGBUS,SIGILL,SIGFPE,SIGTRAP};
std::array<struct sigaction, signals.size()> previous{};
constexpr std::array registers{REG_RAX,REG_RCX,REG_RDX,REG_RBX,REG_RSP,REG_RBP,REG_RSI,REG_RDI,
                              REG_R8,REG_R9,REG_R10,REG_R11,REG_R12,REG_R13,REG_R14,REG_R15};
bool installed = false;
SKY_SYSV_ABI int dispatch(int signal, void* raw_info, void* raw_context) noexcept {
    const auto* info = static_cast<siginfo_t*>(raw_info);
    auto* c = static_cast<ucontext_t*>(raw_context);
    if (info->si_code <= 0) return 0; // Not a synchronous processor fault.
    Fault fault{};
    fault.native_code = static_cast<std::uint32_t>(signal);
    switch (signal) {
    case SIGSEGV: case SIGBUS: fault.kind = FaultKind::access; break;
    case SIGILL: fault.kind = FaultKind::illegal_instruction; break;
    case SIGFPE: fault.kind = FaultKind::arithmetic; break;
    case SIGTRAP: fault.kind = FaultKind::breakpoint; break;
    default: return 0;
    }
    fault.address = reinterpret_cast<std::uintptr_t>(info->si_addr);
    // x86 page-fault error bits are meaningful only for vector 14, not #GP
    // or SIGBUS. Do not invent an access direction for other processor traps.
    if (c->uc_mcontext.gregs[REG_TRAPNO] == 14) {
        const auto error = c->uc_mcontext.gregs[REG_ERR];
        fault.access = (error & 16) ? FaultAccess::execute :
                       (error & 2) ? FaultAccess::write : FaultAccess::read;
    }
    for (unsigned i=0; i<registers.size(); ++i)
        fault.cpu.gpr[i]=static_cast<std::uint64_t>(c->uc_mcontext.gregs[registers[i]]);
    fault.cpu.pc=static_cast<std::uint64_t>(c->uc_mcontext.gregs[REG_RIP]);
    fault.cpu.flags=static_cast<std::uint64_t>(c->uc_mcontext.gregs[REG_EFL]);
    const auto callback=handler.load(std::memory_order_acquire);
    if (!callback || !callback(fault)) return 0;
    for (unsigned i=0; i<registers.size(); ++i)
        c->uc_mcontext.gregs[registers[i]]=static_cast<greg_t>(fault.cpu.gpr[i]);
    c->uc_mcontext.gregs[REG_RIP]=static_cast<greg_t>(fault.cpu.pc);
    c->uc_mcontext.gregs[REG_EFL]=static_cast<greg_t>(fault.cpu.flags);
    return 1;
}
}
bool install_fault_handler(FaultHandler callback) noexcept {
    if (!callback || installed || sky_guest_configure_fault(&dispatch)) return false;
    handler.store(callback, std::memory_order_release);
    struct sigaction action{};
    action.sa_sigaction = &sky_guest_fault_bridge;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&action.sa_mask);
    std::size_t done=0;
    for (; done<signals.size(); ++done) {
        if (sigaction(signals[done], &action, &previous[done])) break;
    }
    if (done != signals.size()) {
        while (done) {
            --done;
            if (sigaction(signals[done], &previous[done], nullptr)) std::abort();
        }
        if (sky_guest_configure_fault(nullptr)) std::abort();
        handler.store(nullptr, std::memory_order_release);
        return false;
    }
    installed=true;
    return true;
}
bool remove_fault_handler() noexcept {
    if (!installed || sky_guest_configure_fault(nullptr)) return false;
    for (std::size_t i=0; i<signals.size(); ++i)
        if (sigaction(signals[i], &previous[i], nullptr)) std::abort();
    handler.store(nullptr, std::memory_order_release);
    installed=false;
    return true;
}
}

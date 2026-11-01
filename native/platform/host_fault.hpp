// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>

namespace SkyHost {
enum class FaultKind { access, illegal_instruction, arithmetic, breakpoint };
enum class FaultAccess { unknown, read, write, execute };
// Architectural encoding order, independent of ucontext/CONTEXT layout.
enum class Gpr : unsigned { rax, rcx, rdx, rbx, rsp, rbp, rsi, rdi,
                           r8, r9, r10, r11, r12, r13, r14, r15 };
struct FaultContext {
    std::array<std::uint64_t, 16> gpr{};
    std::uint64_t pc = 0, flags = 0;
    std::uint64_t& reg(Gpr r) noexcept { return gpr[static_cast<unsigned>(r)]; }
    std::uint64_t reg(Gpr r) const noexcept { return gpr[static_cast<unsigned>(r)]; }
};
struct Fault {
    FaultKind kind;
    FaultAccess access;
    std::uint64_t address;
    std::uint32_t native_code;
    FaultContext cpu;
};
// Native host ABI. Runs in exception/signal context, with host TLS selected.
// Must not allocate, lock, throw, or call non-signal-safe functions on POSIX.
// Only true commits cpu changes and resumes. A false return on Windows searches
// the remaining OS handlers; the existing POSIX guest bridge terminates (126).
using FaultHandler = bool (*)(Fault&) noexcept;

// Process-wide ownership. Caller serializes install/remove against guest entry
// and all faulting threads. POSIX callers must provide per-thread alternate
// signal stacks; dispatch retains the existing FS-restoring assembly bridge.
// Stack overflow/noncontinuable/unknown Windows exceptions are never resumed.
// No handler may be installed through sky_guest_configure_fault concurrently.
bool install_fault_handler(FaultHandler handler) noexcept;
bool remove_fault_handler() noexcept;
}

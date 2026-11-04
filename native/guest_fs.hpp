// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "platform/host_fault.hpp"
#include <cstddef>
#include <cstdint>

// Guest TLS on Windows without rewriting code. Windows user mode cannot set the
// FS base, and for 64-bit threads it is zero, so a guest MOV r64, FS:[disp32]
// faults reading the low 64 KiB (always reserved) instead. The fault handler
// decodes that one instruction, performs the load against the thread's guest
// TCB and resumes after it. Only executed instructions are touched, so no
// static code/data boundary proof is needed, and nothing is patched.
namespace GuestFs {
// The single admitted form (all FS sites in the Trap Team census): 64 REX.W
// [REX.R] 8B /r with mod=00, rm=100, SIB 0x25 (absolute disp32), 9 bytes.
// REX.X/B, RSP destinations and every other encoding are refused.
struct Load {
    unsigned destination; // Architectural GPR number, RAX=0 .. R15=15.
    std::int32_t displacement;
    unsigned length;
};
bool decode(const std::uint8_t* code, std::size_t available, Load& output) noexcept;
// Linear address a zero FS base faults at for this load: the displacement, or
// all ones (Windows' report for the #GP of a noncanonical address).
std::uint64_t fault_address(const Load& load) noexcept;
// Applies an access fault from a decoded FS load: reads 8 bytes at
// tcb + displacement into the destination and advances pc. Refuses a fault
// that is not exactly the load at pc, or a missing TCB.
bool emulate(SkyHost::Fault& fault, std::uint64_t tcb) noexcept;

// Windows: registers the handler first in the vectored chain, then executes a
// real FS:[0] load to prove this process faults on it with a zero FS base.
// False means guest TLS cannot work here; never enter guest code then.
bool install() noexcept;
#ifdef _WIN32
// For the shared fault dispatcher (host_fault_win32.cpp): emulates fault for
// the current thread's guest TCB, if it is an admitted FS load. Runs before any
// registered handler, so a fatal reporter never sees a guest TLS access.
bool emulate_current(SkyHost::Fault& fault) noexcept;
// Successful emulations so far (diagnostics; relaxed counter).
std::uint64_t emulated_loads() noexcept;
#endif
}

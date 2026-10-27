// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstddef>
#include <cstdint>
#include <signal.h>

// Linux x86-64 synthetic entry bridge. The supplied memory must stay valid for
// the whole call; stack_top must leave at least 32 writable bytes below it plus
// the guest's own stack needs. The bridge owns the top 16 bytes while active.
struct SkyGuestStartContext {
    void* entry;
    void* stack_top;
    void* tcb;
    const void* startup_block;
    void* exit_callback;
};

static_assert(sizeof(void*) == 8);
static_assert(sizeof(SkyGuestStartContext) == 40);
static_assert(offsetof(SkyGuestStartContext, entry) == 0);
static_assert(offsetof(SkyGuestStartContext, stack_top) == 8);
static_assert(offsetof(SkyGuestStartContext, tcb) == 16);
static_assert(offsetof(SkyGuestStartContext, startup_block) == 24);
static_assert(offsetof(SkyGuestStartContext, exit_callback) == 32);

// Passes startup_block in RDI and exit_callback in RSI. Switches FS to tcb,
// calls entry on a 16-byte-aligned SysV call stack, and restores host FS/stack
// and callee-saved registers on a normal RET. No libc call runs with guest FS.
// Returns 0 with *returned_value, or a negative errno if validation/arch_prctl
// fails before entry. A failed host-FS restoration terminates the process.
//
// The host supplies explicit import handlers and guarded guest-thread contexts.
// Returning imports, nested callbacks and handled signal resumption preserve TLS.
// C++ unwinding/longjmp across the assembly boundary is unsupported. Entry must
// not call host libc directly while guest FS is set.
extern "C" int sky_guest_start(const SkyGuestStartContext* context,
                                std::uint64_t* returned_value) noexcept;

using SkyGuestTrapHandler = void (*)(std::uint64_t import_index);

// Optional diagnostic bridge. Configure before entry;
// nullptr disables it. Configuration while a trap-enabled guest is active is
// refused with -EBUSY. Caller serializes configuration against entry creation.
extern "C" int sky_guest_configure_trap(SkyGuestTrapHandler handler) noexcept;

// Generated unknown-import thunks put their index in R10 and JMP here. This
// restores the captured host FS and host stack, then calls handler(index).
// Handler must report the canonical import and terminate. If it returns, the
// bridge terminates with code 126. No guest state is resumed or faked.
extern "C" [[noreturn]] void sky_guest_trap_bridge() noexcept;

using SkyGuestFaultHandler = int (*)(int signal, void* info, void* context);

// Diagnostic-only SA_SIGINFO bridge. Install on an alternate signal stack and
// configure a host handler before entry. It restores host FS and forwards the
// original signal/info/ucontext pointers. A handled fault restores interrupted
// FS and returns through sigreturn; the host handler must terminate on failure.
extern "C" int sky_guest_configure_fault(SkyGuestFaultHandler handler) noexcept;
extern "C" void sky_guest_fault_bridge(int signal, siginfo_t* info,
                                                    void* context) noexcept;

// Integer/pointer ABI: six register arguments, separately bounded stack words
// and RAX result. No variadics, vector arguments/results or cross-boundary
// unwinding. Handler runs with host FS on the native stack; actual guest FS is
// restored before return. Concurrent entries and nested callbacks keep separate
// GS contexts. Generated thunks put the import index in R10. Linux FSGSBASE
// support enables direct FS switching; SKY_TLS_BRIDGE=syscall retains fallback.
using SkyGuestCallHandler = std::uint64_t (*)(std::uint64_t index, const std::uint64_t* arguments,
                                            const std::uint64_t* stack_arguments);
extern "C" int sky_guest_configure_call(SkyGuestCallHandler handler) noexcept;
extern "C" void sky_guest_call_bridge() noexcept;
// Host-FS service entry only; no held locks or RAII resources on the call stack.
// Completes the current sky_guest_start with the supplied result.
extern "C" [[noreturn]] void sky_guest_thread_exit(std::uint64_t result) noexcept;
// Host-only call to a verified scalar integer/pointer ABI. Input always has 12
// words (unused slots zeroed). Never pass floating/vector/aggregate signatures.
extern "C" std::uint64_t sky_host_call_integer(void* function, const std::uint64_t* arguments) noexcept;

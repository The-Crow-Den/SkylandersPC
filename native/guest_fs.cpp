// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_fs.hpp"
#include <cstring>
#ifdef _WIN32
#include "platform/host_tls.hpp"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <atomic>
#endif

namespace GuestFs {
bool decode(const std::uint8_t* code, std::size_t available, Load& output) noexcept {
    constexpr unsigned length = 9;
    if (!code || available < length) return false;
    const auto rex = code[1], modrm = code[3];
    // FS prefix, REX.W with only R optionally set, MOV r64, r/m64.
    if (code[0] != 0x64 || (rex & 0xfb) != 0x48 || code[2] != 0x8b) return false;
    // mod=00 rm=100 (SIB follows); SIB scale=0 index=100 (none) base=101 (disp32).
    if ((modrm & 0xc7) != 0x04 || code[4] != 0x25) return false;
    const unsigned destination = ((rex & 0x04) ? 8u : 0u) | ((modrm >> 3) & 7u);
    if (destination == static_cast<unsigned>(SkyHost::Gpr::rsp)) return false;
    std::int32_t displacement;
    std::memcpy(&displacement, code + 5, sizeof(displacement));
    output = {destination, displacement, length};
    return true;
}

std::uint64_t fault_address(const Load& load) noexcept {
    return load.displacement >= 0 ? static_cast<std::uint64_t>(load.displacement) : ~std::uint64_t{0};
}

bool emulate(SkyHost::Fault& fault, std::uint64_t tcb) noexcept {
    if (!tcb || fault.kind != SkyHost::FaultKind::access || fault.access != SkyHost::FaultAccess::read) return false;
    Load load{};
    // The faulting instruction just executed, so these bytes are mapped code.
    if (!decode(reinterpret_cast<const std::uint8_t*>(fault.cpu.pc), 9, load)) return false;
    if (fault.address != fault_address(load)) return false;
    std::uint64_t value;
    std::memcpy(&value, reinterpret_cast<const void*>(tcb + static_cast<std::uint64_t>(static_cast<std::int64_t>(load.displacement))),
                sizeof(value));
    fault.cpu.gpr[load.destination] = value;
    fault.cpu.pc += load.length;
    return true;
}

#ifdef _WIN32
namespace {
std::atomic<std::uint64_t> loads{0};
// The startup probe runs on a host thread with no guest TCB.
thread_local std::uint64_t probe_tcb = 0;

LONG CALLBACK dispatch(EXCEPTION_POINTERS* info) noexcept {
    const auto* record = info->ExceptionRecord;
    if (record->ExceptionCode != EXCEPTION_ACCESS_VIOLATION || record->NumberParameters < 2 ||
        record->ExceptionInformation[0] != 0) return EXCEPTION_CONTINUE_SEARCH;
    std::uint64_t tcb = probe_tcb;
    if (!tcb) {
        const auto* state = sky_host_tls_state();
        tcb = state ? reinterpret_cast<std::uint64_t>(state->guest_tcb) : 0;
    }
    if (!tcb) return EXCEPTION_CONTINUE_SEARCH;
    auto* c = info->ContextRecord;
    SkyHost::Fault fault{};
    fault.kind = SkyHost::FaultKind::access;
    fault.access = SkyHost::FaultAccess::read;
    fault.address = record->ExceptionInformation[1];
    fault.native_code = record->ExceptionCode;
    fault.cpu.gpr = {c->Rax,c->Rcx,c->Rdx,c->Rbx,c->Rsp,c->Rbp,c->Rsi,c->Rdi,
                     c->R8,c->R9,c->R10,c->R11,c->R12,c->R13,c->R14,c->R15};
    fault.cpu.pc = c->Rip;
    if (!emulate(fault, tcb)) return EXCEPTION_CONTINUE_SEARCH;
    DWORD64* registers[] = {&c->Rax,&c->Rcx,&c->Rdx,&c->Rbx,&c->Rsp,&c->Rbp,&c->Rsi,&c->Rdi,
                            &c->R8,&c->R9,&c->R10,&c->R11,&c->R12,&c->R13,&c->R14,&c->R15};
    for (unsigned i = 0; i < 16; ++i) *registers[i] = fault.cpu.gpr[i];
    c->Rip = fault.cpu.pc;
    loads.fetch_add(1, std::memory_order_relaxed);
    return EXCEPTION_CONTINUE_EXECUTION;
}

// MOV RCX, FS:[0] in the exact admitted encoding (an assembler may pick another).
std::uint64_t load_fs_zero() noexcept {
    std::uint64_t value = 0;
    asm volatile(".byte 0x64, 0x48, 0x8b, 0x0c, 0x25, 0x00, 0x00, 0x00, 0x00\n\tmovq %%rcx, %0"
                 : "=r"(value) : : "rcx", "memory");
    return value;
}
}

bool install() noexcept {
    static void* registration = nullptr;
    if (!registration) registration = AddVectoredExceptionHandler(1, &dispatch);
    if (!registration) return false;
    // A sentinel TCB whose first word is its own marker. If FS were not zero-
    // based the load would read some other memory and the marker would differ.
    static constexpr std::uint64_t marker = 0x534b59465350524full; // "SKYFSPRO"
    alignas(16) std::uint64_t tcb[2] = {marker, 0};
    const auto before = loads.load(std::memory_order_relaxed);
    probe_tcb = reinterpret_cast<std::uint64_t>(tcb);
    const auto value = load_fs_zero();
    probe_tcb = 0;
    return value == marker && loads.load(std::memory_order_relaxed) == before + 1;
}

std::uint64_t emulated_loads() noexcept { return loads.load(std::memory_order_relaxed); }
#else
// Linux sets the FS base per guest thread (guest_start.S); nothing to emulate.
bool install() noexcept { return true; }
#endif
}

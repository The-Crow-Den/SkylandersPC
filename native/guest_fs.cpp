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
#include <cstdint>
#include <cstdlib>
#include <new>
#include <vector>
#include "platform/host_memory.hpp"
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

std::uint64_t current_tcb() noexcept {
    if (probe_tcb) return probe_tcb;
    const auto* state = sky_host_tls_state();
    return state ? reinterpret_cast<std::uint64_t>(state->guest_tcb) : 0;
}

// Patch each faulting guest FS load once, so it stops faulting.
// The 9-byte `mov r64, fs:[disp32]` becomes `jmp stub` + 4 bytes of int3; the
// stub does the same load through the host TLS slot without faulting:
//   mov r, gs:[sky_host_tls_offset]   ; TlsState*
//   mov r, [r + 8]                    ; guest_tcb
//   mov r, [r + disp32]
//   jmp pc + 9
// Live patching follows the int3-first sequence (int3, then tail, then the jmp
// opcode). A thread that reaches the site mid-patch (int3) or that faulted on
// the old bytes just before is completed from the recorded site table.
struct Site { std::uint64_t pc; Load load; };
SRWLOCK patch_lock = SRWLOCK_INIT;
std::vector<Site>* sites = nullptr;                 // guarded by patch_lock
std::uint8_t* stubs = nullptr; std::size_t stubs_used = 0, stubs_size = 0;
std::atomic<std::uint64_t> patched{0};
const bool patching_enabled = [] {
    const char* value = std::getenv("SKY_TLS_PATCH");
    return !value || std::strcmp(value, "0") != 0;
}();

const Site* find_site(std::uint64_t pc) noexcept {
    if (!sites) return nullptr;
    for (const auto& site : *sites) if (site.pc == pc) return &site;
    return nullptr;
}

std::size_t emit_load(std::uint8_t* out, unsigned reg, std::uint8_t mod, std::int32_t displacement) noexcept {
    // mov r64, [r64 + disp]: REX.W with R and B both set from reg.
    std::size_t n = 0;
    out[n++] = static_cast<std::uint8_t>(0x48 | ((reg & 8) ? 0x05 : 0));
    out[n++] = 0x8b;
    out[n++] = static_cast<std::uint8_t>((mod << 6) | ((reg & 7) << 3) | (reg & 7));
    if ((reg & 7) == 4) out[n++] = 0x24; // rsp/r12 base needs a SIB byte.
    if (mod == 1) out[n++] = static_cast<std::uint8_t>(displacement);
    else { std::memcpy(out + n, &displacement, 4); n += 4; }
    return n;
}

// Called with patch_lock held exclusively, from the fault handler.
void patch_site(std::uint64_t pc, const Load& load) noexcept {
    if (!patching_enabled || !sky_host_tls_offset || find_site(pc)) return;
    // Guest code only: the host executable and DLLs sit far above 4 GiB.
    if (pc < 0x400000 || pc >= 0x100000000ull) return;
    if (!sites) sites = new (std::nothrow) std::vector<Site>();
    if (!sites) return;
    if (!stubs) {
        stubs_size = 1 << 20;
        stubs = static_cast<std::uint8_t*>(SkyHost::allocate_low_guest(stubs_size, false));
        DWORD previous = 0;
        if (!stubs || !VirtualProtect(stubs, stubs_size, PAGE_EXECUTE_READWRITE, &previous)) { stubs = nullptr; return; }
    }
    if (stubs_used + 32 > stubs_size) return;
    auto* stub = stubs + stubs_used;
    const auto stub_address = reinterpret_cast<std::uint64_t>(stub);
    const auto jump = static_cast<std::int64_t>(stub_address) - static_cast<std::int64_t>(pc + 5);
    if (jump < INT32_MIN || jump > INT32_MAX) return;
    // Build the stub.
    std::size_t n = 0;
    const unsigned reg = load.destination;
    stub[n++] = 0x65; // GS
    stub[n++] = static_cast<std::uint8_t>(0x48 | ((reg & 8) ? 0x04 : 0));
    stub[n++] = 0x8b;
    stub[n++] = static_cast<std::uint8_t>(0x04 | ((reg & 7) << 3));
    stub[n++] = 0x25;
    const auto offset = static_cast<std::int32_t>(sky_host_tls_offset);
    std::memcpy(stub + n, &offset, 4); n += 4;
    n += emit_load(stub + n, reg, 1, 8);
    n += emit_load(stub + n, reg, 2, load.displacement);
    const auto back = static_cast<std::int64_t>(pc + load.length) - static_cast<std::int64_t>(stub_address + n + 5);
    stub[n++] = 0xe9;
    const auto back32 = static_cast<std::int32_t>(back);
    std::memcpy(stub + n, &back32, 4); n += 4;
    FlushInstructionCache(GetCurrentProcess(), stub, n);
    // Record before touching the site so racing threads can be completed.
    try { sites->push_back({pc, load}); } catch (...) { return; }
    stubs_used += 32;
    auto* site = reinterpret_cast<std::uint8_t*>(pc);
    DWORD previous = 0;
    if (!VirtualProtect(site, load.length, PAGE_EXECUTE_READWRITE, &previous)) return;
    reinterpret_cast<volatile std::uint8_t*>(site)[0] = 0xcc;
    FlushInstructionCache(GetCurrentProcess(), site, load.length);
    const auto jump32 = static_cast<std::int32_t>(jump);
    std::memcpy(site + 1, &jump32, 4);
    std::memset(site + 5, 0xcc, load.length - 5);
    FlushInstructionCache(GetCurrentProcess(), site, load.length);
    reinterpret_cast<volatile std::uint8_t*>(site)[0] = 0xe9;
    FlushInstructionCache(GetCurrentProcess(), site, load.length);
    VirtualProtect(site, load.length, previous, &previous);
    patched.fetch_add(1, std::memory_order_relaxed);
}

LONG CALLBACK dispatch(EXCEPTION_POINTERS* info) noexcept {
    const auto* record = info->ExceptionRecord;
    // A thread that hit a site mid-patch (int3), or faulted on the old bytes
    // just before the patch landed: complete the recorded load.
    if (record->ExceptionCode == EXCEPTION_BREAKPOINT || record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION) {
        auto* c = info->ContextRecord;
        const auto tcb = current_tcb();
        if (tcb && sites) {
            AcquireSRWLockShared(&patch_lock);
            const Site* site = find_site(c->Rip);
            if (!site && record->ExceptionCode == EXCEPTION_BREAKPOINT) site = find_site(c->Rip - 1);
            Load load{}; std::uint64_t pc = 0;
            if (site) { load = site->load; pc = site->pc; }
            ReleaseSRWLockShared(&patch_lock);
            if (pc) {
                DWORD64* registers[] = {&c->Rax,&c->Rcx,&c->Rdx,&c->Rbx,&c->Rsp,&c->Rbp,&c->Rsi,&c->Rdi,
                                        &c->R8,&c->R9,&c->R10,&c->R11,&c->R12,&c->R13,&c->R14,&c->R15};
                std::memcpy(registers[load.destination],
                            reinterpret_cast<const void*>(tcb + static_cast<std::uint64_t>(static_cast<std::int64_t>(load.displacement))), 8);
                c->Rip = pc + load.length;
                loads.fetch_add(1, std::memory_order_relaxed);
                return EXCEPTION_CONTINUE_EXECUTION;
            }
        }
    }
    if (record->ExceptionCode != EXCEPTION_ACCESS_VIOLATION || record->NumberParameters < 2 ||
        record->ExceptionInformation[0] != 0) return EXCEPTION_CONTINUE_SEARCH;
    const auto tcb = current_tcb();
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
    const auto site = c->Rip;
    for (unsigned i = 0; i < 16; ++i) *registers[i] = fault.cpu.gpr[i];
    c->Rip = fault.cpu.pc;
    loads.fetch_add(1, std::memory_order_relaxed);
    if (!probe_tcb) {
        Load load{};
        if (decode(reinterpret_cast<const std::uint8_t*>(site), 9, load)) {
            AcquireSRWLockExclusive(&patch_lock);
            patch_site(site, load);
            ReleaseSRWLockExclusive(&patch_lock);
        }
    }
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

bool emulate_current(SkyHost::Fault& fault) noexcept {
    const auto tcb = current_tcb();
    if (!tcb) return false;
    // A site already patched (or being patched): a thread hit its int3, or
    // faulted on the old bytes just before the jump landed. Complete it from
    // the recorded load; the bytes at pc may no longer decode.
    if (sites && (fault.kind == SkyHost::FaultKind::breakpoint || fault.kind == SkyHost::FaultKind::access)) {
        AcquireSRWLockShared(&patch_lock);
        const Site* site = find_site(fault.cpu.pc);
        if (!site && fault.kind == SkyHost::FaultKind::breakpoint) site = find_site(fault.cpu.pc - 1);
        const Site copy = site ? *site : Site{};
        ReleaseSRWLockShared(&patch_lock);
        if (copy.pc) {
            std::memcpy(&fault.cpu.gpr[copy.load.destination],
                        reinterpret_cast<const void*>(tcb + static_cast<std::uint64_t>(static_cast<std::int64_t>(copy.load.displacement))), 8);
            fault.cpu.pc = copy.pc + copy.load.length;
            loads.fetch_add(1, std::memory_order_relaxed);
            return true;
        }
    }
    if (fault.kind != SkyHost::FaultKind::access) return false;
    const auto site = fault.cpu.pc;
    Load load{};
    const bool decoded = decode(reinterpret_cast<const std::uint8_t*>(site), 9, load);
    if (!emulate(fault, tcb)) return false;
    loads.fetch_add(1, std::memory_order_relaxed);
    if (decoded && !probe_tcb) {
        AcquireSRWLockExclusive(&patch_lock);
        patch_site(site, load);
        ReleaseSRWLockExclusive(&patch_lock);
    }
    return true;
}

std::uint64_t patched_sites() noexcept { return patched.load(std::memory_order_relaxed); }

std::uint64_t emulated_loads() noexcept { return loads.load(std::memory_order_relaxed); }
#else
// Linux sets the FS base per guest thread (guest_start.S); nothing to emulate.
bool install() noexcept { return true; }
#endif
}

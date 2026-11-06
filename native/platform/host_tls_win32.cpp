// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_tls.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winternl.h>

static_assert(offsetof(TEB, TlsSlots) == 0x1480);

extern "C" {
unsigned long sky_host_tls_offset = 0;
}

extern "C" SKY_SYSV_ABI SkyHost::TlsState* sky_host_tls_state() noexcept {
    // Only the first 64 slots live in TEB::TlsSlots (x64 offset 0x1480).
    // Expansion slots use a different indirection; refuse rather than reading
    // the wrong address. The successful slot belongs to the process lifetime.
    static const DWORD slot = [] {
        const DWORD allocated = TlsAlloc();
        if (allocated == TLS_OUT_OF_INDEXES) return TLS_OUT_OF_INDEXES;
        if (allocated >= 64) {
            TlsFree(allocated);
            return TLS_OUT_OF_INDEXES;
        }
        sky_host_tls_offset = 0x1480 + allocated * 8;
        return allocated;
    }();
    if (slot == TLS_OUT_OF_INDEXES) return nullptr;
    static thread_local SkyHost::TlsState state;
    if (!TlsSetValue(slot, &state)) return nullptr;
    // Check the direct lookup used by generated/assembly code against the OS
    // API before accepting a new thread. A layout mismatch cannot run a guest.
    if (reinterpret_cast<TEB*>(NtCurrentTeb())->TlsSlots[slot] != &state || TlsGetValue(slot) != &state)
        return nullptr;
    return &state;
}

extern "C" [[noreturn]] SKY_SYSV_ABI void sky_host_bridge_fatal() noexcept {
    ExitProcess(126);
}

bool SkyHost::tls_access(TlsAccess& result) noexcept {
    if (!sky_host_tls_state()) return false;
    result = {static_cast<std::int32_t>(sky_host_tls_offset), true, true};
    return true;
}

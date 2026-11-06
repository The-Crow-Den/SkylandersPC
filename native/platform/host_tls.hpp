// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../guest_abi.hpp"
#include <cstddef>
#include <cstdint>

namespace SkyHost {
// Lives on the host thread, independently of guest FS. Nested entries save and
// restore both fields. The assembly reads bridge at offset zero.
// Generated code loads guest_tcb without calling host code or changing flags.
// Windows: GS:[displacement] -> TlsState* -> guest_tcb. POSIX test path:
// FS:[displacement] -> guest_tcb, while native FS remains selected.
struct TlsAccess {
    std::int32_t displacement;
    bool indirect;
    bool use_gs;
};
bool tls_access(TlsAccess& result) noexcept;

struct TlsState {
    void* bridge = nullptr;
    void* guest_tcb = nullptr;
};
static_assert(offsetof(TlsState, bridge) == 0);
static_assert(offsetof(TlsState, guest_tcb) == 8);
}

// Called on the host stack before entry. Returns null if a directly accessible
// Windows TLS slot cannot be allocated/installed. No guest code runs on failure.
extern "C" SKY_SYSV_ABI SkyHost::TlsState* sky_host_tls_state() noexcept;
#ifdef _WIN32
// Byte offset within TEB::TlsSlots, initialized once before guest execution.
extern "C" unsigned long sky_host_tls_offset;
extern "C" [[noreturn]] SKY_SYSV_ABI void sky_host_bridge_fatal() noexcept;
#endif

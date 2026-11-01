// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_tls.hpp"
#include <asm/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <limits>

extern "C" SKY_SYSV_ABI SkyHost::TlsState* sky_host_tls_state() noexcept {
    static thread_local SkyHost::TlsState state;
    return &state;
}


bool SkyHost::tls_access(TlsAccess& result) noexcept {
    std::uintptr_t fs = 0;
    if (syscall(SYS_arch_prctl, ARCH_GET_FS, &fs)) return false;
    const auto address = reinterpret_cast<std::uintptr_t>(&sky_host_tls_state()->guest_tcb);
    // This is an opt-in host-FS test path; the Linux guest bridge still uses
    // its existing FS-switching implementation. Query while host FS is active.
    const auto delta = address >= fs ? address - fs : fs - address;
    if (delta > static_cast<std::uintptr_t>(std::numeric_limits<std::int32_t>::max())) return false;
    const auto signed_delta = static_cast<std::int32_t>(delta);
    result = {address >= fs ? signed_delta : -signed_delta, false, false};
    return true;
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_tls.hpp"

extern "C" SKY_SYSV_ABI SkyHost::TlsState* sky_host_tls_state() noexcept {
    static thread_local SkyHost::TlsState state;
    return &state;
}

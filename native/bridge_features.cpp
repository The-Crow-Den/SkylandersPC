// SPDX-License-Identifier: GPL-3.0-or-later
#include <asm/hwcap2.h>
#include <sys/auxv.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

// Called only by sky_guest_start while host FS is active. Cache policy before
// guest execution; no libc, environment access or lazy init on the import path.
extern "C" int sky_guest_fast_tls_enabled() noexcept {
    static const int enabled = [] {
        const char* mode = std::getenv("SKY_TLS_BRIDGE");
        const bool automatic = !mode || !std::strcmp(mode,"auto");
        const bool supported = (getauxval(AT_HWCAP2) & HWCAP2_FSGSBASE) != 0;
        const int use_fast = automatic && supported;
        std::printf("TLS import bridge: %s (kernel FSGSBASE %s)\n",
                    use_fast ? "direct FSBASE" : "arch_prctl fallback",
                    supported ? "available" : "unavailable");
        return use_fast;
    }();
    return enabled;
}

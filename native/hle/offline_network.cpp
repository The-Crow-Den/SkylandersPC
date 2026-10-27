// SPDX-License-Identifier: GPL-3.0-or-later
#include "offline_network.hpp"
#include <algorithm>
#include <array>
#include <stdexcept>
#include <arpa/inet.h>

namespace {
thread_local std::int32_t net_errno = 0;
constexpr std::array<std::string_view, 10> names{
    "Nlev7Lg8k3A#libSceNet#libSceNet", "cTGkc6-TBlI#libSceNet#libSceNet",
    "dgJBaeJnGpo#libSceNet#libSceNet", "K7RlrTkI-mw#libSceNet#libSceNet",
    "gky0+oaNM4k#libSceNetCtl#libSceNetCtl", "uBPlr0lbuiI#libSceNetCtl#libSceNetCtl",
    "obuxdTiwkF8#libSceNetCtl#libSceNetCtl", "8Kcp5d-q1Uo#libSceNet#libSceNet",
    "Q4qBuN-c0ZM#libSceNet#libSceNet", "HQOwnfMGipQ#libSceNet#libSceNet"};
}
bool OfflineNetwork::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
std::uint64_t OfflineNetwork::call(std::string_view identity, const std::uint64_t* a) {
    if (identity == names[9]) return reinterpret_cast<std::uintptr_t>(&net_errno);
    std::lock_guard lock(lock_);
    if (identity == names[7]) {
        if (a[0] != 2 && a[0] != 28) return ~std::uint64_t{0};
        if (!a[1] || !a[2]) return ~std::uint64_t{0};
        const auto status = inet_pton(a[0] == 2 ? AF_INET : AF_INET6,
            reinterpret_cast<const char*>(a[1]), reinterpret_cast<void*>(a[2]));
        return static_cast<std::uint64_t>(status);
    }
    if (identity == names[0]) {
        if (initialized_) return 0x80410125; // EALREADY
        initialized_ = true; return 0;
    }
    if (identity == names[4]) {
        control_initialized_ = true; return 0;
    }
    if (identity == names[5]) {
        if (!a[0]) return 0x80412107;
        if (!control_initialized_) return 0x80412101;
        *reinterpret_cast<int*>(a[0]) = 0; return 0;
    }
    if (identity == names[6]) {
        if (!a[1]) return 0x80412107;
        return control_initialized_ ? 0x80412108 : 0x80412101;
    }
    if (!initialized_) return 0x804101c8; // ENOTINIT
    if (identity == names[8]) {
        // Explicit offline failure: no host socket, no invented descriptor,
        // and no indefinitely suspended guest worker. Error ABI verified
        // against the supplied reference's NetErrorHandler and net_error.h.
        net_errno = 50; // ORBIS_NET_ENETDOWN
        return 0x80410132;
    }
    if (identity == names[1]) {
        if (!pools_.empty()) return 0x80410110;
        initialized_ = false; return 0;
    }
    if (identity == names[2]) {
        if (!a[0] || !a[1] || a[1] > 64 * 1024 * 1024 || a[2]) return 0x80410116;
        const int pool = next_pool_++;
        pools_.emplace(pool, a[1]); return static_cast<std::uint64_t>(pool);
    }
    if (identity == names[3]) return pools_.erase(static_cast<int>(a[0])) ? 0 : 0x80410116;
    throw std::runtime_error("unsupported offline network import");
}

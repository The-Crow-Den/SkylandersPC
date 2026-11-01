// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_tls.hpp"
#include <array>
#include <iostream>
#include <stdexcept>

void require(bool condition) { if (!condition) throw std::runtime_error("TLS manifest assertion failed"); }
template<class F> void rejects(F action) {
    bool rejected = false;
    try { action(); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected);
}
int main() try {
    const std::array<std::uint8_t, 10> code{0x64,0x48,0x8b,0x04,0x25,0,0,0,0,0xc3};
    const std::array<GuestTls::CodeRange, 1> ranges{{{0,0x10000,code.size()}}};
    auto manifest = GuestTls::inspect(code, ranges);
    require(manifest.sites.size() == 1 && manifest.sites[0].address == 0x10000 &&
            manifest.sites[0].expected_bytes.size() == 9 && manifest.sites[0].destination_register == 0);
    require(manifest.sites_sha256 == "cc2a546217237c77301a5eb904ab6db39ca14ea5441810dee9f5be748e705fcd");
    GuestTls::Profile profile{manifest.executable_sha256,1,manifest.sites_sha256};
    GuestTls::verify(manifest,profile);
    auto changed = code; changed.back() = 0x90;
    rejects([&] { GuestTls::verify(GuestTls::inspect(changed,ranges),profile); });
    auto wrong = profile; ++wrong.site_count;
    rejects([&] { GuestTls::verify(manifest,wrong); });
    wrong = profile; wrong.sites_sha256[0] = wrong.sites_sha256[0] == '0' ? '1' : '0';
    rejects([&] { GuestTls::verify(manifest,wrong); });
    wrong = profile; wrong.executable_sha256.clear();
    rejects([&] { GuestTls::verify(manifest,wrong); });
    auto unsupported = code; unsupported[2] = 0x89; // FS store: not implemented.
    rejects([&] { GuestTls::inspect(unsupported,ranges); });
    unsupported = code; unsupported[3] = 0x24; // MOV RSP, FS:[0].
    rejects([&] { GuestTls::inspect(unsupported,ranges); });
    auto high_register = code; high_register[1] = 0x4c; high_register[3] = 0x24;
    for (unsigned i = 5; i < 9; ++i) high_register[i] = 0xff;
    const auto high = GuestTls::inspect(high_register,ranges);
    require(high.sites[0].destination_register == 12 && high.sites[0].displacement == -1);
    const std::array<GuestTls::CodeRange, 2> reversed{{{9,0x20000,1},{0,0x10000,9}}};
    const auto ordered = GuestTls::inspect(code,reversed);
    require(ordered.sites_sha256 == manifest.sites_sha256);
    const std::array<GuestTls::CodeRange, 1> truncated{{{0,0x10000,8}}};
    rejects([&] { GuestTls::inspect(code,truncated); });
    const std::array<GuestTls::CodeRange, 2> overlap{{ranges[0],ranges[0]}};
    rejects([&] { GuestTls::inspect(code,overlap); });
    const std::array<GuestTls::CodeRange, 1> outside{{{code.size(),0x10000,1}}};
    rejects([&] { GuestTls::inspect(code,outside); });
    std::cout << "guest TLS preflight and profile refusal tests passed\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }

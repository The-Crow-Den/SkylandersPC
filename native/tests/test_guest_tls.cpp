// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_tls.hpp"
#include "platform/host_code.hpp"
#include "guest_abi.hpp"
#include "guest_start.hpp"
#include <algorithm>
#include <atomic>
#include <thread>
#include <vector>
#include <limits>
#ifndef _WIN32
#include <asm/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif
#include <array>
#include <iostream>
#include <stdexcept>

void require(bool condition) { if (!condition) throw std::runtime_error("TLS manifest assertion failed"); }
template<class F> void rejects(F action) {
    bool rejected = false;
    try { action(); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected);
}
#ifndef _WIN32
// Exercise the GS + indirect TlsState lookup on Linux too. This uses real
// arch_prctl calls on test threads, with host FS unchanged; no Windows APIs are
// substituted. Always restore the thread's original GS before leaving scope.
class GsSlot {
    void* slot_;
    std::uintptr_t previous_ = 0;
    bool enabled_;
public:
    GsSlot(void* state, bool enabled) : slot_(state), enabled_(enabled) {
        if (enabled_) {
            require(syscall(SYS_arch_prctl, ARCH_GET_GS, &previous_) == 0);
            require(syscall(SYS_arch_prctl, ARCH_SET_GS, &slot_) == 0);
        }
    }
    ~GsSlot() {
        if (enabled_ && syscall(SYS_arch_prctl, ARCH_SET_GS, previous_)) std::terminate();
    }
};
#endif

void execution_tests(bool indirect_gs = false) {
    SkyHost::TlsAccess access{};
    require(SkyHost::tls_access(access));
    const auto native_access = access;
#ifndef _WIN32
    if (indirect_gs) access = {0, true, true};
#else
    (void)indirect_gs;
#endif
    // Each function contains one original FS load. Exercise every permitted
    // destination, including high GPRs and R12's SIB encoding, and signed offsets.
    for (unsigned reg = 0; reg < 16; ++reg) {
        if (reg == 4) continue;
        const bool saved = reg == 3 || reg == 5 || reg >= 12;
        auto push = [&](std::vector<std::uint8_t>& out) {
            if (saved) { if (reg >= 8) out.push_back(0x41); out.push_back(static_cast<std::uint8_t>(0x50 + (reg & 7))); }
        };
        auto pop = [&](std::vector<std::uint8_t>& out) {
            if (saved) { if (reg >= 8) out.push_back(0x41); out.push_back(static_cast<std::uint8_t>(0x58 + (reg & 7))); }
        };
        for (const std::int32_t offset : {-8, 0, 8}) {
            std::vector<std::uint8_t> original;
            push(original);
            original.insert(original.end(), {0x31,0xc0,0xf9}); // XOR EAX,EAX; STC.
            original.insert(original.end(), {0x64,static_cast<std::uint8_t>(0x48 | (reg >= 8 ? 4 : 0)),0x8b,
                static_cast<std::uint8_t>(((reg & 7) << 3) | 4),0x25});
            for (unsigned i = 0; i < 4; ++i) original.push_back(static_cast<std::uint8_t>(static_cast<std::uint32_t>(offset) >> (i * 8)));
            // Capture flags in RCX unless it is the destination, otherwise RDX.
            const unsigned scratch = reg == 1 ? 2 : 1;
            original.insert(original.end(), {0x9c,static_cast<std::uint8_t>(0x58 + scratch),0x81,
                static_cast<std::uint8_t>(0xe0 + scratch),0xc5,0x08,0,0,0x83,
                static_cast<std::uint8_t>(0xf8 + scratch),0x45,0x75,0});
            const auto branch = original.size() - 1;
            original.insert(original.end(), {static_cast<std::uint8_t>(0x48 | (reg >= 8 ? 4 : 0)),0x89,
                static_cast<std::uint8_t>(0xc0 | ((reg & 7) << 3))});
            pop(original); original.push_back(0xc3);
            original[branch] = static_cast<std::uint8_t>(original.size() - branch - 1);
            original.insert(original.end(), {0x31,0xc0}); pop(original); original.push_back(0xc3);
            SkyHost::CodeMemory code, arena;
            require(code.allocate(65536));
            require(arena.allocate(65536, code.address()));
            require((arena.address() & 65535) == 0);
            const std::array<GuestTls::CodeRange,1> ranges{{{0,code.address(),original.size()}}};
            const auto manifest = GuestTls::inspect(original,ranges);
            const GuestTls::Profile profile{manifest.executable_sha256,manifest.sites.size(),manifest.sites_sha256};
            const auto plan = GuestTls::prepare(original,ranges,profile,arena.address(),arena.writable().size(),access);
            std::copy(original.begin(),original.end(),code.writable().begin());
            const std::array<GuestTls::WritableCode,1> mappings{{{code.writable()}}};
            GuestTls::apply(plan,mappings,arena.writable());
            require(code.seal() && arena.seal());
            require(code.writable().empty() && arena.writable().empty());
            using Function = std::uint64_t (SKY_SYSV_ABI *)();
            const auto function = reinterpret_cast<Function>(static_cast<std::uintptr_t>(code.address()));
            std::atomic<unsigned> failures = 0;
            auto run = [&](unsigned thread_index) {
                SkyHost::TlsAccess current{};
                if (!SkyHost::tls_access(current) || current.displacement != native_access.displacement ||
                    current.indirect != native_access.indirect || current.use_gs != native_access.use_gs) { ++failures; return; }
                auto* state = sky_host_tls_state();
#ifndef _WIN32
                GsSlot gs(state, indirect_gs);
#endif
                const auto previous = state->guest_tcb;
                std::array<std::uint64_t,3> tcb{1000 + thread_index,2000 + thread_index,3000 + thread_index};
                state->guest_tcb = &tcb[1];
                const auto expected = tcb[static_cast<std::size_t>(1 + offset / 8)];
                for (unsigned i = 0; i < 100; ++i) if (function() != expected) ++failures;
#ifdef _WIN32
                // Exercise the same rewritten function through the real guest
                // entry bridge, which installs/restores its own TCB in host TLS.
                std::vector<std::uint8_t> guest_stack(65536);
                std::array<std::uint64_t,3> bridge_tcb{4000 + thread_index,5000 + thread_index,6000 + thread_index};
                SkyGuestStartContext context{reinterpret_cast<void*>(static_cast<std::uintptr_t>(code.address())),
                    guest_stack.data() + guest_stack.size(), &bridge_tcb[1], nullptr, nullptr};
                std::uint64_t result = 0;
                if (sky_guest_start(&context,&result) || result != bridge_tcb[static_cast<std::size_t>(1 + offset / 8)] ||
                    state->guest_tcb != &tcb[1] || state->bridge) ++failures;
#endif
                state->guest_tcb = previous;
            };
            run(0);
            std::vector<std::thread> threads;
            for (unsigned i = 1; i <= 4; ++i) threads.emplace_back(run,i);
            for (auto& thread : threads) thread.join();
            require(failures == 0);
        }
    }
}

void address_only_tests() {
    // FS-prefixed NOP must not dereference the noncanonical RAX. LEA must
    // return the offset 42, independently of the host FS base on Linux/Windows.
    const std::vector<std::uint8_t> original{0x48,0xc7,0xc0,0xff,0xff,0xff,0xff,
        0x64,0x0f,0x1f,0x00,0x64,0x48,0x8d,0x04,0x25,42,0,0,0,0xc3};
    SkyHost::CodeMemory code;
    require(code.allocate(65536));
    const std::array<GuestTls::CodeRange,1> ranges{{{0,code.address(),original.size()}}};
    const auto manifest=GuestTls::inspect(original,ranges);
    require(manifest.sites.empty());
    std::copy(original.begin(),original.end(),code.writable().begin());
    require(code.seal());
    using Function=std::uint64_t (SKY_SYSV_ABI *)();
    require(reinterpret_cast<Function>(static_cast<std::uintptr_t>(code.address()))()==42);
}

void patch_refusal_tests() {
    SkyHost::TlsAccess access{};
    require(SkyHost::tls_access(access));
    SkyHost::CodeMemory code, arena;
    require(code.allocate(65536) && arena.allocate(65536,code.address()));
    const std::vector<std::uint8_t> original{0x64,0x48,0x8b,0x04,0x25,0,0,0,0,
                                          0x64,0x48,0x8b,0x04,0x25,0,0,0,0,0xc3};
    const std::array<GuestTls::CodeRange,1> ranges{{{0,code.address(),original.size()}}};
    const auto manifest = GuestTls::inspect(original,ranges);
    const GuestTls::Profile profile{manifest.executable_sha256,2,manifest.sites_sha256};
    rejects([&] { GuestTls::prepare(original,ranges,profile,code.address(),65536,access); });
    rejects([&] { GuestTls::prepare(original,ranges,profile,arena.address(),1,access); });
    rejects([&] { GuestTls::prepare(original,ranges,profile,code.address() + 0x100000000ULL,65536,access); });
    rejects([&] { GuestTls::prepare(original,ranges,profile,std::numeric_limits<std::uint64_t>::max() - 3,65536,access); });
    auto bad = profile; ++bad.site_count;
    rejects([&] { GuestTls::prepare(original,ranges,bad,arena.address(),65536,access); });
    const auto plan = GuestTls::prepare(original,ranges,profile,arena.address(),65536,access);
    std::copy(original.begin(),original.end(),code.writable().begin());
    code.writable()[10] ^= 1; // Corrupt only the second site: no partial writes.
    const std::vector<std::uint8_t> before(code.writable().begin(),code.writable().end());
    std::fill(arena.writable().begin(),arena.writable().end(),0xcc);
    const std::array<GuestTls::WritableCode,1> mappings{{{code.writable()}}};
    rejects([&] { GuestTls::apply(plan,mappings,arena.writable()); });
    require(std::equal(before.begin(),before.end(),code.writable().begin()));
    require(std::all_of(arena.writable().begin(),arena.writable().end(),[](auto b) {return b == 0xcc;}));
    const std::array<GuestTls::WritableCode,2> overlap{{mappings[0],mappings[0]}};
    rejects([&] { GuestTls::apply(plan,overlap,arena.writable()); });
    rejects([&] { GuestTls::apply(plan,mappings,arena.writable().subspan(1)); });
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
    patch_refusal_tests();
    address_only_tests();
    execution_tests();
#ifndef _WIN32
    execution_tests(true);
#endif
    std::cout << "guest TLS preflight, rewrite execution and refusal tests passed\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }

// SPDX-License-Identifier: GPL-3.0-or-later
#include "thread_context.hpp"
#include "guest_start.hpp"
#include "guest_tls.hpp"
#include "platform/host_code.hpp"
#include "platform/host_thread.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <vector>
#ifndef _WIN32
#include <signal.h>
#endif

namespace {
void require(bool value) { if (!value) throw std::runtime_error("thread context assertion failed"); }
thread_local unsigned callback_depth = 0;
std::uint64_t callback_entry = 0, template_entry = 0;
std::uint64_t SKY_SYSV_ABI callback_handler(std::uint64_t index, const std::uint64_t*, const std::uint64_t*) {
    // Never unwind across assembly, including on a failed assertion.
    try {
        auto* context = GuestThreadContext::current();
        require(context && index == 7);
        const auto entry = callback_depth++ ? template_entry : callback_entry;
        const auto result = context->callback(entry, nullptr);
        --callback_depth;
        return result + 1;
    } catch (...) { std::terminate(); }
}
void fault_context_test() {
    SkyHost::ThreadFaultContext outer, inner;
#ifdef _WIN32
    require(outer.mode() == SkyHost::FaultStackMode::NativeExceptionStack);
#else
    require(outer.mode() == SkyHost::FaultStackMode::AlternateSignalStack);
    stack_t before{}, during{}, restored{};
    require(sigaltstack(nullptr, &before) == 0);
#endif
    require(!outer.leave() && outer.enter() && !outer.enter());
#ifndef _WIN32
    require(sigaltstack(nullptr, &during) == 0 && !(during.ss_flags & SS_DISABLE));
#endif
    bool wrong_thread_left = true;
    std::thread other([&] { wrong_thread_left = outer.leave(); });
    other.join();
    require(!wrong_thread_left && inner.enter() && inner.leave());
#ifndef _WIN32
    require(sigaltstack(nullptr, &restored) == 0 && restored.ss_sp == during.ss_sp &&
            restored.ss_size == during.ss_size && restored.ss_flags == during.ss_flags);
#endif
    require(outer.leave() && !outer.leave());
#ifndef _WIN32
    require(sigaltstack(nullptr, &restored) == 0 && restored.ss_flags == before.ss_flags);
    if (!(before.ss_flags & SS_DISABLE))
        require(restored.ss_sp == before.ss_sp && restored.ss_size == before.ss_size);
#endif
}
}
int main() {
    fault_context_test();
    SkyHost::CodeMemory code, arena;
    require(code.allocate(65536));
    std::vector<std::uint8_t> original;
    std::vector<GuestTls::CodeRange> ranges;
    auto function = [&](std::vector<std::uint8_t> bytes) {
        const auto offset = original.size();
        original.insert(original.end(), bytes.begin(), bytes.end());
        ranges.push_back({offset, code.address() + offset, bytes.size()});
        return code.address() + offset;
    };
    auto fs_load = [&](std::int32_t offset, std::vector<std::uint8_t> suffix = {0xc3}) {
        std::vector<std::uint8_t> bytes{0x64,0x48,0x8b,0x04,0x25};
        for (unsigned i = 0; i < 4; ++i) bytes.push_back(static_cast<std::uint8_t>(static_cast<std::uint32_t>(offset) >> (8 * i)));
        bytes.insert(bytes.end(), suffix.begin(), suffix.end());
        return function(bytes);
    };
    const auto self = fs_load(0);
    template_entry = fs_load(-16);
    const auto bss = fs_load(-8);
    const auto error = fs_load(192);
    const auto secondary = fs_load(8, {0x48,0x8b,0x40,0x18,0x48,0x8b,0x40,0x08,0xc3});
    const auto stack = function({0x48,0x89,0xe0,0xc3}); // MOV RAX,RSP; RET.
    std::vector<std::uint8_t> wrapper{0x48,0x83,0xec,0x08,0x49,0xc7,0xc2,7,0,0,0,0x48,0xb8};
    const auto bridge = reinterpret_cast<std::uintptr_t>(&sky_guest_call_bridge);
    for (unsigned i = 0; i < 8; ++i) wrapper.push_back(static_cast<std::uint8_t>(bridge >> (8 * i)));
    wrapper.insert(wrapper.end(), {0xff,0xd0,0x48,0x83,0xc4,0x08,0xc3});
    callback_entry = function(wrapper);
    std::copy(original.begin(), original.end(), code.writable().begin());
#ifdef _WIN32
    // Only these fully known synthetic functions constitute this profile.
    // Real executable admission still requires independent complete evidence.
    require(arena.allocate(65536, code.address()));
    SkyHost::TlsAccess access{};
    require(SkyHost::tls_access(access));
    const auto manifest = GuestTls::inspect(original, ranges);
    require(manifest.sites.size() == 5);
    const GuestTls::Profile profile{manifest.executable_sha256, manifest.sites.size(), manifest.sites_sha256};
    const auto plan = GuestTls::prepare(original, ranges, profile, arena.address(), arena.writable().size(), access);
    const std::array<GuestTls::WritableCode,1> mappings{{{code.writable()}}};
    GuestTls::apply(plan, mappings, arena.writable());
    require(arena.seal());
#endif
    require(code.seal());
    const std::uint64_t initial = 0x123456789abcdef0;
    const std::array<std::uint64_t,2> other_initial{0x1111222233334444,0x5555666677778888};
    SkyBootPlan boot;
    boot.modules = {{1,0,reinterpret_cast<std::uintptr_t>(&initial),8,16,16},
                    {2,0,reinterpret_cast<std::uintptr_t>(other_initial.data()),16,32,16}};
    require(sky_guest_configure_call(callback_handler) == 0);
    std::atomic<unsigned> failures = 0;
    auto exercise = [&](unsigned id) {
        try {
            thread_local unsigned host_sentinel = 0;
            host_sentinel = 100 + id;
            GuestThreadContext context(boot, 65536);
            require(!GuestThreadContext::current());
            bool rejected = false;
            try { context.run(0, nullptr); } catch (const std::runtime_error&) { rejected = true; }
            require(rejected && !GuestThreadContext::current());
            require(context.run(self, nullptr) == context.handle() - 128);
            require(context.run(template_entry, nullptr) == initial);
            require(context.run(bss, nullptr) == 0);
            require(context.run(secondary, nullptr) == other_initial[1]);
            std::uint64_t zero = 1;
            std::memcpy(&zero, reinterpret_cast<const void*>(context.tls_address(2,16)), sizeof(zero));
            require(zero == 0);
            const auto changed = initial + id + 1;
            std::memcpy(reinterpret_cast<void*>(context.tls_address(1,0)), &changed, sizeof(changed));
            *context.error_pointer() = static_cast<std::int32_t>(1000 + id);
            for (unsigned i = 0; i < 20; ++i) {
                require(context.run(template_entry, nullptr) == changed);
                require(context.run(error, nullptr) == 1000 + id);
                require(context.run(callback_entry, nullptr) == changed + 2);
                const auto sp = context.run(stack, nullptr);
                require(sp < 0x80000000 && !context.is_stack_guard(sp));
                require(!GuestThreadContext::current() && host_sentinel == 100 + id);
            }
        } catch (...) { ++failures; }
    };
    exercise(0);
    std::vector<std::thread> threads;
    for (unsigned i = 1; i <= 4; ++i) threads.emplace_back(exercise, i);
    for (auto& thread : threads) thread.join();
    require(sky_guest_configure_call(nullptr) == 0 && failures == 0);
}

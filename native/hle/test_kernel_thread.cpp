// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_thread.hpp"
#include "../guest_start.hpp"
#include <array>
#include <chrono>
#include <thread>
#include <iostream>
#include <stdexcept>
#include <string>

extern "C" std::uint64_t synthetic_worker();
extern "C" std::uint64_t synthetic_exit_worker();
extern "C" std::uint64_t synthetic_callback_worker();
extern "C" std::uint64_t synthetic_nested_callback();
asm(R"(
.text
.globl synthetic_worker
synthetic_worker:
    movq %fs:-8, %rax
    addq %rdi, %rax
    movq $99, %fs:-8
    ret
.globl synthetic_exit_worker
synthetic_exit_worker:
    movq $17, %r10
    jmp sky_guest_call_bridge
.globl synthetic_callback_worker
synthetic_callback_worker:
    subq $8, %rsp
    movq $7, %rdi
    movq $18, %r10
    call sky_guest_call_bridge
    movq %rax, %rdi
    movq $19, %r10
    call sky_guest_call_bridge
    addq $8, %rsp
    ret
.globl synthetic_nested_callback
synthetic_nested_callback:
    subq $8, %rsp
    movq $19, %r10
    call sky_guest_call_bridge
    addq %fs:-8, %rax
    movq $99, %fs:-8
    addq $8, %rsp
    ret
)");
std::uint64_t exit_handler(std::uint64_t index, const std::uint64_t* arguments, const std::uint64_t*) {
    if (index == 18) return GuestThreadContext::current()->callback(
        reinterpret_cast<std::uintptr_t>(&synthetic_nested_callback), reinterpret_cast<const void*>(arguments[0]));
    if (index == 19) return arguments[0];
    if (index != 17) return 0;
    sky_guest_thread_exit(arguments[0]);
}
int main() {
    try {
        const auto check = [](bool value) { if (!value) throw std::runtime_error("guest thread contract failed"); };
        const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
        std::uint64_t template_value = 41;
        SkyBootPlan boot;
        boot.modules.push_back({1, 0, pointer(&template_value), 8, 8, 8});
        KernelThread threads;
        threads.configure(boot);
        check(sky_guest_configure_call(&exit_handler) == 0);
        const auto call = [&](const char* nid, std::array<std::uint64_t, 6> args = {}) {
            return threads.call(std::string(nid) + "#libkernel#libkernel", args.data());
        };
        check(!KernelThread::supports("nsYoNRywwNg#wrong#libkernel"));
        check(!KernelThread::supports("P41kTWUS3EI#wrong#libkernel"));
        GuestThreadContext main_context(boot);
        threads.attach_main(main_context);
        check(main_context.run(reinterpret_cast<std::uintptr_t>(&synthetic_callback_worker),nullptr) == 48);
        check(*reinterpret_cast<std::uint64_t*>(main_context.tls_address(1,0)) == 99);
        std::int32_t policy = -1;
        std::array<std::int32_t, 2> sched{-1, 12345};
        check(call("P41kTWUS3EI", {main_context.handle(), pointer(&policy), pointer(sched.data())}) == 0);
        check(policy == 1 && sched[0] == 700 && sched[1] == 12345);
        std::int32_t new_priority = 600;
        check(call("oIRFTjoILbg", {main_context.handle(), 1, pointer(&new_priority)}) == 0);
        check(call("P41kTWUS3EI", {main_context.handle(), pointer(&policy), pointer(sched.data())}) == 0);
        check(policy == 1 && sched[0] == 600 && sched[1] == 12345);
        check(call("oIRFTjoILbg", {main_context.handle(), 99, pointer(&new_priority)}) == 45);
        check(call("P41kTWUS3EI", {0, pointer(&policy), pointer(sched.data())}) == 3);
        check(call("P41kTWUS3EI", {main_context.handle(), 0, pointer(sched.data())}) == 22);
        std::uint64_t attr = 0;
        check(call("nsYoNRywwNg", {pointer(&attr)}) == 0);
        check(call("UTXzJbWhhTE", {pointer(&attr), 1}) == 0x80020016);
        check(call("UTXzJbWhhTE", {pointer(&attr), 1024 * 1024}) == 0);
        std::array<std::uint64_t, 3> handles{};
        for (std::size_t i = 0; i < 3; ++i) {
            auto entry = i == 2 ? &synthetic_exit_worker : &synthetic_worker;
            check(call("6UgtwV+0zb4", {pointer(&handles[i]), pointer(&attr),
                reinterpret_cast<std::uintptr_t>(entry), i + 1}) == 0);
            check(handles[i] && handles[i] < (1ull << 40));
        }
        check(handles[0] != handles[1]);
        check(call("62KCwEMmzcM", {pointer(&attr)}) == 0);
        for (std::size_t i = 0; i < 3; ++i) {
            std::uint64_t result = 0;
            check(call("onNY9Byn-W8", {handles[i], pointer(&result)}) == 0);
            check(result == (i == 2 ? 3 : 42 + i));
            check(call("onNY9Byn-W8", {handles[i], pointer(&result)}) == 0x80020003);
        }
        check(template_value == 41);
        // Reusing the outermost callback stack must not disturb a second callback.
        check(main_context.run(reinterpret_cast<std::uintptr_t>(&synthetic_callback_worker),nullptr) == 106);
        // Finished detached threads release their record, stack and TLS.
        const auto gone = [&](std::uint64_t handle) {
            int priority = 0;
            for (int i = 0; i < 2000; ++i) {
                if (call("1tKyG7RlMJo", {handle, pointer(&priority)}) == 0x80020003) return true;
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            return false;
        };
        std::uint64_t detached_attr = 0;
        check(call("nsYoNRywwNg", {pointer(&detached_attr)}) == 0);
        check(call("-Wreprtu0Qs", {pointer(&detached_attr), 1}) == 0);
        std::array<std::uint64_t, 32> detached{};
        for (auto& handle : detached)
            check(call("6UgtwV+0zb4", {pointer(&handle), pointer(&detached_attr),
                reinterpret_cast<std::uintptr_t>(&synthetic_worker), 1}) == 0);
        for (auto handle : detached) check(gone(handle));
        check(call("62KCwEMmzcM", {pointer(&detached_attr)}) == 0);
        std::uint64_t late = 0;
        check(call("6UgtwV+0zb4", {pointer(&late), 0, reinterpret_cast<std::uintptr_t>(&synthetic_worker), 1}) == 0);
        for (int i = 0; i < 200; ++i) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        check(call("4qGrR6eoP9Y", {late}) == 0);
        check(gone(late));
        check(sky_guest_configure_call(nullptr) == 0);
        std::cout << "guest thread creation, TLS isolation, join and explicit exit passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}

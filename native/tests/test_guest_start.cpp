// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_start.hpp"

#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <string>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "platform/host_tls.hpp"
#else
#include <asm/prctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_read_fs();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_startup();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_exit_pointer();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_clobber_saved();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_trap();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_fault();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_call();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_nested_call();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_thread_exit();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_resume();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_stack_call();
extern "C" SKY_SYSV_ABI std::uint64_t sky_synthetic_host_fault_call();
// The Windows entry test deliberately contains no guest FS accesses. A later
// load-time rewriter test must establish guest TLS semantics separately.
#ifdef _WIN32
#define SYNTHETIC_TCB_RAX "    movq $42, %rax\n"
#define SYNTHETIC_TCB_RBX "    movq $42, %rbx\n"
#define SYNTHETIC_TCB_COMPARE "    cmpq $42, %rbx\n"
#else
#define SYNTHETIC_TCB_RAX "    movq %fs:0, %rax\n"
#define SYNTHETIC_TCB_RBX "    movq %fs:0, %rbx\n"
#define SYNTHETIC_TCB_COMPARE "    cmpq %fs:0, %rbx\n"
#endif
asm(R"(
    .text
    .globl sky_synthetic_host_fault_call
sky_synthetic_host_fault_call:
    pushq %rbx
)" SYNTHETIC_TCB_RBX R"(
    movq $103, %r10
    call sky_guest_call_bridge
)" SYNTHETIC_TCB_COMPARE R"(
    jne 3f
    call sky_synthetic_call
    popq %rbx
    ret
3:  xorq %rax, %rax
    popq %rbx
    ret
    .globl sky_synthetic_read_fs
sky_synthetic_read_fs:
)" SYNTHETIC_TCB_RAX R"(
    ret
    .globl sky_synthetic_startup
sky_synthetic_startup:
    movq 0(%rdi), %rax
    addq 8(%rdi), %rax
    ret
    .globl sky_synthetic_exit_pointer
sky_synthetic_exit_pointer:
    movq %rsi, %rax
    ret
    .globl sky_synthetic_clobber_saved
sky_synthetic_clobber_saved:
    movq $1, %rbx
    movq $2, %rbp
    movq $3, %r12
    movq $4, %r13
    movq $5, %r14
    movq $6, %r15
    pxor %xmm6, %xmm6
    pxor %xmm7, %xmm7
    pxor %xmm8, %xmm8
    pxor %xmm9, %xmm9
    pxor %xmm10, %xmm10
    pxor %xmm11, %xmm11
    pxor %xmm12, %xmm12
    pxor %xmm13, %xmm13
    pxor %xmm14, %xmm14
    pxor %xmm15, %xmm15
)" SYNTHETIC_TCB_RAX R"(
    ret
    .globl sky_synthetic_trap
sky_synthetic_trap:
    movq $73, %r10
    jmp sky_guest_trap_bridge
    .globl sky_synthetic_fault
sky_synthetic_fault:
    xorq %rax, %rax
    movq 0(%rax), %rax
    ret
    .globl sky_synthetic_call
sky_synthetic_call:
    pushq %rbx
)" SYNTHETIC_TCB_RBX R"(
    movq $101, %r10
    movq $1, %rdi
    movq $2, %rsi
    movq $3, %rdx
    movq $4, %rcx
    movq $5, %r8
    movq $6, %r9
    call sky_guest_call_bridge
)" SYNTHETIC_TCB_COMPARE R"(
    je 1f
    xorq %rax, %rax
1:  popq %rbx
    ret
    .globl sky_synthetic_nested_call
sky_synthetic_nested_call:
    subq $8, %rsp
    movq $104, %r10
    call sky_guest_call_bridge
    addq $8, %rsp
    ret
    .globl sky_synthetic_thread_exit
sky_synthetic_thread_exit:
    subq $8, %rsp
    movq $105, %r10
    call sky_guest_call_bridge
    addq $8, %rsp
    xorq %rax, %rax
    ret
    .globl sky_synthetic_resume
sky_synthetic_resume:
    movq $42, (%rdi)
)" SYNTHETIC_TCB_RAX R"(
    ret
    .globl sky_synthetic_stack_call
sky_synthetic_stack_call:
    pushq %rbx
)" SYNTHETIC_TCB_RBX R"(
    subq $16, %rsp
    movq $7, 0(%rsp)
    movq $8, 8(%rsp)
    movq $102, %r10
    movq $1, %rdi
    movq $2, %rsi
    movq $3, %rdx
    movq $4, %rcx
    movq $5, %r8
    movq $6, %r9
    call sky_guest_call_bridge
    addq $16, %rsp
)" SYNTHETIC_TCB_COMPARE R"(
    je 2f
    xorq %rax, %rax
2:  popq %rbx
    ret
)");

#ifdef _WIN32
extern "C" int sky_synthetic_windows_entry(const SkyGuestStartContext*, std::uint64_t*) noexcept;
extern "C" int sky_synthetic_windows_register_probe(const SkyGuestStartContext*, std::uint64_t*);
asm(R"(
    .text
    .globl sky_synthetic_windows_register_probe
sky_synthetic_windows_register_probe:
    pushq %rdi
    pushq %rsi
    subq $200, %rsp
    movdqu %xmm6, 32(%rsp)
    movdqu %xmm7, 48(%rsp)
    movdqu %xmm8, 64(%rsp)
    movdqu %xmm9, 80(%rsp)
    movdqu %xmm10, 96(%rsp)
    movdqu %xmm11, 112(%rsp)
    movdqu %xmm12, 128(%rsp)
    movdqu %xmm13, 144(%rsp)
    movdqu %xmm14, 160(%rsp)
    movdqu %xmm15, 176(%rsp)
    movq $123, %rdi
    movq $456, %rsi
    pcmpeqd %xmm6, %xmm6
    pcmpeqd %xmm7, %xmm7
    pcmpeqd %xmm8, %xmm8
    pcmpeqd %xmm9, %xmm9
    pcmpeqd %xmm10, %xmm10
    pcmpeqd %xmm11, %xmm11
    pcmpeqd %xmm12, %xmm12
    pcmpeqd %xmm13, %xmm13
    pcmpeqd %xmm14, %xmm14
    pcmpeqd %xmm15, %xmm15
    call sky_synthetic_windows_entry
    movl %eax, %r10d
    cmpq $123, %rdi
    jne 4f
    cmpq $456, %rsi
    jne 4f
    pmovmskb %xmm6, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm7, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm8, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm9, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm10, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm11, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm12, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm13, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm14, %eax
    cmpl $65535, %eax
    jne 4f
    pmovmskb %xmm15, %eax
    cmpl $65535, %eax
    jne 4f
    movl %r10d, %eax
    jmp 5f
4:  movl $1, %eax
5:
    movdqu 32(%rsp), %xmm6
    movdqu 48(%rsp), %xmm7
    movdqu 64(%rsp), %xmm8
    movdqu 80(%rsp), %xmm9
    movdqu 96(%rsp), %xmm10
    movdqu 112(%rsp), %xmm11
    movdqu 128(%rsp), %xmm12
    movdqu 144(%rsp), %xmm13
    movdqu 160(%rsp), %xmm14
    movdqu 176(%rsp), %xmm15
    addq $200, %rsp
    popq %rsi
    popq %rdi
    ret
)");
#endif

namespace {
std::uint64_t twelve_integer_arguments(std::uint64_t a, std::uint64_t b, std::uint64_t c, std::uint64_t d,
    std::uint64_t e, std::uint64_t f, std::uint64_t g, std::uint64_t h, std::uint64_t i,
    std::uint64_t j, std::uint64_t k, std::uint64_t l) {
    const std::array<std::uint64_t, 12> values{a,b,c,d,e,f,g,h,i,j,k,l};
    std::uint64_t result = 0;
    for (std::size_t index = 0; index < values.size(); ++index) result += (index + 1) * values[index];
    return result;
}
SKY_SYSV_ABI std::uint64_t twelve_sysv_arguments(std::uint64_t a, std::uint64_t b, std::uint64_t c, std::uint64_t d,
    std::uint64_t e, std::uint64_t f, std::uint64_t g, std::uint64_t h, std::uint64_t i,
    std::uint64_t j, std::uint64_t k, std::uint64_t l) {
    return twelve_integer_arguments(a,b,c,d,e,f,g,h,i,j,k,l);
}
SKY_SYSV_ABI std::uint64_t sysv_pointer_arguments(std::uint64_t a, std::uint64_t b, std::uint64_t c, std::uint64_t d,
    std::uint64_t e, std::uint64_t f, std::uint64_t g, std::uint64_t h, std::uint64_t i,
    std::uint64_t j, std::uint64_t k, std::uint64_t* output) {
    *output = twelve_integer_arguments(a,b,c,d,e,f,g,h,i,j,k,12);
    return 0xfeedface12345678ULL;
}
#ifndef _WIN32
int trap_pipe = -1;
#endif
thread_local std::uintptr_t expected_host_fs = 0;
#ifndef _WIN32
void* resume_page = nullptr;
#endif

std::uintptr_t fs_base();
std::uintptr_t gs_base();
std::uint64_t run_nested_probe();

SKY_SYSV_ABI std::uint64_t synthetic_call_handler(std::uint64_t index, const std::uint64_t* arguments, const std::uint64_t* stacked) {
    // Larger than the entire 64 KiB guest stack: HLE must use the native stack.
    volatile unsigned char native_scratch[128 * 1024];
    native_scratch[0] = 17; native_scratch[sizeof(native_scratch) - 1] = 29;
    if (native_scratch[0] != 17 || native_scratch[sizeof(native_scratch) - 1] != 29) return 0;
    if (fs_base() != expected_host_fs || (index < 101 || index > 105))
        return 0;
    if (sky_guest_configure_call(nullptr) != -16) return 0;
#ifdef _WIN32
    auto* tls = sky_host_tls_state();
    if (!tls || !tls->bridge || !tls->guest_tcb ||
        *static_cast<const std::uintptr_t*>(tls->guest_tcb) != reinterpret_cast<std::uintptr_t>(tls->guest_tcb))
        return 0;
#endif
    if (index == 104) return run_nested_probe();
    if (index == 105) sky_guest_thread_exit(93);
#ifndef _WIN32
    if (index == 103) {
        *static_cast<volatile std::uint64_t*>(resume_page) = 84;
        return 42;
    }
#endif
    std::vector<std::uint64_t> values(arguments, arguments + 6);
    std::uint64_t sum = 0;
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (values[i] != i + 1) return 0;
        sum += values[i];
    }
    if (index == 102) {
        if (stacked[0] != 7 || stacked[1] != 8) return 0;
        sum += stacked[0] + stacked[1];
    }
    return sum * 2;
}

#ifndef _WIN32
SKY_SYSV_ABI void synthetic_trap_handler(std::uint64_t index) {
    std::uintptr_t current_fs = 0;
    const bool fs_ok = syscall(SYS_arch_prctl, ARCH_GET_FS, &current_fs) == 0 && current_fs == expected_host_fs;
    const std::array<std::uint64_t, 3> report{index, fs_ok ? 1u : 0u,
        sky_guest_configure_trap(nullptr) == -16 ? 1u : 0u};
    const auto count = write(trap_pipe, report.data(), sizeof(report));
    _exit(count == static_cast<ssize_t>(sizeof(report)) ? 20 : 21);
}

SKY_SYSV_ABI int synthetic_fault_handler(int signal, void* raw_info, void* context) {
    std::uintptr_t current_fs = 0;
    const bool fs_ok = syscall(SYS_arch_prctl, ARCH_GET_FS, &current_fs) == 0 && current_fs == expected_host_fs;
    const auto* info = static_cast<siginfo_t*>(raw_info);
    if (resume_page && info->si_addr == resume_page) {
        if (!fs_ok || mprotect(resume_page, static_cast<std::size_t>(sysconf(_SC_PAGESIZE)), PROT_READ | PROT_WRITE)) _exit(25);
        return 1;
    }
    const std::array<std::uint64_t, 4> report{static_cast<std::uint64_t>(signal), fs_ok ? 1u : 0u,
                                             info && info->si_addr == nullptr ? 1u : 0u, context ? 1u : 0u};
    const auto count = write(trap_pipe, report.data(), sizeof(report));
    _exit(count == static_cast<ssize_t>(sizeof(report)) ? 23 : 24);
}

#endif

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::uintptr_t fs_base() {
#ifdef _WIN32
    // Windows host TLS is based on GS (TEB). Neither segment base may change.
    return reinterpret_cast<std::uintptr_t>(NtCurrentTeb());
#else
    std::uintptr_t result = 0;
    require(syscall(SYS_arch_prctl, ARCH_GET_FS, &result) == 0, "cannot read host FS");
    return result;
#endif
}

std::uintptr_t gs_base() {
#ifdef _WIN32
    return reinterpret_cast<std::uintptr_t>(NtCurrentTeb());
#else
    std::uintptr_t result = 0;
    require(syscall(SYS_arch_prctl, ARCH_GET_GS, &result) == 0, "cannot read host GS");
    return result;
#endif
}

class Stack {
#ifdef _WIN32
    void* mapping_ = nullptr;
#else
    void* mapping_ = MAP_FAILED;
#endif
    std::size_t size_{};
public:
    void* top = nullptr;
    Stack() {
#ifdef _WIN32
        SYSTEM_INFO info{};
        GetSystemInfo(&info);
        const auto raw_page = info.dwPageSize;
#else
        const auto raw_page = sysconf(_SC_PAGESIZE);
#endif
        require(raw_page > 0, "cannot query page size");
        const auto page = static_cast<std::size_t>(raw_page);
        constexpr std::size_t usable = 64 * 1024;
        size_ = usable + 2 * page;
#ifdef _WIN32
        mapping_ = VirtualAlloc(nullptr, size_, MEM_RESERVE, PAGE_NOACCESS);
        require(mapping_ != nullptr, "cannot reserve synthetic stack");
        auto* start = static_cast<unsigned char*>(mapping_) + page;
        require(VirtualAlloc(start, usable, MEM_COMMIT, PAGE_READWRITE) == start,
                "cannot commit synthetic stack");
#else
        mapping_ = mmap(nullptr, size_, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        require(mapping_ != MAP_FAILED, "cannot map synthetic stack");
        auto* start = static_cast<unsigned char*>(mapping_) + page;
        require(mprotect(start, usable, PROT_READ | PROT_WRITE) == 0, "cannot protect synthetic stack");
#endif
        top = start + usable;
    }
    Stack(const Stack&) = delete;
    Stack& operator=(const Stack&) = delete;
    ~Stack() {
#ifdef _WIN32
        if (mapping_) VirtualFree(mapping_, 0, MEM_RELEASE);
#else
        if (mapping_ != MAP_FAILED) munmap(mapping_, size_);
#endif
    }
};

std::uint64_t run_nested_probe() try {
    Stack nested_stack;
    std::array<std::uintptr_t, 8> nested_tcb{};
    nested_tcb[0] = reinterpret_cast<std::uintptr_t>(nested_tcb.data());
    SkyGuestStartContext nested{reinterpret_cast<void*>(&sky_synthetic_stack_call),
                               nested_stack.top, nested_tcb.data(), nullptr, nullptr};
#ifdef _WIN32
    auto* tls = sky_host_tls_state();
    require(tls && tls->bridge && tls->guest_tcb, "outer TLS state missing");
    const auto saved = *tls;
#endif
    std::uint64_t result = 0;
    require(sky_guest_start(&nested, &result) == 0 && result == 72, "nested import failed");
#ifdef _WIN32
    require(tls->bridge == saved.bridge && tls->guest_tcb == saved.guest_tcb,
            "nested entry did not restore outer TLS state");
#endif
    return result;
} catch (...) {
    // Never unwind across the assembly boundary.
    return 0;
}

void run_probes() {
    Stack stack;
    alignas(64) std::array<std::uintptr_t, 8> tcb{};
    tcb[0] = reinterpret_cast<std::uintptr_t>(tcb.data());
#ifdef _WIN32
    const std::uint64_t guest_result = 42;
#else
    const std::uint64_t guest_result = tcb[0];
#endif
    const auto host_fs = fs_base();
    const auto host_gs = gs_base();
    std::array<std::uint64_t, 2> startup{7, 35};
    SkyGuestStartContext context{reinterpret_cast<void*>(&sky_synthetic_read_fs), stack.top,
                                tcb.data(), startup.data(), reinterpret_cast<void*>(&sky_synthetic_read_fs)};
    std::uint64_t returned = 0;
    for (unsigned i = 0; i < 100; ++i) {
        require(sky_guest_start(&context, &returned) == 0, "FS probe entry failed");
        require(returned == guest_result, "guest TLS/constant entry result mismatch");
        require(fs_base() == host_fs, "host FS was not restored");
        require(gs_base() == host_gs, "host GS was not restored");
    }
    context.entry = reinterpret_cast<void*>(&sky_synthetic_startup);
    require(sky_guest_start(&context, &returned) == 0 && returned == 42, "startup block RDI was not passed");
    context.entry = reinterpret_cast<void*>(&sky_synthetic_exit_pointer);
    require(sky_guest_start(&context, &returned) == 0 && returned == reinterpret_cast<std::uintptr_t>(context.exit_callback),
            "exit callback RSI was not passed");
    context.entry = reinterpret_cast<void*>(&sky_synthetic_clobber_saved);
#ifdef _WIN32
    require(sky_synthetic_windows_register_probe(&context, &returned) == 0 && returned == guest_result,
            "Win64 nonvolatile GPR/vector registers were not preserved");
#else
    require(sky_guest_start(&context, &returned) == 0 && returned == guest_result, "host frame depends on guest saved registers");
#endif
    require(fs_base() == host_fs, "host FS changed after register-clobber probe");
    context.entry = nullptr;
    returned = 123;
    require(sky_guest_start(&context, &returned) == -22 && returned == 123, "invalid context was not rejected");
    require(sky_guest_start(nullptr, &returned) == -22, "null context was not rejected");
    require(sky_guest_start(&context, nullptr) == -22, "null result was not rejected");
    context.entry = reinterpret_cast<void*>(&sky_synthetic_read_fs);
    auto invalid = context;
    invalid.tcb = nullptr;
    require(sky_guest_start(&invalid, &returned) == -22 && returned == 123, "null TCB was not rejected");
    invalid = context;
    invalid.stack_top = reinterpret_cast<void*>(31);
    require(sky_guest_start(&invalid, &returned) == -22 && returned == 123, "invalid stack was not rejected");
    context.entry = reinterpret_cast<void*>(&sky_synthetic_read_fs);
#ifndef _WIN32
    context.tcb = reinterpret_cast<void*>(~std::uintptr_t{0});
    require(sky_guest_start(&context, &returned) < 0 && returned == 123, "kernel FS rejection was not propagated");
    require(fs_base() == host_fs, "host FS changed after rejected probe");
#else
    auto* tls = sky_host_tls_state();
    require(tls && !tls->bridge && !tls->guest_tcb, "entry leaked host TLS state");
#endif
}

#ifndef _WIN32
void run_trap_probe() {
    std::array<int, 2> descriptors{};
    require(pipe(descriptors.data()) == 0, "cannot create trap report pipe");
    const auto child = fork();
    require(child >= 0, "cannot fork trap probe");
    if (child == 0) {
        close(descriptors[0]);
        trap_pipe = descriptors[1];
        expected_host_fs = fs_base();
        require(sky_guest_configure_trap(&synthetic_trap_handler) == 0, "cannot configure trap");
        Stack stack;
        alignas(64) std::array<std::uintptr_t, 8> tcb{};
        tcb[0] = reinterpret_cast<std::uintptr_t>(tcb.data());
        SkyGuestStartContext context{reinterpret_cast<void*>(&sky_synthetic_trap), stack.top,
                                    tcb.data(), nullptr, nullptr};
        std::uint64_t ignored = 0;
        (void)sky_guest_start(&context, &ignored);
        _exit(22);
    }
    close(descriptors[1]);
    std::array<std::uint64_t, 3> report{};
    const auto count = read(descriptors[0], report.data(), sizeof(report));
    close(descriptors[0]);
    int status = 0;
    require(waitpid(child, &status, 0) == child, "cannot reap trap probe");
    require(WIFEXITED(status) && WEXITSTATUS(status) == 20, "trap did not stop in host handler");
    require(count == static_cast<ssize_t>(sizeof(report)) && report[0] == 73 && report[1] == 1 && report[2] == 1,
            "trap index, restored FS or active-context guard failed");
}

#endif

void run_call_probe() {
    require(sky_guest_configure_call(&synthetic_call_handler) == 0, "cannot configure returning call");
    std::atomic<unsigned> failures = 0;
    const auto run = [&] {
        try {
            Stack stack;
            alignas(64) std::array<std::uintptr_t, 8> tcb{};
            tcb[0] = reinterpret_cast<std::uintptr_t>(tcb.data());
            expected_host_fs = fs_base();
            const auto host_gs = gs_base();
            SkyGuestStartContext context{reinterpret_cast<void*>(&sky_synthetic_call), stack.top,
                                        tcb.data(), nullptr, nullptr};
            for (unsigned i = 0; i < 100; ++i) {
                context.entry = i % 2 ? reinterpret_cast<void*>(&sky_synthetic_stack_call) : reinterpret_cast<void*>(&sky_synthetic_call);
                std::uint64_t result = 0;
                require(sky_guest_start(&context, &result) == 0 && result == (i % 2 ? 72 : 42),
                        "returning call arguments, host FS or resumed guest FS failed");
                require(fs_base() == expected_host_fs && gs_base() == host_gs,
                        "host FS/GS changed after returning call");
            }
            context.entry = reinterpret_cast<void*>(&sky_synthetic_nested_call);
            std::uint64_t result = 0;
            require(sky_guest_start(&context, &result) == 0 && result == 72,
                    "nested callback did not resume its outer import");
            context.entry = reinterpret_cast<void*>(&sky_synthetic_thread_exit);
            require(sky_guest_start(&context, &result) == 0 && result == 93,
                    "thread-exit import did not complete entry");
#ifdef _WIN32
            auto* tls = sky_host_tls_state();
            require(tls && !tls->bridge && !tls->guest_tcb, "thread exit leaked TLS state");
#endif
        } catch (...) { ++failures; }
    };
    std::vector<std::thread> threads;
    for (unsigned i = 0; i < 4; ++i) threads.emplace_back(run);
    for (auto& thread : threads) thread.join();
    require(sky_guest_configure_call(nullptr) == 0, "cannot disable returning call");
    require(failures == 0, "concurrent returning service calls leaked thread context");
}

#ifndef _WIN32
void run_fault_probe() {
    std::array<int, 2> descriptors{};
    require(pipe(descriptors.data()) == 0, "cannot create fault report pipe");
    const auto child = fork();
    require(child >= 0, "cannot fork fault probe");
    if (child == 0) {
        close(descriptors[0]);
        trap_pipe = descriptors[1];
        expected_host_fs = fs_base();
        std::vector<unsigned char> signal_stack(65536);
        stack_t alternate{};
        alternate.ss_sp = signal_stack.data();
        alternate.ss_size = signal_stack.size();
        require(sigaltstack(&alternate, nullptr) == 0, "cannot configure alternate signal stack");
        struct sigaction action{};
        action.sa_sigaction = &sky_guest_fault_bridge;
        action.sa_flags = SA_SIGINFO | SA_ONSTACK;
        sigemptyset(&action.sa_mask);
        require(sigaction(SIGSEGV, &action, nullptr) == 0, "cannot install fault bridge");
        require(sky_guest_configure_fault(&synthetic_fault_handler) == 0, "cannot configure fault handler");
        Stack stack;
        alignas(64) std::array<std::uintptr_t, 8> tcb{};
        tcb[0] = reinterpret_cast<std::uintptr_t>(tcb.data());
        SkyGuestStartContext context{reinterpret_cast<void*>(&sky_synthetic_fault), stack.top,
                                    tcb.data(), nullptr, nullptr};
        std::uint64_t ignored = 0;
        resume_page = mmap(nullptr, 4096, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        require(resume_page != MAP_FAILED, "cannot create resumption page");
        auto resumable = context;
        resumable.entry = reinterpret_cast<void*>(&sky_synthetic_resume);
        resumable.startup_block = resume_page;
        require(sky_guest_start(&resumable, &ignored) == 0 && ignored == tcb[0] &&
                *static_cast<std::uint64_t*>(resume_page) == 42 && fs_base() == expected_host_fs,
                "fault resumption lost guest state or host FS");
        require(mprotect(resume_page,4096,PROT_READ)==0, "cannot protect host service fault page");
        require(sky_guest_configure_call(&synthetic_call_handler)==0, "cannot configure host fault import");
        resumable.entry=reinterpret_cast<void*>(&sky_synthetic_host_fault_call);
        require(sky_guest_start(&resumable,&ignored)==0 && ignored==42 &&
                *static_cast<std::uint64_t*>(resume_page)==84 && fs_base()==expected_host_fs,
                "host-service signal resumption or subsequent import lost TLS");
        require(sky_guest_configure_call(nullptr)==0, "cannot clear host fault import");
        munmap(resume_page, 4096); resume_page = nullptr;
        (void)sky_guest_start(&context, &ignored);
        _exit(25);
    }
    close(descriptors[1]);
    std::array<std::uint64_t, 4> report{};
    const auto count = read(descriptors[0], report.data(), sizeof(report));
    close(descriptors[0]);
    int status = 0;
    require(waitpid(child, &status, 0) == child, "cannot reap fault probe");
    require(WIFEXITED(status) && WEXITSTATUS(status) == 23, "fault did not stop in host handler");
    require(count == static_cast<ssize_t>(sizeof(report)) && report[0] == SIGSEGV &&
            report[1] == 1 && report[2] == 1 && report[3] == 1,
            "fault arguments or restored host FS were incorrect");
}
#else
SKY_SYSV_ABI void synthetic_trap_handler(std::uint64_t index) {
    auto* tls = sky_host_tls_state();
    ExitProcess(index == 73 && fs_base() == expected_host_fs && tls && tls->bridge && tls->guest_tcb &&
                sky_guest_configure_trap(nullptr) == -16 ? 20 : 21);
}

SKY_SYSV_ABI void returning_trap_handler(std::uint64_t) {}

int run_child(const char* mode) {
    expected_host_fs = fs_base();
    if (!std::strcmp(mode, "--no-context")) sky_guest_trap_bridge();
    if (!std::strcmp(mode, "--trap")) {
        require(sky_guest_configure_trap(&synthetic_trap_handler) == 0, "cannot configure Windows trap");
    } else if (!std::strcmp(mode, "--trap-return")) {
        require(sky_guest_configure_trap(&returning_trap_handler) == 0, "cannot configure returning trap");
    }
    Stack stack;
    std::array<std::uintptr_t, 8> tcb{};
    SkyGuestStartContext context{reinterpret_cast<void*>(&sky_synthetic_trap), stack.top,
                                tcb.data(), nullptr, nullptr};
    if (!std::strcmp(mode, "--missing-call")) context.entry = reinterpret_cast<void*>(&sky_synthetic_call);
    std::vector<DWORD> occupied_slots;
    if (!std::strcmp(mode, "--tls-exhausted")) {
        // Run in a fresh process, before the bridge allocates its process slot.
        for (;;) {
            const DWORD slot = TlsAlloc();
            require(slot != TLS_OUT_OF_INDEXES, "cannot occupy TLS slots");
            occupied_slots.push_back(slot);
            if (slot >= 64) break;
        }
    }
    std::uint64_t result = 123;
    const auto status = sky_guest_start(&context, &result);
    for (const auto slot : occupied_slots) require(TlsFree(slot), "cannot release test TLS slot");
    require(!std::strcmp(mode, "--tls-exhausted") && status == -12 && result == 123 &&
            fs_base() == expected_host_fs, "fatal guest returned or TLS allocation failure was not propagated");
    return 0;
}

void run_windows_process_probe(const wchar_t* mode, DWORD expected_status) {
    std::wstring executable(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, executable.data(), static_cast<DWORD>(executable.size()));
    require(length && length < executable.size(), "cannot locate synthetic test executable");
    executable.resize(length);
    std::wstring command = L"\"" + executable + L"\" " + mode;
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    require(CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, FALSE, 0,
                           nullptr, nullptr, &startup, &process), "cannot start synthetic child");
    CloseHandle(process.hThread);
    const auto waited = WaitForSingleObject(process.hProcess, 10000);
    if (waited != WAIT_OBJECT_0) {
        TerminateProcess(process.hProcess, 99);
        WaitForSingleObject(process.hProcess, 10000);
        CloseHandle(process.hProcess);
        require(false, "synthetic child timed out");
    }
    DWORD status = 0;
    const bool read = GetExitCodeProcess(process.hProcess, &status);
    CloseHandle(process.hProcess);
    require(read && status == expected_status, "Windows trap termination or TLS failure test failed");
}
#endif
} // namespace

#ifdef _WIN32
// Keep a real native-ABI compiler-generated call boundary between the assembly
// canary probe and the SysV bridge declaration.
extern "C" int sky_synthetic_windows_entry(const SkyGuestStartContext* context, std::uint64_t* result) noexcept {
    return sky_guest_start(context, result);
}
#endif

int main(int argc, char** argv) {
    try {
#ifdef _WIN32
        if (argc == 2) return run_child(argv[1]);
#else
        (void)argc;
        (void)argv;
#endif
        const std::array<std::uint64_t, 12> arguments{1,2,3,4,5,6,7,8,9,10,11,12};
        require(sky_host_call_integer(reinterpret_cast<void*>(&twelve_integer_arguments), arguments.data()) == 650,
                "host call lost register or stack arguments");
        require(sky_sysv_call_integer(reinterpret_cast<void*>(&twelve_sysv_arguments),arguments.data()) == 650,
                "SysV provider call lost register or stack arguments");
        auto pointer_arguments = arguments;
        std::uint64_t stored = 0;
        pointer_arguments[11] = reinterpret_cast<std::uintptr_t>(&stored);
        require(sky_sysv_call_integer(reinterpret_cast<void*>(&sysv_pointer_arguments),pointer_arguments.data()) == 0xfeedface12345678ULL &&
                stored == 650,"SysV provider call lost its stack pointer or full-width result");
        run_probes();
#ifndef _WIN32
        run_trap_probe();
        run_fault_probe();
#else
        run_windows_process_probe(L"--trap", 20);
        run_windows_process_probe(L"--trap-return", 126);
        run_windows_process_probe(L"--missing-call", 126);
        run_windows_process_probe(L"--no-context", 126);
        run_windows_process_probe(L"--tls-exhausted", 0);
#endif
        run_call_probe();
        std::atomic<unsigned> failures = 0;
        std::vector<std::thread> threads;
        for (unsigned i = 0; i < 4; ++i) threads.emplace_back([&] {
            try { run_probes(); } catch (...) { ++failures; }
        });
        for (auto& thread : threads) thread.join();
        require(failures.load() == 0, "per-thread FS/stack isolation failed");
        std::cout << "synthetic guest entry, startup ABI, imports and thread tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

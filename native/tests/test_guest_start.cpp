// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_start.hpp"

#include <array>
#include <atomic>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

#include <asm/prctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

extern "C" std::uint64_t sky_synthetic_read_fs();
extern "C" std::uint64_t sky_synthetic_startup();
extern "C" std::uint64_t sky_synthetic_exit_pointer();
extern "C" std::uint64_t sky_synthetic_clobber_saved();
extern "C" std::uint64_t sky_synthetic_trap();
extern "C" std::uint64_t sky_synthetic_fault();
extern "C" std::uint64_t sky_synthetic_call();
extern "C" std::uint64_t sky_synthetic_resume();
extern "C" std::uint64_t sky_synthetic_stack_call();
extern "C" std::uint64_t sky_synthetic_host_fault_call();
asm(R"(
    .text
    .globl sky_synthetic_host_fault_call
sky_synthetic_host_fault_call:
    pushq %rbx
    movq %fs:0, %rbx
    movq $103, %r10
    call sky_guest_call_bridge
    cmpq %fs:0, %rbx
    jne 3f
    call sky_synthetic_call
    popq %rbx
    ret
3:  xorq %rax, %rax
    popq %rbx
    ret
    .globl sky_synthetic_read_fs
sky_synthetic_read_fs:
    movq %fs:0, %rax
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
    movq %fs:0, %rax
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
    movq %fs:0, %rbx
    movq $101, %r10
    movq $1, %rdi
    movq $2, %rsi
    movq $3, %rdx
    movq $4, %rcx
    movq $5, %r8
    movq $6, %r9
    call sky_guest_call_bridge
    cmpq %fs:0, %rbx
    je 1f
    xorq %rax, %rax
1:  popq %rbx
    ret
    .globl sky_synthetic_resume
sky_synthetic_resume:
    movq $42, (%rdi)
    movq %fs:0, %rax
    ret
    .globl sky_synthetic_stack_call
sky_synthetic_stack_call:
    pushq %rbx
    movq %fs:0, %rbx
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
    cmpq %fs:0, %rbx
    je 2f
    xorq %rax, %rax
2:  popq %rbx
    ret
)");

namespace {
std::uint64_t twelve_integer_arguments(std::uint64_t a, std::uint64_t b, std::uint64_t c, std::uint64_t d,
    std::uint64_t e, std::uint64_t f, std::uint64_t g, std::uint64_t h, std::uint64_t i,
    std::uint64_t j, std::uint64_t k, std::uint64_t l) {
    const std::array<std::uint64_t, 12> values{a,b,c,d,e,f,g,h,i,j,k,l};
    std::uint64_t result = 0;
    for (std::size_t index = 0; index < values.size(); ++index) result += (index + 1) * values[index];
    return result;
}
int trap_pipe = -1;
thread_local std::uintptr_t expected_host_fs = 0;
void* resume_page = nullptr;

std::uint64_t synthetic_call_handler(std::uint64_t index, const std::uint64_t* arguments, const std::uint64_t* stacked) {
    // Larger than the entire 64 KiB guest stack: HLE must use the native stack.
    volatile unsigned char native_scratch[128 * 1024];
    native_scratch[0] = 17; native_scratch[sizeof(native_scratch) - 1] = 29;
    if (native_scratch[0] != 17 || native_scratch[sizeof(native_scratch) - 1] != 29) return 0;
    std::uintptr_t current_fs = 0;
    if (syscall(SYS_arch_prctl, ARCH_GET_FS, &current_fs) || current_fs != expected_host_fs || (index != 101 && index != 102 && index != 103))
        return 0;
    if (sky_guest_configure_call(nullptr) != -16) return 0;
    if (index == 103) {
        *static_cast<volatile std::uint64_t*>(resume_page) = 84;
        return 42;
    }
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

void synthetic_trap_handler(std::uint64_t index) {
    std::uintptr_t current_fs = 0;
    const bool fs_ok = syscall(SYS_arch_prctl, ARCH_GET_FS, &current_fs) == 0 && current_fs == expected_host_fs;
    const std::array<std::uint64_t, 3> report{index, fs_ok ? 1u : 0u,
        sky_guest_configure_trap(nullptr) == -16 ? 1u : 0u};
    const auto count = write(trap_pipe, report.data(), sizeof(report));
    _exit(count == static_cast<ssize_t>(sizeof(report)) ? 20 : 21);
}

int synthetic_fault_handler(int signal, void* raw_info, void* context) {
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

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::uintptr_t fs_base() {
    std::uintptr_t result = 0;
    require(syscall(SYS_arch_prctl, ARCH_GET_FS, &result) == 0, "cannot read host FS");
    return result;
}

std::uintptr_t gs_base() {
    std::uintptr_t result = 0;
    require(syscall(SYS_arch_prctl, ARCH_GET_GS, &result) == 0, "cannot read host GS");
    return result;
}

class Stack {
    void* mapping_ = MAP_FAILED;
    std::size_t size_{};
public:
    void* top = nullptr;
    Stack() {
        const auto raw_page = sysconf(_SC_PAGESIZE);
        require(raw_page > 0, "cannot query page size");
        const auto page = static_cast<std::size_t>(raw_page);
        constexpr std::size_t usable = 64 * 1024;
        size_ = usable + 2 * page;
        mapping_ = mmap(nullptr, size_, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        require(mapping_ != MAP_FAILED, "cannot map synthetic stack");
        auto* start = static_cast<unsigned char*>(mapping_) + page;
        require(mprotect(start, usable, PROT_READ | PROT_WRITE) == 0, "cannot protect synthetic stack");
        top = start + usable;
    }
    Stack(const Stack&) = delete;
    Stack& operator=(const Stack&) = delete;
    ~Stack() { if (mapping_ != MAP_FAILED) munmap(mapping_, size_); }
};

void run_probes() {
    Stack stack;
    alignas(64) std::array<std::uintptr_t, 8> tcb{};
    tcb[0] = reinterpret_cast<std::uintptr_t>(tcb.data());
    const auto host_fs = fs_base();
    const auto host_gs = gs_base();
    std::array<std::uint64_t, 2> startup{7, 35};
    SkyGuestStartContext context{reinterpret_cast<void*>(&sky_synthetic_read_fs), stack.top,
                                tcb.data(), startup.data(), reinterpret_cast<void*>(&sky_synthetic_read_fs)};
    std::uint64_t returned = 0;
    for (unsigned i = 0; i < 100; ++i) {
        require(sky_guest_start(&context, &returned) == 0, "FS probe entry failed");
        require(returned == tcb[0], "guest did not observe supplied FS:0");
        require(fs_base() == host_fs, "host FS was not restored");
        require(gs_base() == host_gs, "host GS was not restored");
    }
    context.entry = reinterpret_cast<void*>(&sky_synthetic_startup);
    require(sky_guest_start(&context, &returned) == 0 && returned == 42, "startup block RDI was not passed");
    context.entry = reinterpret_cast<void*>(&sky_synthetic_exit_pointer);
    require(sky_guest_start(&context, &returned) == 0 && returned == reinterpret_cast<std::uintptr_t>(context.exit_callback),
            "exit callback RSI was not passed");
    context.entry = reinterpret_cast<void*>(&sky_synthetic_clobber_saved);
    require(sky_guest_start(&context, &returned) == 0 && returned == tcb[0], "host frame depends on guest saved registers");
    require(fs_base() == host_fs, "host FS changed after register-clobber probe");
    context.entry = nullptr;
    returned = 123;
    require(sky_guest_start(&context, &returned) == -22 && returned == 123, "invalid context was not rejected");
    require(sky_guest_start(nullptr, &returned) == -22, "null context was not rejected");
    require(sky_guest_start(&context, nullptr) == -22, "null result was not rejected");
    context.entry = reinterpret_cast<void*>(&sky_synthetic_read_fs);
    context.tcb = reinterpret_cast<void*>(~std::uintptr_t{0});
    require(sky_guest_start(&context, &returned) < 0 && returned == 123, "kernel FS rejection was not propagated");
    require(fs_base() == host_fs, "host FS changed after rejected probe");
}

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
        } catch (...) { ++failures; }
    };
    std::vector<std::thread> threads;
    for (unsigned i = 0; i < 4; ++i) threads.emplace_back(run);
    for (auto& thread : threads) thread.join();
    require(sky_guest_configure_call(nullptr) == 0, "cannot disable returning call");
    require(failures == 0, "concurrent returning service calls leaked thread context");
}

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
} // namespace

int main() {
    try {
        const std::array<std::uint64_t, 12> arguments{1,2,3,4,5,6,7,8,9,10,11,12};
        require(sky_host_call_integer(reinterpret_cast<void*>(&twelve_integer_arguments), arguments.data()) == 650,
                "host call lost register or stack arguments");
        run_probes();
        run_trap_probe();
        run_fault_probe();
        run_call_probe();
        std::atomic<unsigned> failures = 0;
        std::vector<std::thread> threads;
        for (unsigned i = 0; i < 4; ++i) threads.emplace_back([&] {
            try { run_probes(); } catch (...) { ++failures; }
        });
        for (auto& thread : threads) thread.join();
        require(failures.load() == 0, "per-thread FS/stack isolation failed");
        std::cout << "synthetic guest entry, FS restoration, startup ABI and thread tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

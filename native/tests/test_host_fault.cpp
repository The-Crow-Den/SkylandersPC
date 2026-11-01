// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/host_fault.hpp"
#include "../guest_start.hpp"
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <csignal>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

extern "C" SKY_SYSV_ABI std::uint64_t sky_fault_probe();
extern "C" SKY_SYSV_ABI std::uint64_t sky_fault_load(const void*);
extern "C" SKY_SYSV_ABI std::uint64_t sky_fault_store(void*);
extern "C" SKY_SYSV_ABI std::uint64_t sky_fault_return();
extern "C" SKY_SYSV_ABI std::uint64_t sky_fault_guest();
extern "C" const unsigned char sky_fault_ud2[], sky_fault_read[], sky_fault_write[];
#ifdef _WIN32
#define READ_THREAD_BASE "    movq %gs:0x30,%rbx\n"
#define CHECK_THREAD_BASE "    cmpq %gs:0x30,%rbx\n"
#else
#define READ_THREAD_BASE "    movq %fs:0,%rbx\n"
#define CHECK_THREAD_BASE "    cmpq %fs:0,%rbx\n"
#endif
asm(R"(
.text
.globl sky_fault_guest
sky_fault_guest:
    pushq %rbx
)" READ_THREAD_BASE R"(
    call sky_fault_probe
)" CHECK_THREAD_BASE R"(
    je 1f
    xorq %rax,%rax
1:  popq %rbx
    ret
.globl sky_fault_probe
sky_fault_probe:
    pushq %rbx
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    movq $1,%rax
    movq $2,%rcx
    movq $3,%rdx
    movq $4,%rbx
    movq $6,%rbp
    movq $7,%rsi
    movq $8,%rdi
    movq $9,%r8
    movq $10,%r9
    movq $11,%r10
    movq $12,%r11
    movq $13,%r12
    movq $14,%r13
    movq $15,%r14
    movq $16,%r15
    stc
.globl sky_fault_ud2
sky_fault_ud2:
    ud2
    adcq $0,%rax
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbp
    popq %rbx
    ret
.globl sky_fault_load
sky_fault_load:
.globl sky_fault_read
sky_fault_read:
    movq (%rdi),%rax
    ret
.globl sky_fault_store
sky_fault_store:
.globl sky_fault_write
sky_fault_write:
    movq %rax,(%rdi)
    ret
.globl sky_fault_return
sky_fault_return:
    movq $42,%rax
    ret
)");

namespace {
void require(bool value) { if (!value) std::abort(); }
thread_local int host_tls_marker=0;
std::atomic<unsigned> handled{0};
std::atomic<bool> decline{false};
std::uint64_t memory_address=0;
bool handle(SkyHost::Fault& fault) noexcept {
    using namespace SkyHost;
    if (decline.load()) {
        fault.cpu.pc=0; // Declining must not commit this mutation.
        return false;
    }
    if (host_tls_marker != 123) return false;
    if (fault.cpu.pc == reinterpret_cast<std::uintptr_t>(sky_fault_ud2)) {
        if (fault.kind != FaultKind::illegal_instruction || !(fault.cpu.flags & 1)) return false;
        for (unsigned i=0; i<16; ++i)
            if (i!=4 && fault.cpu.gpr[i]!=i+1) return false;
        if (!fault.cpu.reg(Gpr::rsp)) return false;
        fault.cpu.pc+=2;
        fault.cpu.flags &= ~std::uint64_t{1};
    } else if (fault.cpu.pc == reinterpret_cast<std::uintptr_t>(sky_fault_read) ||
               fault.cpu.pc == reinterpret_cast<std::uintptr_t>(sky_fault_write)) {
        const auto access=fault.cpu.pc==reinterpret_cast<std::uintptr_t>(sky_fault_read)
            ? FaultAccess::read : FaultAccess::write;
        if (fault.kind != FaultKind::access || fault.address!=memory_address || fault.access!=access)
            return false;
        fault.cpu.pc+=3;
    } else if (fault.cpu.pc==memory_address) {
        if (fault.kind!=FaultKind::access || fault.access!=FaultAccess::execute || fault.address!=memory_address)
            return false;
        fault.cpu.pc=reinterpret_cast<std::uintptr_t>(&sky_fault_return);
    } else return false;
    fault.cpu.reg(Gpr::rax)=42;
    handled.fetch_add(1);
    return true;
}
#ifdef _WIN32
bool unknown_seen=false;
LONG CALLBACK fallback(EXCEPTION_POINTERS* info) {
    if (info->ExceptionRecord->ExceptionCode==0xe0421234) {
        unknown_seen=true;
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    if (info->ExceptionRecord->ExceptionCode != EXCEPTION_ILLEGAL_INSTRUCTION ||
        info->ContextRecord->Rip != reinterpret_cast<std::uintptr_t>(sky_fault_ud2))
        return EXCEPTION_CONTINUE_SEARCH;
    info->ContextRecord->Rip+=2;
    info->ContextRecord->Rax=42;
    info->ContextRecord->EFlags &= ~DWORD{1};
    return EXCEPTION_CONTINUE_EXECUTION;
}
#endif
}

int main() {
    using namespace SkyHost;
    host_tls_marker=123;
#ifndef _WIN32
    std::vector<unsigned char> alternate(128*1024);
    stack_t stack{}, old_stack{};
    stack.ss_sp=alternate.data(); stack.ss_size=alternate.size();
    require(sigaltstack(&stack,&old_stack)==0);
    struct sigaction old_action{};
    require(sigaction(SIGILL,nullptr,&old_action)==0);
#endif
    require(!remove_fault_handler());
    require(!install_fault_handler(nullptr));
    require(install_fault_handler(&handle));
    require(!install_fault_handler(&handle));
    require(sky_fault_probe()==42);
    // The same fault from a real synthetic guest must restore host TLS for
    // the handler, then restore guest FS on POSIX before resuming.
    std::vector<unsigned char> guest_stack(128*1024);
    alignas(16) std::array<std::uint64_t,32> tcb{};
    tcb[0]=reinterpret_cast<std::uintptr_t>(tcb.data());
    SkyGuestStartContext start{reinterpret_cast<void*>(&sky_fault_guest),
        guest_stack.data()+guest_stack.size(),tcb.data(),nullptr,nullptr};
    std::uint64_t result=0;
    require(sky_guest_start(&start,&result)==0 && result==42);
#ifdef _WIN32
    void* page=VirtualAlloc(nullptr,65536,MEM_RESERVE|MEM_COMMIT,PAGE_NOACCESS);
#else
    void* page=mmap(nullptr,65536,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    require(page!=MAP_FAILED);
#endif
    require(page!=nullptr);
    memory_address=reinterpret_cast<std::uintptr_t>(page);
    require(sky_fault_load(page)==42);
    require(sky_fault_store(page)==42);
#ifdef _WIN32
    DWORD old_protection=0;
    require(VirtualProtect(page,65536,PAGE_READWRITE,&old_protection)!=0);
#else
    require(mprotect(page,65536,PROT_READ|PROT_WRITE)==0);
#endif
    using GuestFunction=std::uint64_t (SKY_SYSV_ABI *)();
    require(reinterpret_cast<GuestFunction>(page)()==42);
    require(handled.load()==5);
    // Each worker owns its alternate signal stack and host TLS marker. The
    // global registration must serve independent native and guest contexts.
    std::array<std::thread,4> workers;
    for (auto& worker:workers) worker=std::thread([] {
        host_tls_marker=123;
#ifndef _WIN32
        std::vector<unsigned char> alt(128*1024);
        stack_t alternate_stack{}, previous_stack{};
        alternate_stack.ss_sp=alt.data(); alternate_stack.ss_size=alt.size();
        require(sigaltstack(&alternate_stack,&previous_stack)==0);
#endif
        std::vector<unsigned char> stack_memory(128*1024);
        alignas(16) std::array<std::uint64_t,32> block{};
        block[0]=reinterpret_cast<std::uintptr_t>(block.data());
        SkyGuestStartContext context{reinterpret_cast<void*>(&sky_fault_guest),
            stack_memory.data()+stack_memory.size(),block.data(),nullptr,nullptr};
        for (unsigned i=0;i<20;++i) {
            std::uint64_t returned=0;
            require(sky_fault_probe()==42);
            require(sky_guest_start(&context,&returned)==0 && returned==42);
        }
#ifndef _WIN32
        require(sigaltstack(&previous_stack,nullptr)==0);
#endif
    });
    for (auto& worker:workers) worker.join();
    require(handled.load()==165);
    decline.store(true);
#ifdef _WIN32
    void* next=AddVectoredExceptionHandler(0,&fallback);
    require(next!=nullptr);
    RaiseException(0xe0421234,0,0,nullptr);
    require(unknown_seen && handled.load()==165);
    require(sky_fault_probe()==42); // Original context reaches the next VEH.
    require(remove_fault_handler());
    require(sky_fault_probe()==42); // Our VEH was actually removed.
    require(RemoveVectoredExceptionHandler(next)!=0);
    require(VirtualFree(page,0,MEM_RELEASE)!=0);
#else
    const auto child=fork();
    require(child>=0);
    if (!child) { sky_fault_probe(); _exit(1); }
    int status=0;
    require(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==126);
    require(remove_fault_handler());
    struct sigaction restored{};
    require(sigaction(SIGILL,nullptr,&restored)==0 && restored.sa_sigaction==old_action.sa_sigaction);
    require(sigaltstack(&old_stack,nullptr)==0);
    require(munmap(page,65536)==0);
#endif
    require(!remove_fault_handler());
    decline.store(false);
    require(install_fault_handler(&handle));
    require(sky_fault_probe()==42);
    require(remove_fault_handler());
    std::puts("host fault tests passed");
}

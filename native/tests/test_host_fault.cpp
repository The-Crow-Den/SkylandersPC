// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/host_fault.hpp"
#include "../platform/host_thread.hpp"
#include "../platform/host_memory.hpp"
#include "../platform/host_random.hpp"
#include "../hle/kernel_data.hpp"
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
    // Permanent guards on both ends of the production stack allocation must
    // fault on every access, including repeated reads after a handled fault.
    ThreadMemory guarded;
    const auto page_size = thread_page_size();
    require(page_size && !guarded.allocate(0) && guarded.allocate(4 * page_size));
    require(!guarded.allocate(page_size));
    const auto base = reinterpret_cast<std::uintptr_t>(guarded.data());
    require(base < 0x80000000 && guarded.size() == 4 * page_size);
    const auto* bytes = static_cast<const unsigned char*>(guarded.data());
    for (std::size_t i = 0; i < guarded.size(); ++i) require(bytes[i] == 0);
    require(!guarded.protect_none(1,page_size) && !guarded.protect_none(0,1) &&
            !guarded.protect_none(guarded.size(),page_size) && !guarded.protect_none(0,0));
    require(guarded.protect_none(0,page_size) && guarded.protect_none(3 * page_size,page_size));
    for (const auto offset : {std::size_t{0},3 * page_size}) {
        auto* address = static_cast<unsigned char*>(guarded.data()) + offset;
        memory_address = reinterpret_cast<std::uintptr_t>(address);
        require(sky_fault_load(address) == 42 && sky_fault_load(address) == 42);
    }
    require(handled.load() == 169);
    require(protect(base + page_size,page_size,ProtRead));
    auto* readonly = static_cast<unsigned char*>(guarded.data()) + page_size;
    memory_address = reinterpret_cast<std::uintptr_t>(readonly);
    require(sky_fault_store(readonly) == 42 && sky_fault_store(readonly) == 42 && *readonly == 0);
    require(protect(base + 2 * page_size,page_size,ProtNone));
    auto* inaccessible = static_cast<unsigned char*>(guarded.data()) + 2 * page_size;
    memory_address = reinterpret_cast<std::uintptr_t>(inaccessible);
    require(sky_fault_load(inaccessible) == 42 && sky_fault_load(inaccessible) == 42);
    require(handled.load() == 173);
    std::array<std::uint8_t,1026> random_buffer{};
    random_buffer.front() = 0x5a;
    random_buffer.back() = 0xa5;
    require(random_bytes({}) && random_bytes(std::span(random_buffer).subspan(1,1024)));
    require(random_buffer.front() == 0x5a && random_buffer.back() == 0xa5);
    ThreadMemory empty;
    require(!empty.protect_readonly(0,page_size));
    require(!guarded.protect_readonly(1,page_size) && !guarded.protect_readonly(0,1) &&
            !guarded.protect_readonly(guarded.size(),page_size) && !guarded.protect_readonly(0,0));
    KernelData data;
    constexpr auto guard_identity = "f7uOxY9mM1U#libkernel#libkernel";
    const auto* guard = static_cast<const unsigned char*>(data.resolve(guard_identity,1));
    require(guard && !data.resolve(guard_identity,0) &&
            !data.resolve("f7uOxY9mM1U#wrong#libkernel",1));
    std::array<unsigned char,8> before{};
    for (std::size_t i = 0; i < page_size; ++i) {
        if (i < before.size()) before[i] = guard[i];
        else require(guard[i] == 0);
    }
    memory_address = reinterpret_cast<std::uintptr_t>(guard);
    require(sky_fault_store(const_cast<unsigned char*>(guard)) == 42);
    require(sky_fault_store(const_cast<unsigned char*>(guard)) == 42);
    for (std::size_t i = 0; i < before.size(); ++i) require(guard[i] == before[i]);
    require(handled.load() == 175);
    decline.store(true);
#ifdef _WIN32
    void* next=AddVectoredExceptionHandler(0,&fallback);
    require(next!=nullptr);
    RaiseException(0xe0421234,0,0,nullptr);
    require(unknown_seen && handled.load()==175);
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

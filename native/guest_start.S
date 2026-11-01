// SPDX-License-Identifier: GPL-3.0-or-later
/* SysV bridge. Linux switches FS/GS; Windows keeps both host bases intact. */
#if (!defined(__linux__) && !defined(_WIN32)) || !defined(__x86_64__)
#error "sky_guest_start requires Linux or Windows x86-64"
#endif
#ifdef _WIN32
#define BRIDGE(offset) offset(%r11)
#else
#define BRIDGE(offset) %gs:offset
#endif
    .text
#ifdef _WIN32
    .macro load_bridge
    movl sky_host_tls_offset(%rip), %r11d
    testl %r11d, %r11d
    jz .Lfatal
    movq %gs:(%r11), %r11
    testq %r11, %r11
    jz .Lfatal
    movq 0(%r11), %r11
    testq %r11, %r11
    jz .Lfatal
    .endm
#endif
    .globl sky_guest_start
#ifdef __ELF__
    .type sky_guest_start,@function
#endif
sky_guest_start:
    testq %rdi, %rdi
    jz .Linvalid
    testq %rsi, %rsi
    jz .Linvalid
    cmpq $0, 0(%rdi)
    je .Linvalid
    cmpq $32, 8(%rdi)
    jb .Linvalid
    cmpq $0, 16(%rdi)
    je .Linvalid
    pushq %rbp
    pushq %rbx
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    subq $104, %rsp
    movq %rsi, 8(%rsp)
    movq %rdi, 16(%rsp)
    movq $0, 24(%rsp)
#ifdef _WIN32
    call sky_host_tls_state
    testq %rax, %rax
    jz .Ltls_unavailable
    movq %rax, 0(%rsp)
    movq 0(%rax), %rdx
    movq %rdx, 32(%rsp)
    movq 8(%rax), %rdx
    movq %rdx, 96(%rsp)
#else
    movq $158, %rax
    movq $0x1003, %rdi
    movq %rsp, %rsi
    syscall
    testq %rax, %rax
    jnz .Lreturn
    movq $158, %rax
    movq $0x1004, %rdi
    leaq 32(%rsp), %rsi
    syscall
    testq %rax, %rax
    jnz .Lreturn
#endif
.Lclaim:
    movl .Lactive(%rip), %eax
    cmpl $-1, %eax
    je .Lbusy
    leal 1(%eax), %edx
    lock cmpxchgl %edx, .Lactive(%rip)
    jne .Lclaim
    movq $1, 24(%rsp)
    /* Feature selection runs under host FS, once cached by the C++ helper.
       This per-entry flag follows nested GS contexts without global mutation. */
#ifndef _WIN32
    call sky_guest_fast_tls_enabled
    movl %eax, %eax
    movq %rax, 96(%rsp)
#endif
    /* Bridge state (Linux GS base, Windows host TLS pointer):
       host FS/TLS state, host stack, trap, fault, call, magic,
       saved guest stack and per-entry direct-FS flag. */
    movq 0(%rsp), %rax
    movq %rax, 40(%rsp)
    movq %rsp, 48(%rsp)
    movq .Ltrap_handler(%rip), %rax
    movq %rax, 56(%rsp)
    movq .Lfault_handler(%rip), %rax
    movq %rax, 64(%rsp)
    movq .Lcall_handler(%rip), %rax
    movq %rax, 72(%rsp)
    movq $0x534b5942, 80(%rsp)
#ifdef _WIN32
    movq 0(%rsp), %rax
    leaq 40(%rsp), %rdx
    movq %rdx, 0(%rax)
    movq 16(%rsp), %r12
    movq 16(%r12), %rdx
    movq %rdx, 8(%rax)
#else
    movq $158, %rax
    movq $0x1001, %rdi
    leaq 40(%rsp), %rsi
    syscall
    testq %rax, %rax
    jnz .Lfinish
    movq 16(%rsp), %r12
    movq 16(%r12), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lfinish
#endif
    movq 8(%r12), %rdx
    andq $-16, %rdx
    subq $16, %rdx
    movq %rsp, 0(%rdx)
    movq %rdx, %rsp
    movq 24(%r12), %rdi
    movq 32(%r12), %rsi
    xorl %edx, %edx
    call *0(%r12)
    movq 0(%rsp), %r12
    movq %rax, %r13
    movq %r12, %rsp
.Lentry_restore_fs:
#ifndef _WIN32
    movq 0(%rsp), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
#endif
    movq 8(%rsp), %rdx
    movq %r13, 0(%rdx)
    xorl %eax, %eax
.Lfinish:
#ifdef _WIN32
    movq 0(%rsp), %rdx
    movq 32(%rsp), %rcx
    movq %rcx, 0(%rdx)
    movq 96(%rsp), %rcx
    movq %rcx, 8(%rdx)
#else
    movq %rax, 88(%rsp)
    movq 32(%rsp), %rsi
    movq $0x1001, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
    movq 88(%rsp), %rax
#endif
.Lreturn:
    cmpq $0, 24(%rsp)
    je .Lregisters
    lock decl .Lactive(%rip)
.Lregisters:
    addq $104, %rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbx
    popq %rbp
    ret
.Lbusy:
    movl $-16, %eax
    jmp .Lreturn
.Linvalid:
    movl $-22, %eax
    ret
#ifdef _WIN32
.Ltls_unavailable:
    movl $-12, %eax
    jmp .Lreturn
#else
.Lrestore_failed:
    movq $231, %rax
    movq $127, %rdi
    syscall
    ud2
#endif
#ifdef __ELF__
    .size sky_guest_start, .-sky_guest_start
#endif

    .globl sky_guest_configure_trap
#ifdef __ELF__
    .type sky_guest_configure_trap,@function
#endif
sky_guest_configure_trap:
    leaq .Ltrap_handler(%rip), %r8
    jmp .Lconfigure
#ifdef __ELF__
    .size sky_guest_configure_trap, .-sky_guest_configure_trap
#endif
#ifndef _WIN32
    .globl sky_guest_configure_fault
#ifdef __ELF__
    .type sky_guest_configure_fault,@function
#endif
sky_guest_configure_fault:
    leaq .Lfault_handler(%rip), %r8
    jmp .Lconfigure
#ifdef __ELF__
    .size sky_guest_configure_fault, .-sky_guest_configure_fault
#endif
#endif
    .globl sky_guest_configure_call
#ifdef __ELF__
    .type sky_guest_configure_call,@function
#endif
sky_guest_configure_call:
    leaq .Lcall_handler(%rip), %r8
.Lconfigure:
    xorl %eax, %eax
    movl $-1, %edx
    lock cmpxchgl %edx, .Lactive(%rip)
    jne .Lconfiguration_busy
    movq %rdi, (%r8)
    movl $0, .Lactive(%rip)
    xorl %eax, %eax
    ret
.Lconfiguration_busy:
    movl $-16, %eax
    ret
#ifdef __ELF__
    .size sky_guest_configure_call, .-sky_guest_configure_call
#endif

    .globl sky_guest_trap_bridge
#ifdef __ELF__
    .type sky_guest_trap_bridge,@function
#endif
sky_guest_trap_bridge:
#ifdef _WIN32
    load_bridge
#endif
    cmpq $0x534b5942, BRIDGE(40)
    jne .Lfatal
#ifdef _WIN32
    // Valid entries terminate on the native stack, including absent handlers.
    movq BRIDGE(8), %rsp
#endif
    cmpq $0, BRIDGE(16)
    je .Lfatal
#ifndef _WIN32
    movq BRIDGE(0), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
#endif
    movq BRIDGE(8), %rsp
    movq %r10, %rdi
    call *BRIDGE(16)
.Lfatal:
#ifdef _WIN32
    // Termination helper is SysV; align even if entered via a guest JMP.
    andq $-16, %rsp
    call sky_host_bridge_fatal
    ud2
#else
    movq $231, %rax
    movq $126, %rdi
    syscall
    ud2
#endif
#ifdef __ELF__
    .size sky_guest_trap_bridge, .-sky_guest_trap_bridge
#endif

#ifndef _WIN32
    .globl sky_guest_fault_bridge
#ifdef __ELF__
    .type sky_guest_fault_bridge,@function
#endif
sky_guest_fault_bridge:
    /* Stay on the alternate signal stack so a handled fault can sigreturn.
       Preserve callee-saved registers and the interrupted thread's FS base. */
    pushq %rbp
    pushq %rbx
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    subq $72, %rsp
    movq %rdi, 0(%rsp)
    movq %rsi, 8(%rsp)
    movq %rdx, 16(%rsp)
    movq $158, %rax
    movq $0x1003, %rdi
    leaq 24(%rsp), %rsi
    syscall
    testq %rax, %rax
    jnz .Lfatal
    movq $158, %rax
    movq $0x1004, %rdi
    leaq 32(%rsp), %rsi
    syscall
    testq %rax, %rax
    jnz .Lfatal
    cmpq $0, 32(%rsp)
    je .Lfault_host_ready
    cmpq $0x534b5942, BRIDGE(40)
    jne .Lfatal
    movq BRIDGE(0), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
.Lfault_host_ready:
    cmpq $0, .Lfault_handler(%rip)
    je .Lfatal
    movq 0(%rsp), %rdi
    movq 8(%rsp), %rsi
    movq 16(%rsp), %rdx
    call *.Lfault_handler(%rip)
    testl %eax, %eax
    jz .Lfatal
    movq 24(%rsp), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
    addq $72, %rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbx
    popq %rbp
    ret
#ifdef __ELF__
    .size sky_guest_fault_bridge, .-sky_guest_fault_bridge
#endif

#endif
    .globl sky_guest_call_bridge
#ifdef __ELF__
    .type sky_guest_call_bridge,@function
#endif
sky_guest_call_bridge:
#ifdef _WIN32
    load_bridge
#endif
    cmpq $0x534b5942, BRIDGE(40)
    jne .Lfatal
    cmpq $0, BRIDGE(32)
#ifdef _WIN32
    jne .Lcall_present
    movq BRIDGE(8), %rsp
    jmp .Lfatal
.Lcall_present:
#else
    je .Lfatal
#endif
    subq $72, %rsp
    movq %rdi, 0(%rsp)
    movq %rsi, 8(%rsp)
    movq %rdx, 16(%rsp)
    movq %rcx, 24(%rsp)
    movq %r8, 32(%rsp)
    movq %r9, 40(%rsp)
    movq %r10, 48(%rsp)
    movq %rsp, BRIDGE(48)
#ifndef _WIN32
    cmpq $0, BRIDGE(56)
    je .Lcall_syscall_fs
    rdfsbase %rax
    movq %rax, 56(%rsp)
    movq BRIDGE(0), %rax
    wrfsbase %rax
    jmp .Lcall_host_fs_ready
.Lcall_syscall_fs:
    movq $158, %rax
    movq $0x1003, %rdi
    leaq 56(%rsp), %rsi
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
    movq BRIDGE(0), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
.Lcall_host_fs_ready:
#endif
    movq 48(%rsp), %rdi
    movq %rsp, %rsi
    leaq 80(%rsp), %rdx
    movq BRIDGE(8), %rsp
    call *BRIDGE(32)
#ifdef _WIN32
    load_bridge
#endif
    movq BRIDGE(48), %rsp
    movq %rax, 0(%rsp)
#ifndef _WIN32
    movq 56(%rsp), %rsi
    cmpq $0, BRIDGE(56)
    je .Lcall_syscall_restore
    wrfsbase %rsi
    jmp .Lcall_guest_fs_ready
.Lcall_syscall_restore:
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
.Lcall_guest_fs_ready:
#endif
    movq 0(%rsp), %rax
    addq $72, %rsp
    ret
#ifdef __ELF__
    .size sky_guest_call_bridge, .-sky_guest_call_bridge
#endif

    .globl sky_guest_thread_exit
#ifdef __ELF__
    .type sky_guest_thread_exit,@function
#endif
sky_guest_thread_exit:
#ifdef _WIN32
    load_bridge
#endif
    /* Called with host FS from the explicit thread-exit service. No host
       resources may be held on the abandoned service stack. */
    cmpq $0x534b5942, BRIDGE(40)
    jne .Lfatal
    movq %rdi, %r13
    movq BRIDGE(8), %rsp
    jmp .Lentry_restore_fs
#ifdef __ELF__
    .size sky_guest_thread_exit, .-sky_guest_thread_exit
#endif

    .globl sky_host_call_integer
#ifdef __ELF__
    .type sky_host_call_integer,@function
#endif
sky_host_call_integer:
    /* Host TLS already selected. Twelve prepared integer/pointer arguments.
       The bridge entry is SysV; the target function uses the native host ABI. */
    pushq %r12
    pushq %r13
#ifdef _WIN32
    subq $104, %rsp
#else
    subq $56, %rsp
#endif
    movq %rdi, %r12
    movq %rsi, %r13
#ifdef _WIN32
    /* Win64 shadow space, then arguments five through twelve. */
    movq 32(%r13), %rax
    movq %rax, 32(%rsp)
    movq 40(%r13), %rax
    movq %rax, 40(%rsp)
    movq 48(%r13), %rax
    movq %rax, 48(%rsp)
    movq 56(%r13), %rax
    movq %rax, 56(%rsp)
    movq 64(%r13), %rax
    movq %rax, 64(%rsp)
    movq 72(%r13), %rax
    movq %rax, 72(%rsp)
    movq 80(%r13), %rax
    movq %rax, 80(%rsp)
    movq 88(%r13), %rax
    movq %rax, 88(%rsp)
    movq 0(%r13), %rcx
    movq 8(%r13), %rdx
    movq 16(%r13), %r8
    movq 24(%r13), %r9
    call *%r12
    addq $104, %rsp
#else
    movq 48(%r13), %rax
    movq %rax, 0(%rsp)
    movq 56(%r13), %rax
    movq %rax, 8(%rsp)
    movq 64(%r13), %rax
    movq %rax, 16(%rsp)
    movq 72(%r13), %rax
    movq %rax, 24(%rsp)
    movq 80(%r13), %rax
    movq %rax, 32(%rsp)
    movq 88(%r13), %rax
    movq %rax, 40(%rsp)
    movq 0(%r13), %rdi
    movq 8(%r13), %rsi
    movq 16(%r13), %rdx
    movq 24(%r13), %rcx
    movq 32(%r13), %r8
    movq 40(%r13), %r9
    call *%r12
    addq $56, %rsp
#endif
    popq %r13
    popq %r12
    ret
#ifdef __ELF__
    .size sky_host_call_integer, .-sky_host_call_integer
#endif
    .bss
    .p2align 3
.Ltrap_handler: .quad 0
.Lfault_handler: .quad 0
.Lcall_handler: .quad 0
.Lactive: .long 0
#ifdef __ELF__
    .section .note.GNU-stack,"",@progbits
#endif

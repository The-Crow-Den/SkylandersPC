// SPDX-License-Identifier: GPL-3.0-or-later
/* Original Linux x86-64 bridge: FS is guest TLS; GS holds our per-entry state. */
#if !defined(__linux__) || !defined(__x86_64__)
#error "sky_guest_start requires Linux x86-64"
#endif
    .text
    .globl sky_guest_start
    .type sky_guest_start,@function
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
    call sky_guest_fast_tls_enabled
    movl %eax, %eax
    movq %rax, 96(%rsp)
    /* GS state: host FS, host stack, trap, fault, call, magic,
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
    movq 0(%rsp), %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
    movq 8(%rsp), %rdx
    movq %r13, 0(%rdx)
    xorl %eax, %eax
.Lfinish:
    movq %rax, 88(%rsp)
    movq 32(%rsp), %rsi
    movq $0x1001, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
    movq 88(%rsp), %rax
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
.Lrestore_failed:
    movq $231, %rax
    movq $127, %rdi
    syscall
    ud2
    .size sky_guest_start, .-sky_guest_start

    .globl sky_guest_configure_trap
    .type sky_guest_configure_trap,@function
sky_guest_configure_trap:
    leaq .Ltrap_handler(%rip), %r8
    jmp .Lconfigure
    .size sky_guest_configure_trap, .-sky_guest_configure_trap
    .globl sky_guest_configure_fault
    .type sky_guest_configure_fault,@function
sky_guest_configure_fault:
    leaq .Lfault_handler(%rip), %r8
    jmp .Lconfigure
    .size sky_guest_configure_fault, .-sky_guest_configure_fault
    .globl sky_guest_configure_call
    .type sky_guest_configure_call,@function
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
    .size sky_guest_configure_call, .-sky_guest_configure_call

    .globl sky_guest_trap_bridge
    .type sky_guest_trap_bridge,@function
sky_guest_trap_bridge:
    cmpq $0x534b5942, %gs:40
    jne .Lfatal
    cmpq $0, %gs:16
    je .Lfatal
    movq %gs:0, %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
    movq %gs:8, %rsp
    movq %r10, %rdi
    call *%gs:16
.Lfatal:
    movq $231, %rax
    movq $126, %rdi
    syscall
    ud2
    .size sky_guest_trap_bridge, .-sky_guest_trap_bridge

    .globl sky_guest_fault_bridge
    .type sky_guest_fault_bridge,@function
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
    cmpq $0x534b5942, %gs:40
    jne .Lfatal
    movq %gs:0, %rsi
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
    .size sky_guest_fault_bridge, .-sky_guest_fault_bridge

    .globl sky_guest_call_bridge
    .type sky_guest_call_bridge,@function
sky_guest_call_bridge:
    cmpq $0x534b5942, %gs:40
    jne .Lfatal
    cmpq $0, %gs:32
    je .Lfatal
    subq $72, %rsp
    movq %rdi, 0(%rsp)
    movq %rsi, 8(%rsp)
    movq %rdx, 16(%rsp)
    movq %rcx, 24(%rsp)
    movq %r8, 32(%rsp)
    movq %r9, 40(%rsp)
    movq %r10, 48(%rsp)
    movq %rsp, %gs:48
    cmpq $0, %gs:56
    je .Lcall_syscall_fs
    rdfsbase %rax
    movq %rax, 56(%rsp)
    movq %gs:0, %rax
    wrfsbase %rax
    jmp .Lcall_host_fs_ready
.Lcall_syscall_fs:
    movq $158, %rax
    movq $0x1003, %rdi
    leaq 56(%rsp), %rsi
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
    movq %gs:0, %rsi
    movq $0x1002, %rdi
    movq $158, %rax
    syscall
    testq %rax, %rax
    jnz .Lrestore_failed
.Lcall_host_fs_ready:
    movq 48(%rsp), %rdi
    movq %rsp, %rsi
    leaq 80(%rsp), %rdx
    movq %gs:8, %rsp
    call *%gs:32
    movq %gs:48, %rsp
    movq %rax, 0(%rsp)
    movq 56(%rsp), %rsi
    cmpq $0, %gs:56
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
    movq 0(%rsp), %rax
    addq $72, %rsp
    ret
    .size sky_guest_call_bridge, .-sky_guest_call_bridge

    .globl sky_guest_thread_exit
    .type sky_guest_thread_exit,@function
sky_guest_thread_exit:
    /* Called with host FS from the explicit thread-exit service. No host
       resources may be held on the abandoned service stack. */
    cmpq $0x534b5942, %gs:40
    jne .Lfatal
    movq %rdi, %r13
    movq %gs:8, %rsp
    jmp .Lentry_restore_fs
    .size sky_guest_thread_exit, .-sky_guest_thread_exit

    .globl sky_host_call_integer
    .type sky_host_call_integer,@function
sky_host_call_integer:
    /* Host FS already selected. Twelve prepared integer/pointer arguments.
       Pack six stack slots, then fill the six SysV argument registers. */
    pushq %r12
    pushq %r13
    subq $56, %rsp
    movq %rdi, %r12
    movq %rsi, %r13
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
    popq %r13
    popq %r12
    ret
    .size sky_host_call_integer, .-sky_host_call_integer
    .bss
    .p2align 3
.Ltrap_handler: .quad 0
.Lfault_handler: .quad 0
.Lcall_handler: .quad 0
.Lactive: .long 0
    .section .note.GNU-stack,"",@progbits

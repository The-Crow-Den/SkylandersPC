// SPDX-License-Identifier: GPL-2.0-or-later
// renderer Windows: sigsetjmp/siglongjmp for the fault recovery points (a draw preparation worker
// reading guest memory that went away; the runtime's own). No SEH unwinding (guest frames have no
// unwind data): every Win64 callee-saved register, xmm6-15 included, is saved and restored
// (sky_setjmp/sky_longjmp, the runtime's win32 assembly). The runtime's exception handler resumes a
// faulting thread in sky_longjmp.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

typedef unsigned long long sigjmp_buf[32];
__attribute__((returns_twice)) int sky_setjmp(sigjmp_buf buffer);
__attribute__((noreturn)) void sky_longjmp(sigjmp_buf buffer, int value);

/// Calls function(argument) on the stack [low, high) (TEB stack bounds set to it meanwhile).
void sky_run_on_stack(void (*function)(void*), void* argument, void* low, void* high);

#ifdef __cplusplus
}
#endif

#define sigsetjmp(buffer, save_mask) sky_setjmp(buffer)
#define siglongjmp(buffer, value) sky_longjmp(buffer, value)

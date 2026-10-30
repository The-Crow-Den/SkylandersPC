// SPDX-License-Identifier: GPL-2.0-or-later
// renderer Windows: MinGW's setjmp.h (re)defines setjmp/longjmp on every inclusion (outside its
// guard), with a longjmp that unwinds through SEH and stops at the game's frames. In C they are
// sky_setjmp/sky_longjmp (renderer_jmp.h) after each inclusion: no include guard here on purpose.
#include_next <setjmp.h>
#ifndef __cplusplus
#include "renderer_jmp.h"
#undef setjmp
#undef longjmp
#define setjmp(buffer) sky_setjmp((unsigned long long*)(buffer))
#define longjmp(buffer, value) sky_longjmp((unsigned long long*)(buffer), value)
#endif

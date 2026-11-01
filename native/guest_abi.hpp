// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// PS4 code and the assembly bridges always use SysV, including on Win64.
// Apply this to definitions as well as declarations and callback pointer types.
#if defined(_WIN32) && defined(__x86_64__)
#define SKY_SYSV_ABI __attribute__((sysv_abi))
#else
#define SKY_SYSV_ABI
#endif

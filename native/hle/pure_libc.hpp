// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <string_view>

// Exact canonical NID#library#module identities only. nullptr means unresolved.
// This supplies no OS, allocator, thread, TLS or exception-runtime behavior.
void* resolve_pure_libc(std::string_view identity) noexcept;

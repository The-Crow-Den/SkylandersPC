// SPDX-License-Identifier: GPL-3.0-or-later
#include "pure_libc.hpp"

#include <array>
#include <cstddef>
#include <cstring>
#include <utility>

namespace {
// Host and guest use the System V x86-64 ABI on the initial Linux target.
// Pointers remain the caller's responsibility, as for the libc interfaces.
extern "C" void* sky_memcpy(void* dst, const void* src, std::size_t size) noexcept {
    return std::memcpy(dst, src, size);
}
extern "C" void* sky_memmove(void* dst, const void* src, std::size_t size) noexcept {
    return std::memmove(dst, src, size);
}
extern "C" void* sky_memset(void* dst, int value, std::size_t size) noexcept {
    return std::memset(dst, value, size);
}
extern "C" int sky_memcmp(const void* lhs, const void* rhs, std::size_t size) noexcept {
    return std::memcmp(lhs, rhs, size);
}
extern "C" std::size_t sky_strlen(const char* text) noexcept {
    return std::strlen(text);
}
extern "C" int sky_strcmp(const char* lhs, const char* rhs) noexcept {
    return std::strcmp(lhs, rhs);
}
}

void* resolve_pure_libc(std::string_view identity) noexcept {
    // NIDs are platform symbol identifiers, calculated from the public names.
    // The complete library/module scope must match; no NID-only fallback.
    const std::array<std::pair<std::string_view, void*>, 6> bindings{{
        {"Q3VBxCXhUHs#libc#libc", reinterpret_cast<void*>(&sky_memcpy)},
        {"+P6FRGH4LfA#libc#libc", reinterpret_cast<void*>(&sky_memmove)},
        {"8zTFvBIAIN8#libc#libc", reinterpret_cast<void*>(&sky_memset)},
        {"DfivPArhucg#libc#libc", reinterpret_cast<void*>(&sky_memcmp)},
        {"j4ViWNHEgww#libc#libc", reinterpret_cast<void*>(&sky_strlen)},
        {"Ovb2dSJOAuE#libc#libc", reinterpret_cast<void*>(&sky_strcmp)},
    }};
    for (const auto& [name, address] : bindings) {
        if (name == identity) return address;
    }
    return nullptr;
}

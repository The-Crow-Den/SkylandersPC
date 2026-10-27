// SPDX-License-Identifier: GPL-3.0-or-later
#include "pure_libc.hpp"

#include <cstddef>
#include <cstring>
#include <iostream>

int main() {
    using Copy = void* (*)(void*, const void*, std::size_t);
    using Set = void* (*)(void*, int, std::size_t);
    using Compare = int (*)(const void*, const void*, std::size_t);
    using Length = std::size_t (*)(const char*);
    using StringCompare = int (*)(const char*, const char*);
    auto copy = reinterpret_cast<Copy>(resolve_pure_libc("Q3VBxCXhUHs#libc#libc"));
    auto move = reinterpret_cast<Copy>(resolve_pure_libc("+P6FRGH4LfA#libc#libc"));
    auto set = reinterpret_cast<Set>(resolve_pure_libc("8zTFvBIAIN8#libc#libc"));
    auto compare = reinterpret_cast<Compare>(resolve_pure_libc("DfivPArhucg#libc#libc"));
    auto length = reinterpret_cast<Length>(resolve_pure_libc("j4ViWNHEgww#libc#libc"));
    auto string_compare = reinterpret_cast<StringCompare>(resolve_pure_libc("Ovb2dSJOAuE#libc#libc"));
    if (!copy || !move || !set || !compare || !length || !string_compare) return 1;
    char target[16]{};
    if (copy(target, "abcdef", 7) != target || length(target) != 6) return 2;
    if (move(target + 1, target, 6) != target + 1 || compare(target, "aabcdef", 7) != 0) return 3;
    if (set(target + 1, 'x', 2) != target + 1 || compare(target, "axx", 3) != 0) return 4;
    if (string_compare("alpha", "beta") >= 0 || string_compare("same", "same") != 0) return 5;
    for (auto invalid : {"Q3VBxCXhUHs#libkernel#libc", "Q3VBxCXhUHs#libc#other",
                         "Q3VBxCXhUHs", "unknown#libc#libc"}) {
        if (resolve_pure_libc(invalid) != nullptr) return 6;
    }
    std::cout << "pure libc ABI and scope tests passed\n";
}

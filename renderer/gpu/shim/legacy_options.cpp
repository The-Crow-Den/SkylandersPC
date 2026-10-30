// SPDX-License-Identifier: GPL-2.0-or-later
// Options used to be read as BB_<name>; they are SKY_RENDERER_<name> now. For one
// transition, a BB_<name> without a SKY_RENDERER_<name> is copied over (with a note) when
// the library loads, before any option is read: the earliest constructor priority runs
// ahead of this library's C++ static initialization.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <unistd.h>

namespace {
__attribute__((constructor(101))) void AdoptLegacyOptions() {
    constexpr char legacy[] = "BB_";
    constexpr char current[] = "SKY_RENDERER_";
    // setenv may move environ, so collect first.
    std::vector<std::pair<std::string, std::string>> found;
    for (char** entry = environ; entry && *entry; ++entry) {
        if (std::strncmp(*entry, legacy, sizeof legacy - 1)) continue;
        const char* separator = std::strchr(*entry, '=');
        if (!separator) continue;
        const char* name = *entry + sizeof legacy - 1;
        found.emplace_back(std::string(name, separator), separator + 1);
    }
    for (const auto& [name, value] : found) {
        const std::string replacement = current + name;
        if (std::getenv(replacement.c_str())) continue;
        std::fprintf(stderr, "Renderer: %s%s is deprecated; use %s\n", legacy, name.c_str(),
                     replacement.c_str());
        setenv(replacement.c_str(), value.c_str(), 0);
    }
}
} // namespace

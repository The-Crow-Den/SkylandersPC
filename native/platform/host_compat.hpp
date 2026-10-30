// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdio>
#include <cstdlib>
#ifdef _WIN32
#include <io.h>
#include <process.h>
#else
#include <unistd.h>
#endif

// The few POSIX calls the host uses that MinGW's CRT spells differently.
namespace SkyHost {
// Flushes a stdio file's kernel buffers to disk (after std::fflush).
inline bool sync_file(std::FILE* file) noexcept {
#ifdef _WIN32
    return _commit(_fileno(file)) == 0;
#else
    return fsync(fileno(file)) == 0;
#endif
}
inline int set_environment(const char* name, const char* value) noexcept {
#ifdef _WIN32
    return _putenv_s(name, value);
#else
    return setenv(name, value, 1);
#endif
}
inline int unset_environment(const char* name) noexcept {
#ifdef _WIN32
    return _putenv_s(name, ""); // an empty value removes the variable
#else
    return unsetenv(name);
#endif
}
} // namespace SkyHost

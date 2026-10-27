// SPDX-License-Identifier: GPL-3.0-or-later
// Logging bridge for the optional, externally compiled MPL Cemu portal core.
#include "Cemu/Logging/CemuLogging.h"
#include <cstdio>
std::uint64_t s_loggingFlagMask = ~std::uint64_t{0};
bool cemuLog_log(LogType, std::string_view text) {
    std::fprintf(stderr,"Portal: %.*s\n",static_cast<int>(text.size()),text.data());
    return true;
}

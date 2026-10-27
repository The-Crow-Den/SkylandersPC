// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <vector>

struct SkyBootModule {
    std::uint64_t id, init, tls_address, tls_filesz, tls_memsz, tls_align;
};
struct SkyBootPlan {
    std::uint64_t process_param = 0;
    std::vector<SkyBootModule> modules;
};

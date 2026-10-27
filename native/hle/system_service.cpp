// SPDX-License-Identifier: GPL-3.0-or-later
#include "system_service.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#include <ctime>
#include <stdexcept>

namespace {
constexpr std::array<std::string_view, 4> names{
    "fZo48un7LK4#libSceSystemService#libSceSystemService",
    "rPo6tV8D9bM#libSceSystemService#libSceSystemService",
    "656LMQSrg6U#libSceSystemService#libSceSystemService",
    "Vo5V8KAwCmk#libSceSystemService#libSceSystemService"};
}
bool SystemService::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
std::uint64_t SystemService::call(std::string_view identity, const std::uint64_t* a) {
    if (identity == names[0]) {
        if (!a[1]) return 0x80a10003;
        auto* out = reinterpret_cast<std::int32_t*>(a[1]);
        switch (a[0]) {
            case 1: *out = 1; break; // English US.
            case 2: *out = 1; break; // DD/MM/YYYY.
            case 3: *out = 1; break; // 24-hour clock.
            case 4: case 5: {
                const auto now = std::time(nullptr);
                std::tm local{};
                if (!localtime_r(&now, &local)) throw std::runtime_error("cannot read local timezone");
                *out = a[0] == 4 ? static_cast<std::int32_t>(local.tm_gmtoff / 60) : local.tm_isdst > 0;
                break;
            }
            case 7: *out = 0; break; // No configured parental restriction.
            case 1000: *out = 1; break; // Cross is the accept button.
            default: return 0x80a10003;
        }
        return 0;
    }
    if (identity == names[1]) {
        if (!a[0]) return 0x80a10003;
        // Foreground application, no shell overlay and no pending system event.
        std::memset(reinterpret_cast<void*>(a[0]), 0, 12); return 0;
    }
    if (identity == names[2]) return a[0] ? 0x80a10004 : 0x80a10003;
    if (identity == names[3]) { splash_hidden_ = true; return 0; }
    throw std::runtime_error("unsupported system service import");
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string_view>
#include <mutex>

class KernelClock {
public:
    KernelClock();
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    std::mutex lock_;
    std::uint64_t started_, tsc_frequency_ = 0;
};

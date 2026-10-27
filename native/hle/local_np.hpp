// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <mutex>
#include <string_view>
#include <vector>
#include "local_trophies.hpp"
class LocalNp {
public:
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    LocalTrophies trophies_;
    std::mutex lock_;
    std::int8_t age_ = 0;
    std::vector<unsigned char> country_restrictions_;
};

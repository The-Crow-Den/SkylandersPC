// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string_view>
#include <mutex>
#include <deque>
#include <array>

// Offline local users: keyboard/player one 0x1000, second controller 0x1001.
class UserService {
public:
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    std::mutex lock_;
    bool initialized_ = false, second_seen_ = false;
    std::deque<std::array<std::int32_t,2>> events_;
    std::int32_t priority_ = 0;
};

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <map>
#include <mutex>
#include <string_view>

// No host network connection is opened. NetCtl exposes a disconnected console.
class OfflineNetwork {
public:
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    std::mutex lock_;
    bool initialized_ = false, control_initialized_ = false;
    std::map<int, std::uint64_t> pools_;
    int next_pool_ = 1;
};

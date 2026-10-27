// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <mutex>
#include <string_view>
#include <unordered_set>

// A console USB bus with no devices attached. No portal identity is fabricated.
class EmptyUsbBus {
public:
    ~EmptyUsbBus();
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    std::mutex lock_;
    bool initialized_ = false;
    std::unordered_set<void**> lists_;
};

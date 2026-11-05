// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cstdint>
#include <string_view>
class SystemService {
public:
    // SKY_SYSTEM_LANGUAGE selects the reported system language (PS4 code 0..30);
    // English (US) when unset.
    SystemService();
    static std::int32_t language_from(const char* value);
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    std::atomic<bool> splash_hidden_ = false;
    std::int32_t language_ = 1;
};

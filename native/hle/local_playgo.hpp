// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <mutex>
#include <string>
#include <string_view>
// Installed-directory provider. Assumes the supplied package dump is complete;
// validates chunk IDs from its metadata. No download/partial-install backend.
class LocalPlayGo {
public:
    void configure(const std::string& root);
    bool available() const noexcept { return chunks_ != 0; }
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    std::mutex lock_;
    std::uint16_t chunks_ = 0;
    bool initialized_ = false, opened_ = false;
    int speed_ = 2;
};

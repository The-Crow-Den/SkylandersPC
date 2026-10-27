// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>
#include <mutex>
#include <string>
#include <string_view>
class AppContent {
public:
    void configure(const std::string& game_root);
    const std::string& title_id() const noexcept { return title_id_; }
    std::uint32_t attributes() const noexcept { return attributes_; }
    std::uint32_t system_version() const noexcept { return system_version_; }
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    std::mutex lock_;
    std::array<std::uint32_t, 4> parameters_{};
    bool configured_ = false;
    std::string title_id_ = "UNKNOWN";
    std::uint32_t attributes_ = 0, system_version_ = 0;
};

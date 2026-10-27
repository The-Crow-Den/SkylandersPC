// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <memory>
#include <string_view>
class KernelSemaphore {
public:
    KernelSemaphore();
    ~KernelSemaphore();
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments, int caller_priority = 700);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

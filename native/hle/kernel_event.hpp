// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <memory>
#include <string_view>
class KernelEvent {
public:
    KernelEvent();
    ~KernelEvent();
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments, int priority = 700);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

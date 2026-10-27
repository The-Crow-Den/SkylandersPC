// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <memory>
#include <string_view>
#include <functional>

// Opaque guest handles owned by one diagnostic process; no guest threads yet.
class KernelSync {
public:
    KernelSync();
    ~KernelSync();
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
    void finish_thread(const std::function<void(std::uint64_t, std::uint64_t)>& callback);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

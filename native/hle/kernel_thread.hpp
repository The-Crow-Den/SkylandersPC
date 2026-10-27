// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../boot_plan.hpp"
#include "../thread_context.hpp"
#include <cstdint>
#include <memory>
#include <string_view>
#include <functional>

class KernelThread {
public:
    KernelThread();
    ~KernelThread();
    void configure(const SkyBootPlan& boot, std::function<void(GuestThreadContext&)> finalizer = {});
    void attach_main(GuestThreadContext& context);
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
    int current_priority() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

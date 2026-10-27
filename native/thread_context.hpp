// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "boot_plan.hpp"
#include <cstddef>
#include <cstdint>
#include <memory>

// Owns the guest-visible stack, TCB, TLS templates and signal stack of one thread.
class GuestThreadContext {
public:
    GuestThreadContext(const SkyBootPlan& boot, std::size_t stack_size = 8 * 1024 * 1024,
                       std::size_t guard_size = 4096);
    ~GuestThreadContext();
    std::uint64_t run(std::uint64_t entry, const void* argument);
    std::uint64_t callback(std::uint64_t entry, const void* argument);
    std::uint64_t handle() const;
    std::uint64_t tls_address(std::uint64_t module, std::uint64_t offset) const;
    std::int32_t* error_pointer() const;
    std::uint64_t signal_mask(int operation, const void* set, void* old_set);
    bool is_stack_guard(std::uint64_t address) const noexcept;
    static GuestThreadContext* current() noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

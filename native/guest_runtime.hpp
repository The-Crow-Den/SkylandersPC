// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>
#include "boot_plan.hpp"

// The native guest runtime: binds every import to a thunk, dispatches calls to
// the HLE services and runs module initializers and the guest entry on real
// guest threads. Unknown imports and unhandled faults still terminate with a
// report; none returns a fabricated result.
class GuestRuntime {
    struct Impl;
    std::unique_ptr<Impl> impl_;
public:
    GuestRuntime(const std::vector<std::string>& imports, const std::vector<unsigned char>& types);
    ~GuestRuntime();
    std::uint64_t address(std::uint64_t index) const;
    [[noreturn]] void enter(std::uint64_t entry, const SkyBootPlan& boot = {}, const std::string& game_root = "");
};

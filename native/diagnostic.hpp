// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>
#include "boot_plan.hpp"

// Single-thread startup observation. Every import traps or faults; none returns
// a fabricated result. This is not a normal execution/runtime-services mode.
class SkyDiagnostic {
    struct Impl;
    std::unique_ptr<Impl> impl_;
public:
    SkyDiagnostic(const std::vector<std::string>& imports, const std::vector<unsigned char>& types);
    ~SkyDiagnostic();
    std::uint64_t address(std::uint64_t index) const;
    [[noreturn]] void enter(std::uint64_t entry, const SkyBootPlan& boot = {}, const std::string& game_root = "");
};

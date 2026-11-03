// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "host_fault.hpp"
#include <cstdint>
#include <filesystem>
#include <string>
namespace SkyHost {
std::uint64_t current_thread_id() noexcept;
// Explicit diagnostic-only suspension after reporting an unsupported worker
// import. Never resumes the guest or fabricates a successful call result.
[[noreturn]] void suspend_diagnostic_worker() noexcept;
// Existing runtime diagnostics: not a signal-safe logging abstraction. POSIX
// retains vdprintf; Windows flushes stderr before a subsequent immediate exit.
int diagnostic_printf(const char* format, ...) noexcept __attribute__((format(printf,1,2)));
struct ModuleOwner { std::string file; std::uint64_t base = 0; };
bool module_owner(std::uint64_t pc, ModuleOwner& output);
std::filesystem::path default_save_root();
using RuntimeFaultReport = void (*)(const Fault&) noexcept;
using LegacyFaultRecovery = bool (*)(int, void*, void*);
using RuntimeFaultRecovery = bool (*)(Fault&);
// Process-wide, caller serialized with guest entry/faults. POSIX retains the
// original renderer's native-context recovery and diagnostics (including its
// inherited signal-safety limitations). Windows uses the normalized VEH path.
// report must terminate; a returning reporter is terminated by this layer.
bool install_runtime_faults(RuntimeFaultReport report, LegacyFaultRecovery legacy,
                            RuntimeFaultRecovery portable) noexcept;
bool remove_runtime_faults() noexcept;
}

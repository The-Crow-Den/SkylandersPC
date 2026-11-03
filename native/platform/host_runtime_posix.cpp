// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_runtime.hpp"
#include "../guest_start.hpp"
#include <array>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <signal.h>
#include <stdexcept>
#include <utility>
#include <sys/syscall.h>
#include <ucontext.h>
#include <unistd.h>
namespace SkyHost {
std::uint64_t current_thread_id() noexcept { return static_cast<std::uint64_t>(syscall(SYS_gettid)); }
[[noreturn]] void suspend_diagnostic_worker() noexcept { for (;;) pause(); }
int diagnostic_printf(const char* format, ...) noexcept {
    va_list arguments;
    va_start(arguments,format);
    const auto result = vdprintf(STDERR_FILENO,format,arguments);
    va_end(arguments);
    return result;
}
bool module_owner(std::uint64_t pc, ModuleOwner& output) {
    Dl_info owner{};
    if (!dladdr(reinterpret_cast<void*>(pc),&owner) || !owner.dli_fname) return false;
    ModuleOwner result{owner.dli_fname,reinterpret_cast<std::uintptr_t>(owner.dli_fbase)};
    output = std::move(result);
    return true;
}
std::filesystem::path default_save_root() {
    std::filesystem::path path;
    const auto* data = std::getenv("XDG_DATA_HOME");
    const auto* home = std::getenv("HOME");
    if (data && std::filesystem::path(data).is_absolute()) path = data;
    else if (home && std::filesystem::path(home).is_absolute()) path = std::filesystem::path(home)/".local/share";
    else throw std::runtime_error("HOME or an absolute XDG_DATA_HOME is required for saves");
    return path/"skylanders-pc/saves";
}
namespace {
RuntimeFaultReport reporter = nullptr;
LegacyFaultRecovery recovery = nullptr;
constexpr std::array registers{REG_RAX,REG_RCX,REG_RDX,REG_RBX,REG_RSP,REG_RBP,REG_RSI,REG_RDI,
                              REG_R8,REG_R9,REG_R10,REG_R11,REG_R12,REG_R13,REG_R14,REG_R15};
SKY_SYSV_ABI int dispatch(int signal, void* info_raw, void* context_raw) noexcept {
    if (recovery && recovery(signal,info_raw,context_raw)) return 1;
    const auto* info = static_cast<siginfo_t*>(info_raw);
    const auto* context = static_cast<ucontext_t*>(context_raw);
    Fault fault{};
    fault.native_code = static_cast<std::uint32_t>(signal);
    fault.native_error = static_cast<std::uint64_t>(context->uc_mcontext.gregs[REG_ERR]);
    switch (signal) {
    case SIGSEGV: case SIGBUS: fault.kind = FaultKind::access; break;
    case SIGILL: fault.kind = FaultKind::illegal_instruction; break;
    case SIGFPE: fault.kind = FaultKind::arithmetic; break;
    case SIGTRAP: fault.kind = FaultKind::breakpoint; break;
    default: std::_Exit(126);
    }
    fault.address = reinterpret_cast<std::uintptr_t>(info->si_addr);
    if (context->uc_mcontext.gregs[REG_TRAPNO] == 14)
        fault.access = (fault.native_error & 16) ? FaultAccess::execute :
                       (fault.native_error & 2) ? FaultAccess::write : FaultAccess::read;
    for (unsigned i = 0; i < registers.size(); ++i)
        fault.cpu.gpr[i] = static_cast<std::uint64_t>(context->uc_mcontext.gregs[registers[i]]);
    fault.cpu.pc = static_cast<std::uint64_t>(context->uc_mcontext.gregs[REG_RIP]);
    fault.cpu.flags = static_cast<std::uint64_t>(context->uc_mcontext.gregs[REG_EFL]);
    if (reporter) reporter(fault);
    std::_Exit(70);
}
}
bool install_runtime_faults(RuntimeFaultReport report, LegacyFaultRecovery legacy,
                            RuntimeFaultRecovery portable) noexcept {
    (void)portable; // Preserve the existing Linux native renderer context path.
    if (!report || !legacy || !portable || reporter) return false;
    reporter = report; recovery = legacy;
    if (install_legacy_fault_handler(&dispatch)) return true;
    reporter = nullptr; recovery = nullptr;
    return false;
}
bool remove_runtime_faults() noexcept {
    if (!reporter || !remove_legacy_fault_handler()) return false;
    reporter = nullptr; recovery = nullptr;
    return true;
}
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_runtime.hpp"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <utility>
#include <vector>
namespace SkyHost {
std::uint64_t current_thread_id() noexcept { return GetCurrentThreadId(); }
[[noreturn]] void suspend_diagnostic_worker() noexcept { for (;;) Sleep(INFINITE); }
int diagnostic_printf(const char* format, ...) noexcept {
    va_list arguments;
    va_start(arguments,format);
    const auto result = std::vfprintf(stderr,format,arguments);
    va_end(arguments);
    return std::fflush(stderr) == 0 ? result : -1;
}
bool module_owner(std::uint64_t pc, ModuleOwner& output) {
    if (!pc) return false;
    HMODULE module = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(pc),&module)) return false;
    std::vector<wchar_t> path(32768);
    const auto length = GetModuleFileNameW(module,path.data(),static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) return false;
    const auto bytes = WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,path.data(),static_cast<int>(length),nullptr,0,nullptr,nullptr);
    if (!bytes) return false;
    ModuleOwner result{std::string(static_cast<std::size_t>(bytes),'\0'),reinterpret_cast<std::uintptr_t>(module)};
    if (WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,path.data(),static_cast<int>(length),result.file.data(),bytes,nullptr,nullptr) != bytes) return false;
    output = std::move(result);
    return true;
}
std::filesystem::path default_save_root() {
    const auto size = GetEnvironmentVariableW(L"LOCALAPPDATA",nullptr,0);
    if (!size) throw std::runtime_error("an absolute LOCALAPPDATA is required for saves");
    std::vector<wchar_t> buffer(size);
    const auto length = GetEnvironmentVariableW(L"LOCALAPPDATA",buffer.data(),size);
    if (!length || length >= size) throw std::runtime_error("cannot read LOCALAPPDATA for saves");
    const std::filesystem::path path(std::wstring(buffer.data(),length));
    if (!path.is_absolute()) throw std::runtime_error("an absolute LOCALAPPDATA is required for saves");
    return path/L"skylanders-pc"/L"saves";
}
namespace {
RuntimeFaultReport reporter = nullptr;
RuntimeFaultRecovery recovery = nullptr;
bool dispatch(Fault& fault) noexcept {
    if (recovery && recovery(fault)) return true;
    if (reporter) reporter(fault);
    std::_Exit(70);
}
}
bool install_runtime_faults(RuntimeFaultReport report, LegacyFaultRecovery legacy,
                            RuntimeFaultRecovery portable) noexcept {
    (void)legacy;
    if (!report || !legacy || !portable || reporter) return false;
    reporter = report; recovery = portable;
    if (install_fault_handler(&dispatch)) return true;
    reporter = nullptr; recovery = nullptr;
    return false;
}
bool remove_runtime_faults() noexcept {
    if (!reporter || !remove_fault_handler()) return false;
    reporter = nullptr; recovery = nullptr;
    return true;
}
}

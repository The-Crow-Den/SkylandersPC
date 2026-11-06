// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/host_runtime.hpp"
#include "../platform/host_thread.hpp"
#include "../platform/host_compat.hpp"
#include "../thread_context.hpp"
#include "../guest_abi.hpp"
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <source_location>
#include <string_view>
#include <thread>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#else
#include <pthread.h>
#include <unistd.h>
#include <csignal>
#include <ucontext.h>
#endif
extern "C" SKY_SYSV_ABI std::uint64_t sky_runtime_fault_probe();
extern "C" char sky_runtime_ud2[];
asm(R"(
.text
.globl sky_runtime_fault_probe
sky_runtime_fault_probe:
.globl sky_runtime_ud2
sky_runtime_ud2:
    ud2
    mov $42, %eax
    ret
)");
namespace {
void require(bool value, const std::source_location where = std::source_location::current()) {
    if (!value) throw std::runtime_error(std::string("host runtime assertion failed at ") +
        where.file_name() + ":" + std::to_string(where.line()));
}
thread_local unsigned marker = 123;
bool recover = false, reporter_returns = false;
unsigned recovered = 0;
void report(const SkyHost::Fault& fault) noexcept {
    SkyHost::diagnostic_printf("{\"event\":\"runtime-fault\",\"kind\":%u,\"native_code\":%u,\"pc\":%llu,\"expected_pc\":%llu,\"tls\":%u}\n",
        static_cast<unsigned>(fault.kind), fault.native_code,
        static_cast<unsigned long long>(fault.cpu.pc),
        static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(sky_runtime_ud2)),marker);
    if (!reporter_returns) std::_Exit(70);
}
bool legacy(int signal, void*, void* raw) {
#ifndef _WIN32
    auto& context = *static_cast<ucontext_t*>(raw);
    if (recover && marker == 123 && signal == SIGILL &&
        static_cast<std::uint64_t>(context.uc_mcontext.gregs[REG_RIP]) == reinterpret_cast<std::uintptr_t>(sky_runtime_ud2)) {
        context.uc_mcontext.gregs[REG_RIP] += 2;
        ++recovered;
        return true;
    }
#else
    (void)signal; (void)raw;
#endif
    return false;
}
bool portable(SkyHost::Fault& fault) {
    if (recover && marker == 123 && fault.kind == SkyHost::FaultKind::illegal_instruction &&
        fault.cpu.pc == reinterpret_cast<std::uintptr_t>(sky_runtime_ud2)) {
        fault.cpu.pc += 2;
        ++recovered;
        return true;
    }
    return false;
}
bool decline(SkyHost::Fault&) noexcept { return false; }
void basic() {
    using namespace SkyHost;
    const auto main_id = current_thread_id();
    require(main_id && current_thread_id() == main_id);
    const auto pid = process_id();
#ifdef _WIN32
    require(pid == GetCurrentProcessId());
    wchar_t* original = nullptr;
    require(SUCCEEDED(GetThreadDescription(GetCurrentThread(),&original)) && original);
    const std::wstring previous_name(original);
    LocalFree(original);
    require(set_current_thread_name("sky-host-\xce\xbb"));
    wchar_t* changed = nullptr;
    require(SUCCEEDED(GetThreadDescription(GetCurrentThread(),&changed)) && changed);
    require(std::wstring(changed) == L"sky-host-\u03bb");
    LocalFree(changed);
    require(!set_current_thread_name(nullptr) && !set_current_thread_name("\xff"));
    require(SUCCEEDED(SetThreadDescription(GetCurrentThread(),previous_name.c_str())));
#else
    require(pid == static_cast<std::uint64_t>(getpid()));
    std::array<char,16> previous_name{}, changed{};
    require(pthread_getname_np(pthread_self(),previous_name.data(),previous_name.size()) == 0);
    require(set_current_thread_name("sky-host-\xce\xbb"));
    require(pthread_getname_np(pthread_self(),changed.data(),changed.size()) == 0 &&
            std::string_view(changed.data()) == "sky-host-\xce\xbb");
    require(!set_current_thread_name(nullptr) && !set_current_thread_name("host-name-far-over-pthread-limit"));
    require(set_current_thread_name(previous_name.data()));
#endif
    const auto* before = std::getenv("SKY_HOST_ENV_PROBE");
    const bool existed = before != nullptr;
    const std::string saved = before ? before : "";
    require(set_environment("SKY_HOST_ENV_PROBE","first") == 0);
    require(set_environment("SKY_HOST_ENV_PROBE","second",false) == 0 &&
            std::string_view(std::getenv("SKY_HOST_ENV_PROBE")) == "first");
    require(set_environment("SKY_HOST_ENV_PROBE","second") == 0 &&
            std::string_view(std::getenv("SKY_HOST_ENV_PROBE")) == "second");
    require((existed ? set_environment("SKY_HOST_ENV_PROBE",saved.c_str()) : unset_environment("SKY_HOST_ENV_PROBE")) == 0);
    std::array<std::uint64_t,4> ids{};
    std::array<std::thread,4> threads;
    std::atomic<unsigned> ready = 0;
    for (unsigned i = 0; i < threads.size(); ++i) threads[i] = std::thread([&,i] {
        ids[i] = current_thread_id();
        ready.fetch_add(1);
        while (ready.load() != threads.size()) std::this_thread::yield();
        if (!ids[i] || current_thread_id() != ids[i] || process_id() != pid) std::terminate();
    });
    for (auto& thread : threads) thread.join();
    for (unsigned i = 0; i < ids.size(); ++i) {
        require(ids[i] && ids[i] != main_id);
        for (unsigned j = 0; j < i; ++j) require(ids[i] != ids[j]);
    }
    ModuleOwner owner;
    const auto pc = reinterpret_cast<std::uintptr_t>(&basic);
    require(module_owner(pc,owner) && !owner.file.empty() && owner.base <= pc);
    ModuleOwner other;
    require(module_owner(pc + 1,other) && other.base == owner.base && other.file == owner.file);
    other = {"unchanged",42};
    require(!module_owner(1,other) && other.file == "unchanged" && other.base == 42);
    require(!module_owner(0,other) && other.file == "unchanged" && other.base == 42);
    require(!remove_runtime_faults());
    require(!install_runtime_faults(nullptr,&legacy,&portable));
    require(install_fault_handler(&decline));
    require(!install_runtime_faults(&report,&legacy,&portable));
    require(remove_fault_handler());
}
}
int main(int argc, char** argv) {
    try {
        using namespace SkyHost;
        const std::string_view mode = argc > 1 ? argv[1] : "basic";
        if (mode == "--save-root") {
            const auto path = default_save_root().u8string();
            std::cout.write(reinterpret_cast<const char*>(path.data()),static_cast<std::streamsize>(path.size()));
            std::cout << '\n';
            return 0;
        }
        if (mode == "--suspend") {
            diagnostic_printf("runtime-worker-suspended\n");
            suspend_diagnostic_worker();
        }
        if (mode == "--diagnostic") {
            require(diagnostic_printf("runtime-host-check:%llu:%s\n",42ULL,"flushed") > 0);
            std::_Exit(0);
        }
        basic();
        recover = mode == "--recover" || mode == "--guest-recover" || mode == "basic";
        reporter_returns = mode == "--report-return";
        ThreadFaultContext fault_stack;
        require(fault_stack.enter());
        require(install_runtime_faults(&report,&legacy,&portable));
        require(!install_runtime_faults(&report,&legacy,&portable));
        require(!install_fault_handler(&decline) && !remove_fault_handler());
#ifndef _WIN32
        if (mode == "--software") raise(SIGILL);
#endif
        if (mode == "--guest-recover" || mode == "--guest-fatal") {
            const SkyBootPlan boot;
            GuestThreadContext context(boot,65536);
            require(context.run(reinterpret_cast<std::uintptr_t>(&sky_runtime_fault_probe),nullptr) == 42);
        } else {
            const unsigned count = recover ? 20 : 1;
            for (unsigned i = 0; i < count; ++i) require(sky_runtime_fault_probe() == 42);
        }
        require(recovered == (mode == "--guest-recover" ? 1u : 20u));
        require(remove_runtime_faults() && !remove_runtime_faults());
        require(install_fault_handler(&decline) && remove_fault_handler());
        require(fault_stack.leave() && marker == 123);
        std::puts("runtime host tests passed");
    } catch (const std::exception& error) {
        std::fprintf(stderr,"runtime host error: %s\n",error.what());
        return 1;
    }
}

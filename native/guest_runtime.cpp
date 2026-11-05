// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_runtime.hpp"
#include "hle/virtual_portal.hpp"
#include "hle/save_data.hpp"
#include "guest_start.hpp"
#include "thread_context.hpp"
#include "gpu_backend.hpp"
#include "game_hooks.hpp"
#include "frame_profile.hpp"
#include "platform/host_memory.hpp"
#include "platform/host_thread.hpp"
#include "platform/host_runtime.hpp"
#include "hle/kernel_data.hpp"
#include "hle/kernel_sync.hpp"
#include "hle/kernel_memory.hpp"
#include "hle/kernel_clock.hpp"
#include "hle/user_service.hpp"
#include "hle/kernel_semaphore.hpp"
#include "hle/kernel_thread.hpp"
#include "hle/kernel_file.hpp"
#include "hle/kernel_event.hpp"
#include "hle/offline_network.hpp"
#include "hle/system_service.hpp"
#include "hle/local_np.hpp"
#include "hle/app_content.hpp"
#include "hle/local_playgo.hpp"
#include "hle/keyboard_pad.hpp"
#include "hle/empty_usb_bus.hpp"
#include <mutex>
#include <atomic>
#include <thread>
#include <chrono>
#include <cstdlib>
#include <filesystem>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <stdexcept>

namespace {
struct Mapping {
    SkyHost::ThreadMemory storage;
    void* value;
    std::size_t size;
    Mapping(std::size_t length, bool inaccessible = false) : size(length) {
        if (!(inaccessible ? storage.allocate_inaccessible(size) : storage.allocate(size)))
            throw std::runtime_error("cannot allocate runtime import memory");
        value = storage.data();
    }
};
std::size_t runtime_page_size(std::size_t names, std::size_t types) {
    if (names != types || names > 1000000)
        throw std::runtime_error("import types count differs from pack");
    const auto page = SkyHost::memory_page_size();
    if (!page) throw std::runtime_error("cannot determine runtime page size");
    return static_cast<std::size_t>(page);
}
std::string escaped(const std::string& text) {
    std::string result = "\"";
    for (unsigned char c : text) {
        if (c == '"' || c == '\\') { result += '\\'; result += static_cast<char>(c); }
        else if (c < 32) { char buffer[7]; std::snprintf(buffer, sizeof(buffer), "\\u%04x", c); result += buffer; }
        else result += static_cast<char>(c);
    }
    return result + '"';
}
bool startup_service(std::string_view name) {
    return name == "959qrazPIrg#libkernel#libkernel" ||
           name == "p5EcQeEeJAE#libkernel#libkernel" ||
           name == "vNe1w4diLCs#libkernel#libkernel" ||
           name == "aI+OeCz8xrQ#libkernel#libkernel" ||
           name == "9BcDykPmo1I#libkernel#libkernel" ||
           name == "ZkZhskCPXFw#libSceSaveData#libSceSaveData" ||
           name == "6xVpy0Fdq+I#libkernel#libkernel" ||
           name == "EI-5-jlq2dE#libkernel#libkernel" ||
           name == "g8cM39EUZ6o#libSceSysmodule#libSceSysmodule" ||
           name == "fMP5NHUOaMk#libSceSysmodule#libSceSysmodule" ||
           name == "eR2bZFAAU0Q#libSceSysmodule#libSceSysmodule" ||
           name == "FzEWeYnAFlI#libSceContentExport#libSceContentExport" ||
           name == "+KDWny9Y-6k#libSceContentExport#libSceContentExport" ||
           name == "fZJQzFK4Gv4#libSceVideoRecording#libSceVideoRecording" ||
           name == "OOFxrMY+mfI#libSceVideoRecording#libSceVideoRecording" ||
           name == "KHvkPQJDMLk#libSceVideoRecording#libSceVideoRecording" ||
           name == "uoUpLGNkygk#libSceCommonDialog#libSceCommonDialog";
}
}

struct GuestRuntime::Impl {
    std::vector<std::string> names;
    std::vector<unsigned char> types;
    std::vector<bool> weak;
    std::size_t page;
    Mapping code;
    Mapping guards;
    KernelData kernel_data;
    KernelSync kernel_sync;
    KernelMemory kernel_memory;
    KernelClock kernel_clock;
    UserService user_service;
    KernelSemaphore kernel_semaphore;
    KernelThread kernel_thread;
    KernelFile kernel_file;
    SaveData save_data{kernel_file};
    KernelEvent kernel_event;
    OfflineNetwork offline_network;
    SystemService system_service;
    LocalNp local_np;
    AppContent app_content;
    LocalPlayGo local_playgo;
    KeyboardPad keyboard_pad;
    EmptyUsbBus empty_usb_bus;
    std::mutex modules_lock;
    unsigned playgo_references = 0;
    unsigned usb_references = 0;
    std::thread::id main_native_thread;
    bool suspend_unsupported_network_workers = false;
    SkyBootPlan boot;
    std::atomic<std::uint64_t> heap_api = 0;
    std::atomic<bool> common_dialog_initialized = false;
    enum class ServiceKind { Special, KernelMemory, KernelClock, UserService, KernelSemaphore, KernelThread, KernelFile, KernelEvent, OfflineNetwork, SystemService, LocalNp, AppContent, LocalPlayGo, KeyboardPad, SaveData, VirtualPortal, EmptyUsbBus, SkyGpu, KernelSync };
    std::vector<ServiceKind> service_kinds;
    std::vector<FrameProfile::Bucket> profile_buckets;
    std::vector<bool> ends_frame;
    std::vector<unsigned> stack_counts;
    std::vector<unsigned> service_calls;
    std::mutex logging;
    static Impl* active;

    Impl(const std::vector<std::string>& input, const std::vector<unsigned char>& input_types)
        : names(input), types(input_types), page(runtime_page_size(input.size(), input_types.size())),
          code(std::max<std::size_t>(page, ((names.size() * 32 + page - 1) / page) * page)),
          guards(std::max<std::size_t>(page, names.size() * page), true) {
        service_calls.resize(names.size());
        service_kinds.reserve(names.size()); stack_counts.reserve(names.size());
        for (const auto& identity : names) {
            ServiceKind kind = ServiceKind::Special;
            if (KernelMemory::supports(identity)) kind = ServiceKind::KernelMemory;
            else if (KernelClock::supports(identity)) kind = ServiceKind::KernelClock;
            else if (UserService::supports(identity)) kind = ServiceKind::UserService;
            else if (KernelSemaphore::supports(identity)) kind = ServiceKind::KernelSemaphore;
            else if (KernelThread::supports(identity)) kind = ServiceKind::KernelThread;
            else if (KernelFile::supports(identity)) kind = ServiceKind::KernelFile;
            else if (KernelEvent::supports(identity)) kind = ServiceKind::KernelEvent;
            else if (OfflineNetwork::supports(identity)) kind = ServiceKind::OfflineNetwork;
            else if (SystemService::supports(identity)) kind = ServiceKind::SystemService;
            else if (LocalNp::supports(identity)) kind = ServiceKind::LocalNp;
            else if (AppContent::supports(identity)) kind = ServiceKind::AppContent;
            else if (LocalPlayGo::supports(identity)) kind = ServiceKind::LocalPlayGo;
            else if (KeyboardPad::supports(identity)) kind = ServiceKind::KeyboardPad;
            else if (SaveData::supports(identity)) kind = ServiceKind::SaveData;
            else if (VirtualPortal::supports(identity)) kind = ServiceKind::VirtualPortal;
            else if (EmptyUsbBus::supports(identity)) kind = ServiceKind::EmptyUsbBus;
            else if (SkyGpu::supports(identity)) kind = ServiceKind::SkyGpu;
            else if (KernelSync::supports(identity)) kind = ServiceKind::KernelSync;
            service_kinds.push_back(kind);
            using B = FrameProfile::Bucket;
            profile_buckets.push_back(kind == ServiceKind::SkyGpu ? B::Gpu :
                kind == ServiceKind::KernelSync || kind == ServiceKind::KernelSemaphore || kind == ServiceKind::KernelEvent ? B::Sync :
                kind == ServiceKind::KernelClock ? B::Clock :
                kind == ServiceKind::KernelFile || kind == ServiceKind::SaveData ? B::File : B::Other);
            // sceVideoOutSubmitFlip and the two sceGnmSubmitAndFlip variants end a guest frame.
            ends_frame.push_back(identity == "U46NwOiJpys#libSceVideoOut#libSceVideoOut" ||
                identity == "xbxNatawohc#libSceGnmDriver#libSceGnmDriver" ||
                identity == "Ga6r7H6Y0RI#libSceGnmDriver#libSceGnmDriver");
            stack_counts.push_back(std::max(SkyGpu::stack_arguments(identity),VirtualPortal::stack_arguments(identity)));
        }
        auto* bytes = static_cast<unsigned char*>(code.value);
        for (std::size_t i = 0; i < names.size(); ++i) {
            weak.push_back((types[i] & 0x80) != 0);
            types[i] &= 0x7f;
            if (types[i] > 2) throw std::runtime_error("unsupported diagnostic import type");
            auto* thunk = bytes + i * 32;
            std::fill(thunk, thunk + 32, 0xcc);
            // movabs r10,index; movabs rax,bridge; jmp rax.
            thunk[0] = 0x49; thunk[1] = 0xba;
            const auto id = static_cast<std::uint64_t>(i);
            const auto bridge = reinterpret_cast<std::uintptr_t>(&sky_guest_call_bridge);
            std::memcpy(thunk + 2, &id, 8);
            thunk[10] = 0x48; thunk[11] = 0xb8;
            std::memcpy(thunk + 12, &bridge, 8);
            thunk[20] = 0xff; thunk[21] = 0xe0;
        }
        if (!SkyHost::protect(reinterpret_cast<std::uintptr_t>(code.value), code.size,
                              SkyHost::ProtRead | SkyHost::ProtExec))
            throw std::runtime_error("cannot protect diagnostic import thunks");
    }

    [[noreturn]] static SKY_SYSV_ABI void trap(std::uint64_t id) {
        if (!active || id >= active->names.size()) std::_Exit(126);
        const auto name = escaped(active->names[static_cast<std::size_t>(id)]);
        SkyHost::diagnostic_printf("{\"event\":\"unsupported-import\",\"index\":%llu,\"name\":%s,\"guest_executed\":true}\n",
                static_cast<unsigned long long>(id), name.c_str());
        std::_Exit(20);
    }

    static SKY_SYSV_ABI std::uint64_t call(std::uint64_t id, const std::uint64_t* registers, const std::uint64_t* stack_arguments) {
        if (!active || id >= active->names.size()) std::_Exit(126);
        const auto& identity = active->names[static_cast<std::size_t>(id)];
        std::array<std::uint64_t, 12> arguments{};
        std::copy_n(registers, 6, arguments.data());
        const auto stacked = active->stack_counts[id];
        if (stacked > 6) std::_Exit(126);
        std::copy_n(stack_arguments, stacked, arguments.data() + 6);
        const auto* args = arguments.data();
        static const bool trace_waits = [] {
            const auto* value = std::getenv("SKY_WAIT_TRACE");
            return value && std::strcmp(value, "1") == 0;
        }();
        const bool timed_wait = trace_waits &&
            (identity == "1jfXLRVzisc#libkernel#libkernel" ||
             identity == "j6RaAUlaLv0#libSceVideoOut#libSceVideoOut" ||
             identity == "fzyMKs9kim0#libkernel#libkernel");
        const auto wait_started = timed_wait ? std::chrono::steady_clock::now()
                                            : std::chrono::steady_clock::time_point{};
        const std::uint64_t profile_started = FrameProfile::enabled() ? FrameProfile::now_ns() : 0;
        try {
            std::uint64_t result = 0;
            // Frequent providers are disjoint from startup special services.
            // The immutable category avoids traversing their string predicates.
            if (active->service_kinds[id] == ServiceKind::SkyGpu) result = SkyGpu::call(identity,args);
            else if (active->service_kinds[id] == ServiceKind::KernelClock) result = active->kernel_clock.call(identity,args);
            else if (active->service_kinds[id] == ServiceKind::KernelSync) result = active->kernel_sync.call(identity,args);
            else if (identity == "959qrazPIrg#libkernel#libkernel") result = active->boot.process_param;
            else if (identity == "aI+OeCz8xrQ#libkernel#libkernel") result = GuestThreadContext::current()->handle();
            else if (identity == "9BcDykPmo1I#libkernel#libkernel") result = reinterpret_cast<std::uintptr_t>(GuestThreadContext::current()->error_pointer());
            else if (identity == "EI-5-jlq2dE#libkernel#libkernel") result = SkyHost::current_thread_id();
            else if (identity == "FzEWeYnAFlI#libSceContentExport#libSceContentExport") result = 0x809d3fff;
            else if (identity == "+KDWny9Y-6k#libSceContentExport#libSceContentExport") result = 0x809d3004;
            // sceVideoRecordingGetStatus: this runtime has no recording backend.
            // Report UNSUPPORTED without fabricating or writing a status value.
            else if (identity == "fZJQzFK4Gv4#libSceVideoRecording#libSceVideoRecording") result = 0x80a80008;
            // sceVideoRecordingStop: recording is unavailable, including stop.
            else if (identity == "OOFxrMY+mfI#libSceVideoRecording#libSceVideoRecording") result = 0x80a80008;
            // sceVideoRecordingClose: no recording resource was opened here.
            else if (identity == "KHvkPQJDMLk#libSceVideoRecording#libSceVideoRecording") result = 0x80a80008;
            else if (identity == "g8cM39EUZ6o#libSceSysmodule#libSceSysmodule" ||
                     identity == "fMP5NHUOaMk#libSceSysmodule#libSceSysmodule" ||
                     identity == "eR2bZFAAU0Q#libSceSysmodule#libSceSysmodule") {
                // No public optional system-module backend has been activated yet.
                // These known modules are unavailable, rather than successfully loaded.
                switch (static_cast<std::uint16_t>(args[0])) {
                    case 0xb7: {
                        std::lock_guard guard(active->modules_lock);
                        if (identity == "g8cM39EUZ6o#libSceSysmodule#libSceSysmodule") ++active->usb_references;
                        else if (!active->usb_references) result = 0x805a1001;
                        else if (identity == "eR2bZFAAU0Q#libSceSysmodule#libSceSysmodule") --active->usb_references;
                        break;
                    }
                    case 0x83: {
                        std::lock_guard guard(active->modules_lock);
                        if (!active->local_playgo.available()) { result = 0x805a1001; break; }
                        if (identity == "g8cM39EUZ6o#libSceSysmodule#libSceSysmodule") ++active->playgo_references;
                        else if (!active->playgo_references) result = 0x805a1001;
                        else if (identity == "eR2bZFAAU0Q#libSceSysmodule#libSceSysmodule") --active->playgo_references;
                        break;
                    }
                    // 0xab is libSceWebBrowserDialog (pinned sysmodule table).
                    // No browser-dialog backend is available; report that to
                    // the caller instead of terminating on a known module ID.
                    case 0x80: case 0x85: case 0x9d: case 0xa0: case 0xa6: case 0xab: case 0xad: case 0xb4: case 0xb6:
                        result = 0x805a1001; break;
                    default: throw std::runtime_error("unregistered system module ID " + std::to_string(args[0]));
                }
            }
            else if (identity == "6xVpy0Fdq+I#libkernel#libkernel")
                result = GuestThreadContext::current()->signal_mask(static_cast<int>(args[0]),
                    reinterpret_cast<const void*>(args[1]), reinterpret_cast<void*>(args[2]));
            else if (identity == "ZkZhskCPXFw#libSceSaveData#libSceSaveData") {
                result = active->save_data.call(identity,args);
            }
            else if (identity == "uoUpLGNkygk#libSceCommonDialog#libSceCommonDialog") {
                if (active->common_dialog_initialized.exchange(true)) result = 0x80b80004;
            }
            else if (identity == "p5EcQeEeJAE#libkernel#libkernel") active->heap_api = args[0];
            else if (identity == "vNe1w4diLCs#libkernel#libkernel") {
                if (!args[0]) throw std::runtime_error("null TLS index");
                const auto* index = reinterpret_cast<const std::uint64_t*>(args[0]);
                result = GuestThreadContext::current()->tls_address(index[0], index[1]);
            } else if (active->service_kinds[id] == ServiceKind::KernelMemory) result = SkyGpu::enabled() ? SkyGpu::memory_call(identity, args) : active->kernel_memory.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::KernelClock) result = active->kernel_clock.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::UserService) result = active->user_service.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::KernelSemaphore) result = active->kernel_semaphore.call(identity, args, active->kernel_thread.current_priority());
            else if (active->service_kinds[id] == ServiceKind::KernelThread) result = active->kernel_thread.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::KernelFile) {
                const bool read = identity == "Cg4srZ6TKbU#libkernel#libkernel" || identity == "+r3rMFwItV4#libkernel#libkernel";
                if (read && args[2] <= 1024ull * 1024 * 1024) SkyGpu::prepare_cpu_write(args[1], args[2]);
                result = active->kernel_file.call(identity, args);
                if (read && static_cast<std::int64_t>(result) > 0) SkyGpu::note_cpu_write(args[1], result);
            }
            else if (active->service_kinds[id] == ServiceKind::KernelEvent) result = active->kernel_event.call(identity, args, active->kernel_thread.current_priority());
            else if (active->service_kinds[id] == ServiceKind::OfflineNetwork) result = active->offline_network.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::SystemService) result = active->system_service.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::LocalNp) result = active->local_np.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::AppContent) result = active->app_content.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::LocalPlayGo) result = active->local_playgo.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::KeyboardPad) result = active->keyboard_pad.call(identity, args, SkyGpu::captures_input());
            else if (active->service_kinds[id] == ServiceKind::SaveData) result = active->save_data.call(identity,args);
            else if (active->service_kinds[id] == ServiceKind::VirtualPortal) result = VirtualPortal::call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::EmptyUsbBus) result = active->empty_usb_bus.call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::SkyGpu) result = SkyGpu::call(identity, args);
            else if (active->service_kinds[id] == ServiceKind::KernelSync) result = active->kernel_sync.call(identity, args);
            else {
                const bool suspend = active->suspend_unsupported_network_workers &&
                    std::this_thread::get_id() != active->main_native_thread &&
                    (identity.find("#libSceNet#") != std::string::npos || identity.find("#libSceNetCtl#") != std::string::npos);
                SkyHost::diagnostic_printf("{\"event\":\"unsupported-import\",\"index\":%llu,\"name\":%s,\"arguments\":[%llu,%llu,%llu,%llu,%llu,%llu],\"guest_executed\":true}\n",
                    static_cast<unsigned long long>(id), escaped(identity).c_str(),
                    static_cast<unsigned long long>(args[0]), static_cast<unsigned long long>(args[1]),
                    static_cast<unsigned long long>(args[2]), static_cast<unsigned long long>(args[3]),
                    static_cast<unsigned long long>(args[4]), static_cast<unsigned long long>(args[5]));
                if (suspend) {
                    SkyHost::diagnostic_printf("{\"event\":\"diagnostic-network-worker-suspended\",\"index\":%llu,\"call_returned\":false}\n",
                        static_cast<unsigned long long>(id));
                    SkyHost::suspend_diagnostic_worker();
                }
                std::_Exit(20);
            }
            if (profile_started) {
                FrameProfile::record(active->profile_buckets[id], FrameProfile::now_ns() - profile_started);
                if (active->ends_frame[id]) FrameProfile::frame();
            }
            // Opt-in diagnostic (SKY_SERVICE_COUNTS=1): every 10 s, log the
            // most-called services in that interval, to find a spinning wait.
            static const bool count_services = [] {
                const auto* value = std::getenv("SKY_SERVICE_COUNTS");
                return value && std::strcmp(value, "1") == 0;
            }();
            if (count_services) {
                static std::vector<std::atomic<std::uint64_t>> totals(active->names.size());
                static std::once_flag reporter;
                totals[static_cast<std::size_t>(id)].fetch_add(1, std::memory_order_relaxed);
                std::call_once(reporter, [] {
                    std::thread([] {
                        std::vector<std::uint64_t> last(totals.size());
                        for (;;) {
                            std::this_thread::sleep_for(std::chrono::seconds(10));
                            std::vector<std::pair<std::uint64_t, std::size_t>> deltas;
                            for (std::size_t i = 0; i < totals.size(); ++i) {
                                const auto now = totals[i].load(std::memory_order_relaxed);
                                if (now != last[i]) deltas.emplace_back(now - last[i], i);
                                last[i] = now;
                            }
                            std::sort(deltas.rbegin(), deltas.rend());
                            std::string line = "{\"event\":\"service-counts\",\"top\":[";
                            for (std::size_t k = 0; k < std::min<std::size_t>(deltas.size(), 10); ++k)
                                line += (k ? "," : "") + std::string("{\"name\":") + escaped(active->names[deltas[k].second]) +
                                        ",\"calls\":" + std::to_string(deltas[k].first) + "}";
                            line += "]}\n";
                            SkyHost::diagnostic_printf("%s", line.c_str());
                        }
                    }).detach();
                });
            }
            // The import table is fixed before guest threads start. Once the
            // four startup samples are logged, normal calls need neither a
            // string allocation nor the shared logging mutex.
            std::atomic_ref<unsigned> counter(active->service_calls[static_cast<std::size_t>(id)]);
            unsigned calls;
            if (timed_wait) calls = counter.fetch_add(1, std::memory_order_relaxed) + 1;
            else {
                auto previous = counter.load(std::memory_order_relaxed);
                do {
                    if (previous >= 4) return result;
                } while (!counter.compare_exchange_weak(previous, previous + 1, std::memory_order_relaxed));
                calls = previous + 1;
            }
            if (calls > 4 && calls % 300 != 0) return result;
            const auto name = escaped(identity);
            std::lock_guard log_lock(active->logging);
            if (timed_wait && (calls <= 4 || calls % 300 == 0)) {
                // guest_start.S passes the first stack argument at entry RSP+8;
                // the preceding word is the guest call's return address.
                const auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(
                    std::chrono::steady_clock::now() - wait_started).count();
                SkyHost::diagnostic_printf(
                    "{\"event\":\"guest-wait\",\"name\":%s,\"caller_return\":%llu,\"argument0\":%llu,\"elapsed_us\":%lld,\"calls\":%llu}\n",
                    name.c_str(), static_cast<unsigned long long>(stack_arguments[-1]),
                    static_cast<unsigned long long>(args[0]), static_cast<long long>(elapsed),
                    static_cast<unsigned long long>(calls));
            }
            if (calls <= 4)
                SkyHost::diagnostic_printf("{\"event\":\"service-return\",\"name\":%s,\"result\":%llu}\n",
                        name.c_str(), static_cast<unsigned long long>(result));
            return result;
        } catch (const std::exception& error) {
            SkyHost::diagnostic_printf("{\"event\":\"service-error\",\"message\":%s}\n", escaped(error.what()).c_str());
            std::_Exit(72);
        }
    }

    [[noreturn]] static void fault(const SkyHost::Fault& fault) noexcept {
        const auto pc = static_cast<unsigned long long>(fault.cpu.pc);
        const auto address = fault.address;
        SkyHost::diagnostic_printf("{\"event\":\"guest-fault\",\"signal\":%u,\"pc\":%llu,\"address\":%llu,\"guest_executed\":true}\n",
                fault.native_code, pc, static_cast<unsigned long long>(address));
        SkyHost::ModuleOwner owner;
        if (SkyHost::module_owner(pc,owner)) {
            SkyHost::diagnostic_printf("{\"event\":\"fault-host-owner\",\"file\":%s,\"offset\":%llu}\n",
                escaped(owner.file).c_str(), pc - owner.base);
        }
        auto* thread = GuestThreadContext::current();
        SkyHost::diagnostic_printf("{\"event\":\"fault-registers\",\"rsp\":%llu,\"rax\":%llu,\"rdi\":%llu,\"rsi\":%llu,\"error\":%llu,\"stack_guard\":%s}\n",
            static_cast<unsigned long long>(fault.cpu.reg(SkyHost::Gpr::rsp)),
            static_cast<unsigned long long>(fault.cpu.reg(SkyHost::Gpr::rax)),
            static_cast<unsigned long long>(fault.cpu.reg(SkyHost::Gpr::rdi)),
            static_cast<unsigned long long>(fault.cpu.reg(SkyHost::Gpr::rsi)),
            static_cast<unsigned long long>(fault.native_error),
            thread && thread->is_stack_guard(address) ? "true" : "false");
        if (active) {
            const auto start = reinterpret_cast<std::uintptr_t>(active->guards.value);
            if (address >= start && address - start < active->guards.size) {
                const auto id = (address - start) / active->page;
                if (id < active->names.size()) {
                    const auto name = escaped(active->names[id]);
                    SkyHost::diagnostic_printf("{\"event\":\"unresolved-data-import\",\"index\":%zu,\"name\":%s}\n", id, name.c_str());
                }
            }
        }
        std::_Exit(70);
    }
};

GuestRuntime::Impl* GuestRuntime::Impl::active = nullptr;

GuestRuntime::GuestRuntime(const std::vector<std::string>& names, const std::vector<unsigned char>& types)
    : impl_(std::make_unique<Impl>(names, types)) {}
GuestRuntime::~GuestRuntime() = default;

std::uint64_t GuestRuntime::address(std::uint64_t index) const {
    if (index >= impl_->names.size()) throw std::runtime_error("diagnostic import index outside table");
    const auto i = static_cast<std::size_t>(index);
    if (const auto* data = impl_->kernel_data.resolve(impl_->names[i], impl_->types[i]))
        return reinterpret_cast<std::uintptr_t>(data);
    if (impl_->weak[i] && !KernelSync::supports(impl_->names[i]) &&
        !KernelMemory::supports(impl_->names[i]) && !KernelClock::supports(impl_->names[i]) &&
        !UserService::supports(impl_->names[i]) && !KernelSemaphore::supports(impl_->names[i]) && !KernelThread::supports(impl_->names[i]) &&
        !KernelFile::supports(impl_->names[i]) && !KernelEvent::supports(impl_->names[i]) &&
        !OfflineNetwork::supports(impl_->names[i]) && !SystemService::supports(impl_->names[i]) &&
        !LocalNp::supports(impl_->names[i]) && !AppContent::supports(impl_->names[i]) &&
        !LocalPlayGo::supports(impl_->names[i]) && !KeyboardPad::supports(impl_->names[i]) &&
        !SaveData::supports(impl_->names[i]) && !VirtualPortal::supports(impl_->names[i]) && !EmptyUsbBus::supports(impl_->names[i]) && !SkyGpu::supports(impl_->names[i]) && !startup_service(impl_->names[i])) return 0;
    auto* base = static_cast<unsigned char*>(impl_->types[i] == 2 ? impl_->code.value : impl_->guards.value);
    return reinterpret_cast<std::uintptr_t>(base + i * (impl_->types[i] == 2 ? 32 : impl_->page));
}

[[noreturn]] void GuestRuntime::enter(std::uint64_t entry, const SkyBootPlan& boot, const std::string& game_root) {
    impl_->boot = boot;
    impl_->main_native_thread = std::this_thread::get_id();
    const auto* suspend = std::getenv("SKY_SUSPEND_UNSUPPORTED_NET_WORKERS");
    impl_->suspend_unsupported_network_workers = suspend && std::strcmp(suspend, "1") == 0;
    GuestThreadContext thread(boot);
    impl_->kernel_file.configure(game_root);
    impl_->app_content.configure(game_root);
    if(impl_->app_content.title_id().starts_with("CUSA")) {
        const auto* save_root=std::getenv("SKY_SAVE_DATA_ROOT");
        const auto default_save = SkyHost::default_save_root();
        impl_->save_data.configure(save_root && *save_root?std::filesystem::path(save_root):default_save,impl_->app_content.title_id());
    }
    impl_->local_playgo.configure(game_root);
    GameHooks::configure(impl_->app_content.title_id(), game_root);
    SkyGpu::configure(impl_->app_content.title_id(), impl_->app_content.system_version(), impl_->app_content.attributes());
    SkyGpu::bind_keyboard(&impl_->keyboard_pad);
    if (VirtualPortal::enabled()) SkyGpu::bind_portal(
        +[](const char* path){VirtualPortal::load(path);}, +[]{VirtualPortal::remove();},
        +[](const char* path){VirtualPortal::load_trap(path);}, +[]{VirtualPortal::remove_trap();});
    impl_->kernel_thread.configure(boot, [this](GuestThreadContext& context) {
        impl_->kernel_sync.finish_thread([&context](std::uint64_t function, std::uint64_t argument) {
            (void)context.run(function, reinterpret_cast<const void*>(argument));
        });
    });
    impl_->kernel_thread.attach_main(thread);
    Impl::active = impl_.get();
    FrameProfile::configure();
    FrameProfile::thread_started(true);
    if (sky_guest_configure_trap(&Impl::trap) || sky_guest_configure_call(&Impl::call) ||
        !SkyHost::install_runtime_faults(&Impl::fault,&SkyGpu::handle_fault,&SkyGpu::handle_fault))
        throw std::runtime_error("guest diagnostics already active");
    struct { std::uint64_t argc; const char* argv[2]; } startup{1, {"/app0/eboot.bin", nullptr}};
    SkyHost::diagnostic_printf("{\"event\":\"entry-attempt\",\"entry\":%llu,\"mode\":\"single-thread-diagnostic\"}\n",
            static_cast<unsigned long long>(entry));
    std::uint64_t returned = 0;
    for (const auto& module : boot.modules) {
        if (module.id == 1 || !module.init) continue;
        SkyHost::diagnostic_printf("{\"event\":\"module-init-attempt\",\"module\":%llu,\"entry\":%llu}\n",
                static_cast<unsigned long long>(module.id), static_cast<unsigned long long>(module.init));
        returned = thread.run(module.init, nullptr);
        const int status = 0;
        SkyHost::diagnostic_printf("{\"event\":\"module-init-returned\",\"module\":%llu,\"status\":%d,\"result\":%llu}\n",
                static_cast<unsigned long long>(module.id), status, static_cast<unsigned long long>(returned));
        if (status || static_cast<std::uint32_t>(returned)) std::_Exit(73);
    }
    returned = thread.run(entry, &startup);
    const int status = 0;
    SkyHost::diagnostic_printf("{\"event\":\"entry-returned\",\"bridge_status\":%d,\"return_value\":%llu}\n",
            status, static_cast<unsigned long long>(returned));
    std::_Exit(status == 0 ? 0 : 71);
}

// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "host_memory.hpp"
#include <windows.h>
#include <algorithm>
#include <cstdio>
#include <limits>
#include <mutex>
#include <vector>

// Sections stand in for the memfd and VirtualAlloc for anonymous memory. Views
// need 64 KiB-aligned addresses and offsets; callers place by map_granularity().
// A request Windows cannot meet exactly reports Failed, never a nearby address.
namespace SkyHost {
namespace {
DWORD page_protection(int protection) noexcept {
    if (protection & ProtExec)
        return (protection & ProtWrite) ? PAGE_EXECUTE_READWRITE
             : (protection & ProtRead) ? PAGE_EXECUTE_READ : PAGE_EXECUTE;
    if (protection & ProtWrite) return PAGE_READWRITE;
    if (protection & ProtRead) return PAGE_READONLY;
    return PAGE_NOACCESS;
}
bool occupied(std::uint64_t address, std::uint64_t size) noexcept {
    for (std::uint64_t at = address; at < address + size;) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<void*>(at), &info, sizeof(info))) return false;
        if (info.State != MEM_FREE) return true;
        at = reinterpret_cast<std::uint64_t>(info.BaseAddress) + info.RegionSize;
    }
    return false;
}
// Diagnostic only: names what holds an exact-address range that could not be
// mapped (VirtualQuery base/allocation/state/type), so the cause is recorded.
void describe_range(const char* why, std::uint64_t address, std::uint64_t size) noexcept {
    std::fprintf(stderr, "{\"event\":\"guest-map-failure\",\"why\":\"%s\",\"address\":\"%#llx\",\"size\":\"%#llx\",\"error\":%lu,\"regions\":[",
                 why, static_cast<unsigned long long>(address), static_cast<unsigned long long>(size), GetLastError());
    bool first = true;
    for (std::uint64_t at = address; at < address + size;) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<void*>(at), &info, sizeof(info))) break;
        const auto base = reinterpret_cast<std::uint64_t>(info.BaseAddress);
        std::fprintf(stderr, "%s{\"base\":\"%#llx\",\"size\":\"%#llx\",\"allocation\":\"%#llx\",\"state\":\"%s\",\"type\":\"%s\",\"protect\":\"%#lx\"}",
                     first ? "" : ",", static_cast<unsigned long long>(base), static_cast<unsigned long long>(info.RegionSize),
                     static_cast<unsigned long long>(reinterpret_cast<std::uint64_t>(info.AllocationBase)),
                     info.State == MEM_FREE ? "free" : info.State == MEM_RESERVE ? "reserve" : "commit",
                     info.Type == MEM_IMAGE ? "image" : info.Type == MEM_MAPPED ? "mapped" : info.Type == MEM_PRIVATE ? "private" : "none",
                     info.Protect);
        first = false;
        at = base + info.RegionSize;
    }
    std::fprintf(stderr, "]}\n");
}
MapStatus failure(std::uint64_t address, std::uint64_t size) noexcept {
    if (address < 0x4400000 && address + size > 0x400000) describe_range("exact-map", address, size);
    return occupied(address, size) ? MapStatus::Occupied : MapStatus::Failed;
}

// PS4 executables load at fixed low addresses (0x400000 up; Trap Team's image
// is about 22 MiB). Windows can put the initial heap or stack there before any
// host code runs, so run_with_guest_window_held reserves this window in a
// suspended child. The child adopts that reservation here; a guest mapping
// inside it takes its range back and re-reserves what is left.
// Windows also hands out ordinary host allocations (heaps, renderer, driver)
// bottom-up, which otherwise fills the low 2 GiB that guest stacks and TLS
// need. So the child also holds a guest-thread arena right after the image
// window, as a second, separate reservation that is never released:
// allocate_low_guest commits 64 KiB blocks inside it and free_low_guest
// decommits them. Nothing else can land there, and image mappings (which
// release and re-reserve parts of the image window) never touch it.
constexpr std::uint64_t kLowGuestBegin = 0x400000, kLowGuestEnd = 0x4400000;
constexpr std::uint64_t kThreadArenaBegin = kLowGuestEnd, kThreadArenaEnd = 0x24400000;
constexpr std::uint64_t kArenaBlock = 0x10000, kArenaBlocks = (kThreadArenaEnd - kThreadArenaBegin) / kArenaBlock;
constexpr char kHeldVariable[] = "SKY_GUEST_WINDOW_HELD";
struct LowGuestHold {
    std::mutex lock;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> held; // base, size
    bool arena = false;                                        // arena reservation adopted
    std::vector<bool> arena_used = std::vector<bool>(kArenaBlocks, false);
    void reserve(std::uint64_t begin, std::uint64_t end) noexcept {
        for (std::uint64_t at = begin; at < end;) {
            MEMORY_BASIC_INFORMATION info{};
            if (!VirtualQuery(reinterpret_cast<void*>(at), &info, sizeof(info))) return;
            const auto base = reinterpret_cast<std::uint64_t>(info.BaseAddress);
            auto next = base + info.RegionSize;
            if (info.State == MEM_FREE) {
                // Reservations start on the 64 KiB allocation granularity.
                const auto start = (std::max(at, base) + 0xffff) & ~std::uint64_t{0xffff};
                const auto stop = std::min(next, end) & ~std::uint64_t{0xffff};
                if (stop > start && VirtualAlloc(reinterpret_cast<void*>(start), stop - start, MEM_RESERVE, PAGE_NOACCESS))
                    held.emplace_back(start, stop - start);
            }
            at = next;
        }
    }
    LowGuestHold() noexcept {
        if (!GetEnvironmentVariableA(kHeldVariable, nullptr, 0)) return;
        MEMORY_BASIC_INFORMATION info{};
        if (VirtualQuery(reinterpret_cast<void*>(kLowGuestBegin), &info, sizeof(info)) && info.State == MEM_RESERVE &&
            reinterpret_cast<std::uint64_t>(info.AllocationBase) == kLowGuestBegin &&
            reinterpret_cast<std::uint64_t>(info.BaseAddress) + info.RegionSize >= kLowGuestEnd)
            held.emplace_back(kLowGuestBegin, kLowGuestEnd - kLowGuestBegin);
        else describe_range("adopt-window", kLowGuestBegin, kLowGuestEnd - kLowGuestBegin);
        info = {};
        arena = VirtualQuery(reinterpret_cast<void*>(kThreadArenaBegin), &info, sizeof(info)) && info.State == MEM_RESERVE &&
            reinterpret_cast<std::uint64_t>(info.AllocationBase) == kThreadArenaBegin &&
            reinterpret_cast<std::uint64_t>(info.BaseAddress) + info.RegionSize >= kThreadArenaEnd;
        if (!arena) describe_range("adopt-arena", kThreadArenaBegin, kThreadArenaEnd - kThreadArenaBegin);
    }
    // Releases held reservations overlapping the request; returns the span
    // released so the caller can re-reserve what the mapping leaves free.
    std::pair<std::uint64_t, std::uint64_t> release(std::uint64_t address, std::uint64_t size) noexcept {
        std::uint64_t low = address, high = address + size;
        bool any = false;
        for (auto it = held.begin(); it != held.end();) {
            if (it->first < address + size && address < it->first + it->second) {
                VirtualFree(reinterpret_cast<void*>(it->first), 0, MEM_RELEASE);
                low = std::min(low, it->first);
                high = std::max(high, it->first + it->second);
                it = held.erase(it);
                any = true;
            } else ++it;
        }
        return any ? std::pair{low, high} : std::pair{address, address};
    }
};
// Constructed before ordinary static objects and long before main's threads.
__attribute__((init_priority(101))) LowGuestHold low_guest;

template <typename Map>
MapStatus map_low_guest(std::uint64_t address, std::uint64_t size, Map&& map) noexcept {
    if (address >= kLowGuestEnd || address + size <= kLowGuestBegin) return map();
    std::lock_guard guard(low_guest.lock);
    const auto [low, high] = low_guest.release(address, size);
    const auto status = map();
    if (high > low) low_guest.reserve(std::max(low, kLowGuestBegin), std::min(high, kLowGuestEnd));
    return status;
}
}

void* allocate_low_guest(std::size_t size, bool inaccessible) noexcept {
    if (!size || size > kThreadArenaEnd - kThreadArenaBegin) return nullptr;
    const std::uint64_t blocks = (size + kArenaBlock - 1) / kArenaBlock;
    std::lock_guard guard(low_guest.lock);
    if (!low_guest.arena) return nullptr;
    auto& used = low_guest.arena_used;
    // First fit over 64 KiB blocks; the reservation itself is never released.
    for (std::uint64_t first = 0, run = 0; first + run < kArenaBlocks;) {
        if (used[first + run]) { first += run + 1; run = 0; continue; }
        if (++run < blocks) continue;
        auto* address = reinterpret_cast<void*>(kThreadArenaBegin + first * kArenaBlock);
        // Commit inside the reservation: fresh pages are zero-filled.
        if (VirtualAlloc(address, size, MEM_COMMIT, inaccessible ? PAGE_NOACCESS : PAGE_READWRITE) != address)
            return nullptr;
        for (std::uint64_t i = 0; i < blocks; ++i) used[first + i] = true;
        return address;
    }
    return nullptr;
}

bool free_low_guest(void* data, std::size_t size) noexcept {
    const auto base = reinterpret_cast<std::uint64_t>(data);
    if (!data || base < kThreadArenaBegin || base >= kThreadArenaEnd || (base - kThreadArenaBegin) % kArenaBlock) return false;
    std::lock_guard guard(low_guest.lock);
    if (!low_guest.arena) return false;
    const std::uint64_t first = (base - kThreadArenaBegin) / kArenaBlock;
    const std::uint64_t blocks = std::min<std::uint64_t>((size + kArenaBlock - 1) / kArenaBlock, kArenaBlocks - first);
    // Decommit only: the range stays reserved for later guest threads.
    if (!VirtualFree(data, blocks * kArenaBlock, MEM_DECOMMIT)) return false;
    for (std::uint64_t i = 0; i < blocks; ++i) low_guest.arena_used[first + i] = false;
    return true;
}

std::uint64_t map_granularity() noexcept {
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    return info.dwAllocationGranularity;
}

std::uint64_t memory_page_size() noexcept {
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    return info.dwPageSize;
}
bool protect(std::uint64_t address, std::uint64_t size, int protection) noexcept {
    const auto page = memory_page_size();
    if (!page || !size || address % page || size % page ||
        size > std::numeric_limits<std::uint64_t>::max() - address || (protection & ~7)) return false;
    DWORD previous = 0;
    if (!VirtualProtect(reinterpret_cast<void*>(address), size, page_protection(protection), &previous)) return false;
    return !(protection & ProtExec) || FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<void*>(address), size);
}

SharedMemory::~SharedMemory() { if (handle_) CloseHandle(handle_); }

bool SharedMemory::open(const char*, std::uint64_t size) noexcept {
    if (handle_) return true;
    // SEC_RESERVE: the pool's full size is not charged against the commit limit
    // until a view commits its own pages.
    handle_ = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE | SEC_RESERVE,
                                 static_cast<DWORD>(size >> 32), static_cast<DWORD>(size), nullptr);
    return handle_ != nullptr;
}

bool SharedMemory::is_open() const noexcept { return handle_ != nullptr; }

MapStatus SharedMemory::map(std::uint64_t address, std::uint64_t size, std::uint64_t offset, int protection) const noexcept {
    return map_low_guest(address, size, [&] { return map_exact(address, size, offset, protection); });
}

MapStatus SharedMemory::map_exact(std::uint64_t address, std::uint64_t size, std::uint64_t offset, int protection) const noexcept {
    const auto granularity = map_granularity();
    if (!handle_ || !size || size > std::numeric_limits<std::uint64_t>::max() - address ||
        address % granularity || offset % granularity) return MapStatus::Failed;
    void* view = MapViewOfFileEx(handle_, FILE_MAP_ALL_ACCESS, static_cast<DWORD>(offset >> 32),
                                 static_cast<DWORD>(offset), size, reinterpret_cast<void*>(address));
    if (!view) return failure(address, size);
    if (reinterpret_cast<std::uintptr_t>(view) != address) {
        UnmapViewOfFile(view);
        return MapStatus::Failed;
    }
    DWORD previous = 0;
    if (!VirtualAlloc(view, size, MEM_COMMIT, PAGE_READWRITE) ||
        !VirtualProtect(view, size, page_protection(protection), &previous)) {
        UnmapViewOfFile(view);
        return MapStatus::Failed;
    }
    return MapStatus::Mapped;
}

MapStatus map_anonymous(std::uint64_t address, std::uint64_t size, int protection) noexcept {
    if (!size || size > std::numeric_limits<std::uint64_t>::max() - address ||
        address % map_granularity()) return MapStatus::Failed;
    return map_low_guest(address, size, [&]() -> MapStatus {
        void* memory = VirtualAlloc(reinterpret_cast<void*>(address), size, MEM_RESERVE | MEM_COMMIT,
                                    page_protection(protection));
        if (!memory) return failure(address, size);
        if (reinterpret_cast<std::uintptr_t>(memory) != address) {
            VirtualFree(memory, 0, MEM_RELEASE);
            return MapStatus::Failed;
        }
        return MapStatus::Mapped;
    });
}

bool unmap(std::uint64_t address, std::uint64_t, bool shared) noexcept {
    auto* base = reinterpret_cast<void*>(address);
    return shared ? UnmapViewOfFile(base) != 0 : VirtualFree(base, 0, MEM_RELEASE) != 0;
}
bool run_with_guest_window_held(int& exit_code) noexcept {
    if (GetEnvironmentVariableA(kHeldVariable, nullptr, 0)) return false;
    wchar_t module[32768];
    const DWORD length = GetModuleFileNameW(nullptr, module, 32768);
    if (!length || length >= 32768) return false;
    if (!SetEnvironmentVariableA(kHeldVariable, "1")) return false;
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup); // STARTUPINFOEXW: required with EXTENDED_STARTUPINFO_PRESENT
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.StartupInfo.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.StartupInfo.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    // Without high-entropy VA, bottom-up ASLR scatters the child's initial
    // stack, PEB/TEB and early section views across the low addresses, so they
    // usually land inside the window before it can be reserved. Turning
    // bottom-up randomization off for the child puts them at the lowest free
    // addresses, below 0x400000. If policy refuses it, fall back to retries.
    DWORD64 policy = PROCESS_CREATION_MITIGATION_POLICY_BOTTOM_UP_ASLR_ALWAYS_OFF;
    SIZE_T attribute_size = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attribute_size);
    std::vector<unsigned char> attributes(attribute_size);
    auto* list = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributes.data());
    bool use_policy = attribute_size && InitializeProcThreadAttributeList(list, 1, 0, &attribute_size) &&
        UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY, &policy, sizeof(policy), nullptr, nullptr);
    // The initial stack/PEB can still land in the window at creation: retry
    // with a fresh child (its layout is randomized again).
    for (int attempt = 0; attempt < 16; ++attempt) {
        std::vector<wchar_t> command(GetCommandLineW(), GetCommandLineW() + wcslen(GetCommandLineW()) + 1);
        PROCESS_INFORMATION child{};
        startup.lpAttributeList = use_policy ? list : nullptr;
        startup.StartupInfo.cb = use_policy ? sizeof(startup) : sizeof(startup.StartupInfo);
        if (!CreateProcessW(module, command.data(), nullptr, nullptr, TRUE,
                            CREATE_SUSPENDED | (use_policy ? EXTENDED_STARTUPINFO_PRESENT : 0),
                            nullptr, nullptr, &startup.StartupInfo, &child)) {
            if (!use_policy) break;
            std::fprintf(stderr, "{\"event\":\"guest-window-hold\",\"result\":\"policy-refused\",\"error\":%lu}\n", GetLastError());
            use_policy = false;
            continue;
        }
        // Two reservations: the image window, and the guest-thread arena after
        // it (kept separate so image mappings never release thread memory).
        const auto window = VirtualAllocEx(child.hProcess, reinterpret_cast<void*>(kLowGuestBegin),
                                           kLowGuestEnd - kLowGuestBegin, MEM_RESERVE, PAGE_NOACCESS);
        const auto arena = window ? VirtualAllocEx(child.hProcess, reinterpret_cast<void*>(kThreadArenaBegin),
                                                   kThreadArenaEnd - kThreadArenaBegin, MEM_RESERVE, PAGE_NOACCESS) : nullptr;
        if (reinterpret_cast<std::uint64_t>(window) != kLowGuestBegin || reinterpret_cast<std::uint64_t>(arena) != kThreadArenaBegin) {
            // Diagnostic: what the fresh suspended child already has in the window.
            const DWORD error = GetLastError();
            for (std::uint64_t at = kLowGuestBegin; at < kThreadArenaEnd;) {
                MEMORY_BASIC_INFORMATION info{};
                if (!VirtualQueryEx(child.hProcess, reinterpret_cast<void*>(at), &info, sizeof(info))) break;
                const auto base = reinterpret_cast<std::uint64_t>(info.BaseAddress);
                if (info.State != MEM_FREE)
                    std::fprintf(stderr, "{\"event\":\"guest-window-child\",\"attempt\":%d,\"error\":%lu,\"base\":\"%#llx\",\"size\":\"%#llx\",\"allocation\":\"%#llx\",\"state\":\"%s\",\"type\":\"%s\"}\n",
                                 attempt, error, static_cast<unsigned long long>(base), static_cast<unsigned long long>(info.RegionSize),
                                 static_cast<unsigned long long>(reinterpret_cast<std::uint64_t>(info.AllocationBase)),
                                 info.State == MEM_RESERVE ? "reserve" : "commit",
                                 info.Type == MEM_IMAGE ? "image" : info.Type == MEM_MAPPED ? "mapped" : "private");
                at = base + info.RegionSize;
            }
            TerminateProcess(child.hProcess, 1);
            CloseHandle(child.hThread);
            CloseHandle(child.hProcess);
            continue;
        }
        // The child handles console interrupts; this process only waits.
        SetConsoleCtrlHandler(nullptr, TRUE);
        ResumeThread(child.hThread);
        CloseHandle(child.hThread);
        if (use_policy) DeleteProcThreadAttributeList(list);
        WaitForSingleObject(child.hProcess, INFINITE);
        DWORD code = 1;
        GetExitCodeProcess(child.hProcess, &code);
        CloseHandle(child.hProcess);
        exit_code = static_cast<int>(code);
        return true;
    }
    // No child could hold the window: carry on here, where an exact mapping
    // that cannot be made still fails with its own message.
    std::fprintf(stderr, "{\"event\":\"guest-window-hold\",\"result\":\"no-child-could-hold\",\"error\":%lu}\n", GetLastError());
    if (use_policy) DeleteProcThreadAttributeList(list);
    SetEnvironmentVariableA(kHeldVariable, nullptr);
    return false;
}
} // namespace SkyHost

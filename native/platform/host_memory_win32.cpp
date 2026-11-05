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
MapStatus failure(std::uint64_t address, std::uint64_t size) noexcept {
    return occupied(address, size) ? MapStatus::Occupied : MapStatus::Failed;
}

// PS4 executables load at fixed low addresses (0x400000 up). Windows places
// heaps and thread stacks there freely, so an exact guest mapping failed
// whenever one landed first. Every free region of this window is reserved
// before main; a guest mapping inside it takes its range back from here.
constexpr std::uint64_t kLowGuestBegin = 0x400000, kLowGuestEnd = 0x80000000;
struct LowGuestHold {
    std::mutex lock;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> held; // base, size
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
    LowGuestHold() noexcept { reserve(kLowGuestBegin, kLowGuestEnd); }
    // Releases held reservations overlapping the request; returns the span
    // released so the caller can re-reserve what the mapping leaves free.
    std::pair<std::uint64_t, std::uint64_t> release(std::uint64_t address, std::uint64_t size) noexcept {
        std::uint64_t low = address, high = address + size;
        for (auto it = held.begin(); it != held.end();) {
            if (it->first < address + size && address < it->first + it->second) {
                VirtualFree(reinterpret_cast<void*>(it->first), 0, MEM_RELEASE);
                low = std::min(low, it->first);
                high = std::max(high, it->first + it->second);
                it = held.erase(it);
            } else ++it;
        }
        return {low, high};
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
    low_guest.reserve(std::max(low, kLowGuestBegin), std::min(high, kLowGuestEnd));
    return status;
}
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
} // namespace SkyHost

// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "host_memory.hpp"
#include <windows.h>

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
}

std::uint64_t map_granularity() noexcept {
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    return info.dwAllocationGranularity;
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
    const auto granularity = map_granularity();
    if (!handle_ || address % granularity || offset % granularity) return MapStatus::Failed;
    void* view = MapViewOfFileEx(handle_, FILE_MAP_ALL_ACCESS, static_cast<DWORD>(offset >> 32),
                                 static_cast<DWORD>(offset), size, reinterpret_cast<void*>(address));
    if (!view) return failure(address, size);
    DWORD previous = 0;
    if (!VirtualAlloc(view, size, MEM_COMMIT, PAGE_READWRITE) ||
        !VirtualProtect(view, size, page_protection(protection), &previous)) {
        UnmapViewOfFile(view);
        return MapStatus::Failed;
    }
    return MapStatus::Mapped;
}

MapStatus map_anonymous(std::uint64_t address, std::uint64_t size, int protection) noexcept {
    if (address % map_granularity()) return MapStatus::Failed;
    void* memory = VirtualAlloc(reinterpret_cast<void*>(address), size, MEM_RESERVE | MEM_COMMIT,
                                page_protection(protection));
    if (!memory) return failure(address, size);
    return MapStatus::Mapped;
}

bool unmap(std::uint64_t address, std::uint64_t, bool shared) noexcept {
    auto* base = reinterpret_cast<void*>(address);
    return shared ? UnmapViewOfFile(base) != 0 : VirtualFree(base, 0, MEM_RELEASE) != 0;
}
} // namespace SkyHost

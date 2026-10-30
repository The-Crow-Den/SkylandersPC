// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <cstdint>

// Host virtual memory for guest-visible mappings at fixed addresses. Linux uses
// memfd/mmap (host_memory_posix.cpp); Windows uses pagefile sections and
// VirtualAlloc (host_memory_win32.cpp). Nothing here falls back silently: a
// mapping the host cannot make exactly as asked reports failure.
namespace SkyHost {

enum Protection : int { ProtNone = 0, ProtRead = 1, ProtWrite = 2, ProtExec = 4 };

enum class MapStatus { Mapped, Occupied, Failed };

// Placement unit for mappings: the page size on Linux, the 64 KiB allocation
// granularity on Windows. Addresses and section offsets must be multiples.
std::uint64_t map_granularity() noexcept;

// A shared, zero-filled backing store that several views can alias.
class SharedMemory {
public:
    SharedMemory() = default;
    ~SharedMemory();
    SharedMemory(const SharedMemory&) = delete;
    SharedMemory& operator=(const SharedMemory&) = delete;
    bool open(const char* name, std::uint64_t size) noexcept;
    bool is_open() const noexcept;
    // Maps [offset, offset + size) at exactly address without replacing anything.
    MapStatus map(std::uint64_t address, std::uint64_t size, std::uint64_t offset, int protection) const noexcept;
private:
#ifdef _WIN32
    void* handle_ = nullptr;
#else
    int fd_ = -1;
#endif
};

// Private zero-filled memory at exactly address, without replacing anything.
MapStatus map_anonymous(std::uint64_t address, std::uint64_t size, int protection) noexcept;
// Releases a mapping made by map_anonymous (shared == false) or SharedMemory::map.
bool unmap(std::uint64_t address, std::uint64_t size, bool shared) noexcept;

} // namespace SkyHost

// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_memory.hpp"
#include <cerrno>
#include <limits>
#include <sys/mman.h>
#include <unistd.h>

namespace SkyHost {
namespace {
MapStatus place(std::uint64_t address, std::uint64_t size, int protection, int flags, int fd, std::uint64_t offset) noexcept {
    void* view = mmap(reinterpret_cast<void*>(address), size, protection, MAP_FIXED_NOREPLACE | flags, fd,
                      static_cast<off_t>(offset));
    if (view != MAP_FAILED) {
        if (reinterpret_cast<std::uintptr_t>(view) == address) return MapStatus::Mapped;
        // Older kernels may ignore MAP_FIXED_NOREPLACE. Never accept a hint
        // allocation as the requested guest mapping.
        munmap(view, size);
        errno = EADDRNOTAVAIL;
        return MapStatus::Failed;
    }
    return errno == EEXIST ? MapStatus::Occupied : MapStatus::Failed;
}
}

std::uint64_t memory_page_size() noexcept {
    const auto page = sysconf(_SC_PAGESIZE);
    return page > 0 ? static_cast<std::uint64_t>(page) : 0;
}
std::uint64_t map_granularity() noexcept { return memory_page_size(); }
bool protect(std::uint64_t address, std::uint64_t size, int protection) noexcept {
    const auto page = memory_page_size();
    if (!page || !size || address % page || size % page ||
        size > std::numeric_limits<std::uint64_t>::max() - address || (protection & ~7)) return false;
    if (mprotect(reinterpret_cast<void*>(address), size, protection)) return false;
    if (protection & ProtExec)
        __builtin___clear_cache(reinterpret_cast<char*>(address), reinterpret_cast<char*>(address + size));
    return true;
}

SharedMemory::~SharedMemory() { if (fd_ >= 0) close(fd_); }

bool SharedMemory::open(const char* name, std::uint64_t size) noexcept {
    if (fd_ >= 0) return true;
    fd_ = memfd_create(name, MFD_CLOEXEC);
    if (fd_ < 0) return false;
    if (ftruncate(fd_, static_cast<off_t>(size))) { close(fd_); fd_ = -1; return false; }
    return true;
}

bool SharedMemory::is_open() const noexcept { return fd_ >= 0; }

MapStatus SharedMemory::map(std::uint64_t address, std::uint64_t size, std::uint64_t offset, int protection) const noexcept {
    return place(address, size, protection, MAP_SHARED, fd_, offset);
}

MapStatus map_anonymous(std::uint64_t address, std::uint64_t size, int protection) noexcept {
    return place(address, size, protection, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
}

bool unmap(std::uint64_t address, std::uint64_t size, bool) noexcept {
    return munmap(reinterpret_cast<void*>(address), size) == 0;
}
} // namespace SkyHost

// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_memory.hpp"
#include <algorithm>
#include <array>
#include <cerrno>
#include <map>
#include <mutex>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>

namespace {
using U = std::uint64_t;
constexpr U page = 16384, pool_size = 5056ull * 1024 * 1024;
constexpr U invalid = 0x80020016, no_memory = 0x8002000c, no_space = 0x8002001c;
constexpr std::array<std::string_view, 6> names{
    "pO96TwzOm5E#libkernel#libkernel", "rTXw65xmLIA#libkernel#libkernel",
    "L-Q3LEjIbgA#libkernel#libkernel", "MBuItvba6z8#libkernel#libkernel",
    "cQke9UuBQOk#libkernel#libkernel", "IWIBBdTHit4#libkernel#libkernel"};
bool aligned(U n) { return n && n % page == 0; }
bool alignment(U n) { return n >= page && n <= (1ull << 32) && !(n & (n - 1)); }
U up(U n, U align) { return (n + align - 1) & ~(align - 1); }
}
struct KernelMemory::Impl {
    std::mutex lock;
    int backing = -1;
    struct Allocation { U size; int type; };
    struct View { U size; bool flexible; };
    std::map<U, Allocation> allocations;
    std::map<U, View> views;
    U cursor = 0x1000000000, flexible_bytes = 0;
    ~Impl() {
        for (const auto& [address, view] : views) munmap(reinterpret_cast<void*>(address), view.size);
        if (backing >= 0) close(backing);
    }
    bool open_pool() {
        if (backing >= 0) return true;
        backing = memfd_create("skylanders-direct-memory", MFD_CLOEXEC);
        if (backing < 0) return false;
        if (ftruncate(backing, static_cast<off_t>(pool_size))) {
            close(backing); backing = -1; return false;
        }
        return true;
    }
    U map(U* out, U size, U prot, U flags, U physical, U align, bool flexible) {
        if (!out || !aligned(size) || !alignment(align) || (prot & ~0x37ull) || (flags & ~0x90ull)) return invalid;
        if (flexible && size > 448ull * 1024 * 1024 - flexible_bytes) return no_memory;
        if (!flexible) {
            if (physical % page || physical >= pool_size || size > pool_size - physical) return invalid;
            auto allocation = allocations.upper_bound(physical);
            if (allocation == allocations.begin()) return invalid;
            --allocation;
            if (physical - allocation->first >= allocation->second.size ||
                size > allocation->second.size - (physical - allocation->first) || !open_pool()) return invalid;
        }
        const bool fixed = flags & 0x10;
        U address = fixed ? *out : up(std::max(cursor, *out), align);
        if (!address || address % align || address < 0x1000000000 || address >= 0xfc00000000 ||
            size > 0xfc00000000 - address) return invalid;
        const int protection = static_cast<int>(prot & 7); // GPU bits retained by caller, CPU bits match POSIX.
        for (unsigned attempt = 0; attempt < 4096; ++attempt) {
            void* view = mmap(reinterpret_cast<void*>(address), size, protection,
                MAP_FIXED_NOREPLACE | (flexible ? MAP_PRIVATE | MAP_ANONYMOUS : MAP_SHARED),
                flexible ? -1 : backing, flexible ? 0 : static_cast<off_t>(physical));
            if (view != MAP_FAILED) {
                try { views.emplace(address, View{size, flexible}); }
                catch (...) { munmap(view, size); throw; }
                if (flexible) flexible_bytes += size;
                cursor = address + size;
                *out = address;
                return 0;
            }
            if (fixed || errno != EEXIST) return no_memory;
            address = up(address + size, align);
            if (address >= 0xfc00000000 || size > 0xfc00000000 - address) return no_memory;
        }
        return no_memory;
    }
};
KernelMemory::KernelMemory() : impl_(std::make_unique<Impl>()) {}
KernelMemory::~KernelMemory() = default;
bool KernelMemory::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
U KernelMemory::call(std::string_view identity, const U* a) {
    std::lock_guard lock(impl_->lock);
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    switch (operation) {
    case 0: return pool_size;
    case 1: {
        U align = a[3] ? a[3] : page;
        if (!a[5] || !aligned(a[2]) || !alignment(align) || a[4] > 10 || a[0] > a[1] || a[1] > pool_size)
            return invalid;
        U start = up(a[0], align);
        for (const auto& [at, allocation] : impl_->allocations) {
            if (at >= start && a[2] <= at - start) break;
            if (start < at + allocation.size) start = up(at + allocation.size, align);
        }
        if (start >= a[1] || a[2] > a[1] - start) return no_space;
        impl_->allocations.emplace(start, Impl::Allocation{a[2], static_cast<int>(a[4])});
        *reinterpret_cast<U*>(a[5]) = start;
        return 0;
    }
    case 2: return impl_->map(reinterpret_cast<U*>(a[0]), a[1], a[2], a[3], a[4], a[5] ? a[5] : page, false);
    case 3: {
        auto allocation = impl_->allocations.find(a[0]);
        if (allocation == impl_->allocations.end() || allocation->second.size != a[1]) return invalid;
        // Views remain valid aliases until explicitly unmapped.
        impl_->allocations.erase(allocation);
        return 0;
    }
    case 4: {
        auto view = impl_->views.find(a[0]);
        if (view == impl_->views.end() || view->second.size != a[1]) return invalid;
        if (munmap(reinterpret_cast<void*>(a[0]), a[1])) return invalid;
        if (view->second.flexible) impl_->flexible_bytes -= a[1];
        impl_->views.erase(view);
        return 0;
    }
    case 5: return impl_->map(reinterpret_cast<U*>(a[0]), a[1], a[2], a[3], 0, page, true);
    default: throw std::runtime_error("unsupported memory import");
    }
}

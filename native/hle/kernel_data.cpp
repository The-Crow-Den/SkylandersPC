// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_data.hpp"
#include <cerrno>
#include <cstdint>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/random.h>
#include <unistd.h>

KernelData::KernelData() : page_(MAP_FAILED), size_(0) {
    const long length = sysconf(_SC_PAGESIZE);
    if (length <= 0) throw std::runtime_error("cannot determine kernel data page size");
    size_ = static_cast<std::size_t>(length);
    page_ = mmap(nullptr, size_, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (page_ == MAP_FAILED) throw std::runtime_error("cannot allocate kernel data");
    auto* bytes = static_cast<unsigned char*>(page_);
    std::size_t filled = 0;
    while (filled < sizeof(std::uint64_t)) {
        const auto count = getrandom(bytes + filled, sizeof(std::uint64_t) - filled, 0);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) {
            munmap(page_, size_);
            throw std::runtime_error("cannot initialize stack guard randomness");
        }
        filled += static_cast<std::size_t>(count);
    }
    if (mprotect(page_, size_, PROT_READ)) {
        munmap(page_, size_);
        throw std::runtime_error("cannot protect kernel data");
    }
}

KernelData::~KernelData() { if (page_ != MAP_FAILED) munmap(page_, size_); }

const void* KernelData::resolve(std::string_view identity, unsigned char type) const noexcept {
    if (type == 1 && identity == "f7uOxY9mM1U#libkernel#libkernel") return page_;
    return nullptr;
}

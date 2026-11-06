// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_data.hpp"
#include "../platform/host_random.hpp"
#include <cstdint>
#include <stdexcept>

KernelData::KernelData() {
    const auto size = SkyHost::thread_page_size();
    if (!size) throw std::runtime_error("cannot determine kernel data page size");
    if (!memory_.allocate(size, false)) throw std::runtime_error("cannot allocate kernel data");
    if (!SkyHost::random_bytes({static_cast<std::uint8_t*>(memory_.data()), sizeof(std::uint64_t)}))
        throw std::runtime_error("cannot initialize stack guard randomness");
    if (!memory_.protect_readonly(0, size)) throw std::runtime_error("cannot protect kernel data");
}
KernelData::~KernelData() = default;

const void* KernelData::resolve(std::string_view identity, unsigned char type) const noexcept {
    if (type == 1 && identity == "f7uOxY9mM1U#libkernel#libkernel") return memory_.data();
    return nullptr;
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <string_view>

// Lifetime is the guest process. Initialize before switching to guest FS.
class KernelData {
public:
    KernelData();
    ~KernelData();
    KernelData(const KernelData&) = delete;
    KernelData& operator=(const KernelData&) = delete;
    const void* resolve(std::string_view identity, unsigned char type) const noexcept;
private:
    void* page_;
    std::size_t size_;
};

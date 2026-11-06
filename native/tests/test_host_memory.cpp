// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/host_memory.hpp"
#include "../guest_abi.hpp"
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <exception>
#include <stdexcept>
namespace {
void require(bool value) { if (!value) throw std::runtime_error("host memory assertion failed"); }
struct Mapping {
    std::uint64_t address = 0, size = 0;
    ~Mapping() { if (address && !SkyHost::unmap(address,size,false)) std::terminate(); }
};
}
int main() {
    using namespace SkyHost;
    const auto page = memory_page_size(), granularity = map_granularity();
    require(page && granularity && granularity % page == 0);
#ifdef _WIN32
    require(granularity == 65536);
    // Windows treats NULL as an anywhere request. It cannot satisfy these
    // exact-zero requests and must release any address it chooses instead.
    require(map_anonymous(0,page,ProtRead | ProtWrite) == MapStatus::Failed);
    SharedMemory shared;
    require(shared.open("synthetic-zero-address",granularity));
    require(shared.map(0,page,0,ProtRead | ProtWrite) == MapStatus::Failed);
#endif
    Mapping mapping;
    // Each call remains an exact request. The test selects a free candidate;
    // an occupied candidate is never silently relocated by the platform API.
    for (std::uint64_t i = 0; i < 64; ++i) {
        const auto address = 0x20000000000ULL + i * granularity;
        const auto status = map_anonymous(address,3 * page,ProtRead | ProtWrite);
        if (status == MapStatus::Occupied) continue;
        require(status == MapStatus::Mapped);
        mapping.address = address;
        mapping.size = 3 * page;
        break;
    }
    require(mapping.address != 0);
    auto* bytes = reinterpret_cast<std::uint8_t*>(mapping.address);
    for (std::size_t i = 0; i < mapping.size; ++i) require(bytes[i] == 0);
    const std::array<std::uint8_t,6> code{0xb8,42,0,0,0,0xc3}; // MOV EAX,42; RET.
    std::memcpy(bytes,code.data(),code.size());
    require(map_anonymous(mapping.address,page,ProtRead | ProtWrite) == MapStatus::Occupied);
    require(std::memcmp(bytes,code.data(),code.size()) == 0);
    require(map_anonymous(mapping.address + 1,page,ProtRead) == MapStatus::Failed);
    require(map_anonymous(mapping.address,0,ProtRead) == MapStatus::Failed);
    require(protect(mapping.address,page,ProtRead | ProtExec));
    using Function = std::uint64_t (SKY_SYSV_ABI *)();
    const auto function = reinterpret_cast<Function>(mapping.address);
    require(function() == 42);
    require(!protect(mapping.address + 1,page,ProtNone));
    require(!protect(mapping.address,1,ProtNone));
    require(!protect(mapping.address,0,ProtNone));
    require(!protect(mapping.address,page,8));
    require(!protect(std::numeric_limits<std::uint64_t>::max() - page + 1,2 * page,ProtRead));
    require(function() == 42); // Invalid requests did not change protection/data.
    require(protect(mapping.address,page,ProtRead | ProtWrite));
    bytes[1] = 73;
    require(protect(mapping.address,page,ProtRead | ProtExec));
    require(function() == 73); // Executable publication includes cache coherence.
    require(protect(mapping.address + page,page,ProtRead));
    require(protect(mapping.address + 2 * page,page,ProtNone));
}

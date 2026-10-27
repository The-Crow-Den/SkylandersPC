// SPDX-License-Identifier: GPL-3.0-or-later
#include "local_playgo.hpp"
#include <algorithm>
#include <array>
#include <cstring>
#include <fstream>
#include <stdexcept>

namespace {
using U = std::uint64_t;
constexpr std::array<std::string_view, 9> names{
    "ts6GlZOKRrE#libScePlayGo#libScePlayGo", "M1Gma1ocrGE#libScePlayGo#libScePlayGo",
    "73fF1MFU8hA#libScePlayGo#libScePlayGo", "uWIYLFkkwqk#libScePlayGo#libScePlayGo",
    "4AAcTU9R3XM#libScePlayGo#libScePlayGo", "Uco1I0dlDi8#libScePlayGo#libScePlayGo",
    "MPe0EeBGM-E#libScePlayGo#libScePlayGo", "rvBSfTimejE#libScePlayGo#libScePlayGo",
    "Nn7zKwnA5q0#libScePlayGo#libScePlayGo"};
struct Init { U buffer; std::uint32_t size, reserved; };
}
void LocalPlayGo::configure(const std::string& root) {
    if (root.empty()) return;
    std::ifstream stream(root + "/sce_sys/playgo-chunk.dat", std::ios::binary | std::ios::ate);
    if (!stream) return;
    if (stream.tellg() < 16 || stream.tellg() > 16 * 1024 * 1024) throw std::runtime_error("invalid PlayGo metadata size");
    std::array<unsigned char, 16> header{};
    stream.seekg(0);
    if (!stream.read(reinterpret_cast<char*>(header.data()), header.size()) || std::memcmp(header.data(), "plgo", 4))
        throw std::runtime_error("invalid PlayGo header");
    chunks_ = static_cast<std::uint16_t>(header[10] | (header[11] << 8));
    if (!chunks_) throw std::runtime_error("empty PlayGo chunk table");
}
bool LocalPlayGo::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
U LocalPlayGo::call(std::string_view identity, const U* a) {
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    std::lock_guard lock(lock_);
    if (operation == 0) {
        if (!a[0]) return 0x80b2000a;
        const auto* init = reinterpret_cast<const Init*>(a[0]);
        if (!init->buffer) return 0x80b2000a;
        if (init->size < 0x200000) return 0x80b2000b;
        if (init->reserved) return 0x80b20004;
        if (initialized_) return 0x80b20006;
        if (!available()) return 0x80b2000e;
        initialized_ = true; return 0;
    }
    if (!initialized_) return 0x80b20005;
    if (operation == 1) {
        if (!a[0]) return 0x80b2000a;
        if (a[1]) return 0x80b20004;
        opened_ = true; *reinterpret_cast<std::uint32_t*>(a[0]) = 1; return 0;
    }
    if (operation == 6) { initialized_ = opened_ = false; return 0; }
    if (!opened_ || a[0] != 1) return 0x80b20009;
    if (operation == 2) {
        if (!a[3]) return 0x80b2000a;
        if (a[1] && !a[2]) return 0x80b2000b;
        auto* out = reinterpret_cast<std::uint32_t*>(a[3]);
        if (!a[1]) { *out = chunks_; return 0; }
        const auto count = std::min<U>(chunks_, a[2]);
        auto* ids = reinterpret_cast<std::uint16_t*>(a[1]);
        for (U i = 0; i < count; ++i) ids[i] = static_cast<std::uint16_t>(i);
        *out = static_cast<std::uint32_t>(count); return 0;
    }
    if (operation == 3) {
        if (!a[1] || !a[3]) return 0x80b2000a;
        if (!a[2] || a[2] > chunks_) return 0x80b2000b;
        const auto* ids = reinterpret_cast<const std::uint16_t*>(a[1]);
        for (U i = 0; i < a[2]; ++i) if (ids[i] >= chunks_) return 0x80b2000c;
        std::memset(reinterpret_cast<void*>(a[3]), 3, a[2]); return 0;
    }
    if (operation == 4) { if (a[1] > 2) return 0x80b2000d; speed_ = static_cast<int>(a[1]); return 0; }
    if (operation == 5) { opened_ = false; return 0; }
    if (operation == 7) { if (!a[1]) return 0x80b2000a; *reinterpret_cast<int*>(a[1]) = speed_; return 0; }
    if (operation == 8) {
        if (!a[1] || !a[3]) return 0x80b2000a;
        if (!a[2]) return 0x80b2000b;
        *reinterpret_cast<std::uint32_t*>(a[3]) = 0; // All declared chunks are local.
        return 0;
    }
    throw std::runtime_error("unsupported local PlayGo import");
}

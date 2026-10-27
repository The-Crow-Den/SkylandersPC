// SPDX-License-Identifier: GPL-3.0-or-later
#include "app_content.hpp"
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <vector>

void AppContent::configure(const std::string& root) {
    if (root.empty()) return;
    std::ifstream stream(root + "/sce_sys/param.sfo", std::ios::binary | std::ios::ate);
    if (!stream || stream.tellg() < 20 || stream.tellg() > 1024 * 1024) throw std::runtime_error("invalid package parameter file size");
    std::vector<unsigned char> data(static_cast<std::size_t>(stream.tellg()));
    stream.seekg(0);
    if (!stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size())))
        throw std::runtime_error("cannot read package parameters");
    const auto integer = [&](std::size_t offset, unsigned bytes) {
        if (offset > data.size() || bytes > data.size() - offset) throw std::runtime_error("package parameter range outside file");
        std::uint32_t value = 0;
        for (unsigned i = 0; i < bytes; ++i) value |= static_cast<std::uint32_t>(data[offset + i]) << (8 * i);
        return value;
    };
    if (integer(0, 4) != 0x46535000 || integer(4, 4) != 0x101) throw std::runtime_error("unsupported package parameter header");
    const auto keys = integer(8, 4), values = integer(12, 4), count = integer(16, 4);
    if (count > 1024 || 20ull + count * 16ull > keys || keys > values || values > data.size())
        throw std::runtime_error("invalid package parameter tables");
    std::array<bool, 4> found{};
    for (std::uint32_t i = 0; i < count; ++i) {
        const auto row = 20 + i * 16;
        const std::size_t key = static_cast<std::size_t>(keys) + integer(row, 2);
        if (key >= values) throw std::runtime_error("package parameter key outside table");
        const auto length = strnlen(reinterpret_cast<const char*>(data.data() + key), values - key);
        if (length == values - key) throw std::runtime_error("unterminated package parameter key");
        const std::string_view name(reinterpret_cast<const char*>(data.data() + key), length);
        if (name == "TITLE_ID") {
            const std::size_t offset = static_cast<std::size_t>(values) + integer(row + 12, 4);
            const auto bytes = integer(row + 4, 4);
            if (integer(row + 2, 2) != 0x204 || bytes != 10 || offset > data.size() || bytes > data.size() - offset || data[offset + 9])
                throw std::runtime_error("invalid package title identity");
            title_id_.assign(reinterpret_cast<const char*>(data.data() + offset), 9);
        }
        if (name == "ATTRIBUTE" || name == "SYSTEM_VER") {
            if (integer(row + 2, 2) != 0x404 || integer(row + 4, 4) != 4)
                throw std::runtime_error("invalid package system parameter");
            const auto value = integer(static_cast<std::size_t>(values) + integer(row + 12, 4), 4);
            if (name == "ATTRIBUTE") attributes_ = value; else system_version_ = value;
        }
        for (unsigned index = 0; index < 4; ++index) {
            if (name != "USER_DEFINED_PARAM_" + std::to_string(index + 1)) continue;
            if (found[index] || integer(row + 2, 2) != 0x404 || integer(row + 4, 4) != 4 || integer(row + 8, 4) < 4)
                throw std::runtime_error("invalid user-defined package parameter");
            parameters_[index] = integer(static_cast<std::size_t>(values) + integer(row + 12, 4), 4);
            found[index] = true;
        }
    }
    configured_ = true;
}
bool AppContent::supports(std::string_view identity) noexcept {
    return identity == "99b82IKXpH4#libSceAppContent#libSceAppContentUtil";
}
std::uint64_t AppContent::call(std::string_view identity, const std::uint64_t* a) {
    std::lock_guard lock(lock_);
    if (!supports(identity)) throw std::runtime_error("unsupported package content import");
    if (!a[1] || a[0] > 4) return 0x80d90002;
    if (!configured_) throw std::runtime_error("package parameters require the game root");
    if (!a[0]) throw std::runtime_error("SKU query requires a registered content profile");
    *reinterpret_cast<std::uint32_t*>(a[1]) = parameters_[a[0] - 1];
    return 0;
}

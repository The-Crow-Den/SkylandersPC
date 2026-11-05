// SPDX-License-Identifier: GPL-3.0-or-later
#include "protocol.hpp"
#include <algorithm>

namespace PortalDevice {
namespace {
Report make(std::initializer_list<std::uint8_t> bytes) {
    Report report{}; std::copy(bytes.begin(), bytes.end(), report.begin()); return report;
}
// Firmware ids from the reset reply, after the 'R'. Sources: the published FCC
// id table supplied by the user. Hardware has not confirmed these yet.
struct Known { std::array<std::uint8_t, 4> id; std::size_t length; const char* name; Capabilities caps; };
constexpr Capabilities plain{}, lit{false, false, true}, trap{true, true, true};
constexpr Known known[]{
    {{0x02, 0x0a, 0x03, 0x02}, 4, "SuperChargers portal", lit},
    {{0x02, 0x14, 0x03, 0x02}, 4, "SuperChargers portal (Xbox One)", lit},
    {{0x02, 0x0a, 0x05, 0x08}, 4, "Imaginators portal", lit},
    {{0x01, 0x29}, 2, "Spyro's Adventure portal (Wii/PS3)", plain},
    {{0x01, 0x28}, 2, "Spyro's Adventure portal (Xbox 360)", plain},
    {{0x01, 0x2c}, 2, "Spyro's Adventure portal (PC/Mac)", plain},
    {{0x01, 0x3c}, 2, "Giants portal", lit},
    {{0x01, 0x3d}, 2, "Giants portal", lit},
    {{0x01, 0x48}, 2, "Giants portal (Xbox 360)", lit},
    {{0x02, 0x03}, 2, "SWAP Force portal", lit},
    {{0x02, 0x18}, 2, "Traptanium portal", trap},
    {{0x02, 0x1b}, 2, "Traptanium portal", trap},
    {{0x02, 0x27}, 2, "Traptanium portal (Xbox One)", trap},
};
}
Report reset() { return make({'R'}); }
Report activate(bool on) { return make({'A', static_cast<std::uint8_t>(on)}); }
Report status() { return make({'S'}); }
Report query(unsigned slot, unsigned block) {
    return make({'Q', static_cast<std::uint8_t>(0x10 | (slot & 15)), static_cast<std::uint8_t>(block)});
}
Report write(unsigned slot, unsigned block, std::span<const std::uint8_t, block_size> data) {
    auto report = make({'W', static_cast<std::uint8_t>(0x10 | (slot & 15)), static_cast<std::uint8_t>(block)});
    std::copy(data.begin(), data.end(), report.begin() + 3); return report;
}
Report colour(std::uint8_t r, std::uint8_t g, std::uint8_t b) { return make({'C', r, g, b}); }
Report audio(bool on) { return make({'M', static_cast<std::uint8_t>(on)}); }

std::optional<Status> parse_status(std::span<const std::uint8_t> reply) {
    if (reply.size() < 7 || reply[0] != 'S') return std::nullopt;
    Status result;
    const std::uint32_t bits = reply[1] | (reply[2] << 8) | (reply[3] << 16) | (static_cast<std::uint32_t>(reply[4]) << 24);
    for (unsigned slot = 0; slot < slots; ++slot) result.state[slot] = static_cast<SlotState>((bits >> (slot * 2)) & 3);
    result.counter = reply[5]; result.active = reply[6] != 0;
    return result;
}
std::optional<Block> parse_query(std::span<const std::uint8_t> reply) {
    if (reply.size() < 3 + block_size || reply[0] != 'Q') return std::nullopt;
    Block result{reply[1] & 15u, reply[2], (reply[1] & 0x10) != 0, {}};
    std::copy_n(reply.begin() + 3, block_size, result.data.begin());
    return result;
}
std::optional<std::pair<unsigned, unsigned>> write_target(std::span<const std::uint8_t> report) {
    if (report.size() < 3 + block_size || report[0] != 'W') return std::nullopt;
    return std::pair{report[1] & 15u, static_cast<unsigned>(report[2])};
}
Model identify(std::span<const std::uint8_t> reply) {
    if (reply.size() < 3 || reply[0] != 'R') return {"Unknown portal", {}, false};
    for (const auto& item : known)
        if (reply.size() >= 1 + item.length && std::equal(item.id.begin(), item.id.begin() + item.length, reply.begin() + 1))
            return {item.name, item.caps, true};
    return {"Unknown portal", {}, false};
}
}

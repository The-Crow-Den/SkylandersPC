// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// The Portal of Power report protocol, shared by every transport. Reports are
// 32 bytes; the first byte names the command and its reply.
#include <array>
#include <cstdint>
#include <optional>
#include <span>
#include <string>

namespace PortalDevice {
constexpr std::size_t report_size = 32;
constexpr std::size_t block_size = 16;
constexpr unsigned figure_blocks = 64;
constexpr unsigned slots = 16;
using Report = std::array<std::uint8_t, report_size>;

Report reset();
Report activate(bool on);
Report status();
Report query(unsigned slot, unsigned block);
Report write(unsigned slot, unsigned block, std::span<const std::uint8_t, block_size> data);
Report colour(std::uint8_t r, std::uint8_t g, std::uint8_t b);
// Trap Team portals: speaker on/off ('M') before 64-byte PCM packets.
Report audio(bool on);

enum class SlotState : std::uint8_t { empty = 0, present = 1, added = 3, removed = 2 };
struct Status {
    std::array<SlotState, slots> state{};
    std::uint8_t counter = 0;
    bool active = false;
};
std::optional<Status> parse_status(std::span<const std::uint8_t> reply);

struct Block { unsigned slot = 0, block = 0; bool ok = false; std::array<std::uint8_t, block_size> data{}; };
std::optional<Block> parse_query(std::span<const std::uint8_t> reply);
// Slot and block a 'W' report targets, or nothing if the report is not a write.
std::optional<std::pair<unsigned, unsigned>> write_target(std::span<const std::uint8_t> report);

// What a portal reports about itself in its reset ('R') reply. The firmware id
// bytes come from the published FCC/firmware table; they are a model, never a
// USB identity.
struct Capabilities { bool traps = false, audio = false, leds = false; };
struct Model { std::string name; Capabilities caps; bool known = false; };
Model identify(std::span<const std::uint8_t> reset_reply);
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cstdint>
namespace LocalPlayers {
// Player one always has the keyboard. A second logged-in local user exists
// while the second SDL controller is connected; it never aliases player one.
inline std::atomic<bool> second_connected{false};
inline bool valid_user(std::uint64_t user) {return user==0x1000 || (user==0x1001 && second_connected.load());}
}

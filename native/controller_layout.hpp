// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>
namespace ControllerLayout {
// SDL instance IDs remain assigned until disconnect. Keyboard mode reserves
// player one, so a single physical pad can join as player two.
inline int assign(const std::array<std::uint32_t,2>& assigned,std::uint32_t incoming,bool keyboard_and_pad) {
    if(!incoming)return -1;
    for(const auto id:assigned)if(id==incoming)return -1;
    for(unsigned slot=keyboard_and_pad?1:0;slot<assigned.size();++slot)if(!assigned[slot])return static_cast<int>(slot);
    return -1;
}
}

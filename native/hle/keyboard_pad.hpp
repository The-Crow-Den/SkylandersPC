// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <array>
#include <functional>
#include <cstdint>
#include <mutex>
#include "local_players.hpp"
#include <string_view>
class KeyboardPad {
public:
    struct PhysicalState {
        std::uint32_t buttons = 0;
        std::array<unsigned char, 4> axes{128,128,128,128};
        std::array<unsigned char, 2> triggers{};
        bool connected = false;
    };
    void set_physical(const PhysicalState& state,unsigned player=0) {
        if(player>=2)return;
        std::lock_guard guard(lock_);
        if(state.connected && physical_[player].connected)
            physical_presses_[player] |= state.buttons & ~physical_[player].buttons;
        else physical_presses_[player]=0;
        physical_[player]=state;
        if(player==1)LocalPlayers::second_connected.store(state.connected);
    }
    void bind_rumble(std::function<bool(unsigned char,unsigned char)> callback,unsigned player=0) { if(player>=2)return;std::lock_guard guard(lock_);rumble_[player]=std::move(callback); }
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments, bool input_blocked = false);
    void key(std::uint32_t mask, bool pressed) noexcept;
    void set_keys(std::uint32_t keys) noexcept;
    void release_keys() noexcept;
private:
    std::mutex lock_;
    std::uint32_t keys_ = 0, pending_presses_ = 0;
    bool initialized_ = false;
    std::array<bool,2> opened_{};
    std::array<PhysicalState,2> physical_;
    std::array<std::uint32_t,2> physical_presses_{};
    std::array<std::function<bool(unsigned char,unsigned char)>,2> rumble_;
};

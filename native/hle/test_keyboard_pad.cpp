// SPDX-License-Identifier: GPL-3.0-or-later
#include "keyboard_pad.hpp"
#include "../controller_layout.hpp"
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

int main() {
    try {
        using U = std::uint64_t;
        KeyboardPad pad;
        if(ControllerLayout::assign({0,0},3,false)!=0 || ControllerLayout::assign({0,0},3,true)!=1 ||
           ControllerLayout::assign({3,0},4,false)!=1 || ControllerLayout::assign({3,4},4,false)!=-1 ||
           ControllerLayout::assign({0,4},3,true)!=-1 || ControllerLayout::assign({0,4},3,false)!=0)
            throw std::runtime_error("controller assignment and hotplug isolation contract failed");
        const auto check = [](bool value) { if (!value) throw std::runtime_error("keyboard controller contract failed"); };
        const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
        const auto call = [&](const char* nid, std::array<U, 6> args = {}) {
            return pad.call(std::string(nid) + "#libScePad#libScePad", args.data());
        };
        check(!KeyboardPad::supports("hv1luiJrqQM#wrong#libScePad"));
        check(call("xk0AcarP3V4", {0x1000, 0, 0, 0}) == 0x80920005);
        check(call("hv1luiJrqQM") == 0);
        check(call("xk0AcarP3V4", {0x1001, 0, 0, 0}) == 0x80920001);
        check(call("xk0AcarP3V4", {0x1000, 0, 0, 0}) == 1);
        alignas(8) std::array<unsigned char, 120> data{};
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0);
        check(data[4] == 128 && data[5] == 128 && data[76] == 1 && data[104] == 1);
        pad.key(0x4000 | (1u << 24), true);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0);
        std::uint32_t buttons = 0; std::memcpy(&buttons, data.data(), 4);
        check(buttons == 0x4000 && data[4] == 0);
        pad.key(1u << 25, true);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0 && data[4] == 128);
        pad.release_keys();
        KeyboardPad::PhysicalState physical;
        physical.connected = true; physical.buttons = 0x4000;
        physical.axes = {31, 211, 54, 199}; physical.triggers = {77, 188};
        pad.set_physical(physical);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0);
        std::memcpy(&buttons, data.data(), 4);
        check(buttons == 0x4000 && data[4] == 31 && data[7] == 199 && data[8] == 77 && data[9] == 188);
        const std::array<U,6> blocked_args{1,pointer(data.data())};
        check(pad.call("YndgXqQVV7c#libScePad#libScePad",blocked_args.data(),true)==0);
        std::memcpy(&buttons,data.data(),4);
        check(buttons==0 && data[4]==128 && data[7]==128 && data[8]==0 && data[9]==0 && data[76]==1);
        pad.key(1u << 24, true);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0 && data[4] == 0 && data[6] == 54);
        pad.release_keys(); pad.set_physical({});
        // A complete quick tap between polls must still reach the guest once.
        pad.set_keys(0x8); pad.set_keys(0);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0x8);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0);
        pad.key(0x2000,true);pad.key(0x2000,false);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0x2000);
        // Focus loss cancels queued presses rather than replaying them later.
        pad.set_keys(0x8);pad.release_keys();
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0);
        std::array<unsigned char,2> motors{17,201};bool rumble_called=false;
        pad.bind_rumble([&](unsigned char large,unsigned char small){rumble_called=large==17&&small==201;pad.set_physical({});return true;});
        check(call("yFVnOdGxvZY",{1,pointer(motors.data())})==0 && rumble_called);
        check(call("yFVnOdGxvZY",{1,0})==0x80920001);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0 && data[0] == 0 && data[1] == 0);
        check(call("6ncge5+l5Qs", {1}) == 0);
        check(call("YndgXqQVV7c", {1, pointer(data.data())}) == 0x80920003);
        KeyboardPad::PhysicalState second;
        second.connected=true;second.buttons=0x8000;second.axes[0]=203;
        pad.set_physical(second,1);
        check(call("xk0AcarP3V4", {0x1001,0,0,0})==2);
        check(call("xk0AcarP3V4", {0x1001,0,0,0})==0x80920004);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0x8000 && data[4]==203 && data[76]==1);
        check(call("xk0AcarP3V4", {0x1000,0,0,0})==1);
        pad.set_keys(0x4000);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0x8000);
        check(call("YndgXqQVV7c", {1,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0x4000);
        // SDL can deliver press+release before the next guest poll. Preserve
        // that edge once, independently for each player, never across unplug.
        second.buttons=0;pad.set_physical(second,1);
        second.buttons=0x2000;pad.set_physical(second,1);
        second.buttons=0;pad.set_physical(second,1);
        check(call("YndgXqQVV7c", {1,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0x4000);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0x2000);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0);
        second.buttons=0x2000;pad.set_physical(second,1);
        second.buttons=0;pad.set_physical(second,1);
        const std::array<U,6> blocked_second{2,pointer(data.data())};
        check(pad.call("YndgXqQVV7c#libScePad#libScePad",blocked_second.data(),true)==0);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0);
        second.buttons=0x2000;pad.set_physical(second,1);
        pad.set_physical({},1);second.buttons=0;pad.set_physical(second,1);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0);
        second.buttons=0x2000;pad.set_physical(second,1);
        second.buttons=0;pad.set_physical(second,1);
        pad.release_keys(); // PC drawer/focus handoff cancels buffered edges.
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0);
        std::memcpy(&buttons,data.data(),4);check(buttons==0);
        bool second_rumble=false;
        pad.bind_rumble([&](unsigned char a,unsigned char b){second_rumble=a==17 && b==201;return true;},1);
        check(call("yFVnOdGxvZY",{2,pointer(motors.data())})==0 && second_rumble);
        pad.set_physical({},1);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0 && data[76]==0 && data[4]==128);
        std::memcpy(&buttons,data.data(),4);check(buttons==0);
        check(call("6ncge5+l5Qs",{2})==0);
        check(call("YndgXqQVV7c", {2,pointer(data.data())})==0x80920003);
        check(call("xk0AcarP3V4", {0x1002,0,0,0})==0x80920001);
        std::cout << "keyboard controller ABI, state, opposing axes and disconnect checks passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}

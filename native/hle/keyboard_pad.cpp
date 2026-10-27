// SPDX-License-Identifier: GPL-3.0-or-later
#include "keyboard_pad.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <stdexcept>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {
using U = std::uint64_t;
constexpr std::array<std::string_view, 7> names{
    "hv1luiJrqQM#libScePad#libScePad", "xk0AcarP3V4#libScePad#libScePad",
    "6ncge5+l5Qs#libScePad#libScePad", "YndgXqQVV7c#libScePad#libScePad",
    "gjP9-KQzoUk#libScePad#libScePad", "rIZnR6eSpvk#libScePad#libScePad",
    "yFVnOdGxvZY#libScePad#libScePad"};
struct Touch { std::uint16_t x, y; unsigned char id, reserved[3]; };
struct Data {
    std::uint32_t buttons;
    unsigned char axes[4], triggers[2], padding[2];
    float orientation[4], acceleration[3], angular_velocity[3];
    unsigned char touch_count, touch_reserved[3];
    std::uint32_t touch_hold;
    Touch touches[2];
    unsigned char connected, pad[3];
    U timestamp;
    unsigned char extension[16], connection_count, reserved[2], unique_length, unique[12];
};
struct Info {
    float density;
    std::uint16_t width, height;
    unsigned char dead_zones[2], connection, connection_count, connected, padding[3];
    std::int32_t device_class;
    unsigned char reserved[8];
};
static_assert(sizeof(Data) == 120 && offsetof(Data, timestamp) == 80);
static_assert(sizeof(Info) == 28);
}
bool KeyboardPad::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
void KeyboardPad::key(std::uint32_t mask, bool pressed) noexcept {
    std::lock_guard guard(lock_);
    if (pressed) { pending_presses_ |= mask & ~keys_; keys_ |= mask; }
    else keys_ &= ~mask;
}
void KeyboardPad::set_keys(std::uint32_t keys) noexcept {
    std::lock_guard guard(lock_);
    pending_presses_ |= keys & ~keys_;
    static const bool trace=[] {const auto* p=std::getenv("SKY_TRAP_PHASE_PROBE");return p && !std::strcmp(p,"1");}();
    if(trace && keys!=keys_)std::fprintf(stderr,"{\"event\":\"probe-keyboard-state\",\"keys\":%u}\n",keys);
    keys_ = keys;
}
void KeyboardPad::release_keys() noexcept {
    std::lock_guard guard(lock_);
    keys_ = pending_presses_ = 0;
    physical_presses_.fill(0);
}
U KeyboardPad::call(std::string_view identity, const U* a, bool input_blocked) {
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    if (operation == static_cast<std::ptrdiff_t>(names.size())) throw std::runtime_error("unsupported keyboard pad import");
    std::unique_lock lock(lock_);
    if (operation == 0) { initialized_ = true; return 0; }
    if (!initialized_) return 0x80920005;
    if (operation == 1) {
        if ((a[0]!=0x1000 && a[0]!=0x1001) || a[1]!=0 || a[2]!=0 || a[3])return 0x80920001;
        const auto player=static_cast<unsigned>(a[0]-0x1000);
        if(player==1 && !physical_[1].connected)return 0x80920001;
        if(opened_[player])return 0x80920004;
        opened_[player]=true;physical_presses_[player]=0;return player+1;
    }
    if(a[0]<1 || a[0]>2)return 0x80920003;
    const auto player=static_cast<unsigned>(a[0]-1);
    if(!opened_[player])return 0x80920003;
    const auto& physical=physical_[player];
    const bool connected=player==0 || physical.connected;
    if(operation==6){
        if(!a[1])return 0x80920001;
        const auto* motors=reinterpret_cast<const unsigned char*>(a[1]);
        const auto large=motors[0],small=motors[1];const auto callback=rumble_[player];
        lock.unlock(); // SDL event polling takes the locks in the opposite order.
        return callback && callback(large,small) ? 0 : 0x80920007;
    }
    if (operation == 2) { opened_[player] = false; physical_presses_[player]=0; if(player==0)keys_=pending_presses_=0; return 0; }
    if (operation == 3) {
        if (!a[1]) return 0x80920001;
        auto* out = reinterpret_cast<Data*>(a[1]);
        *out = {};
        const auto keys = player==0?keys_ | pending_presses_:0;
        if(player==0)pending_presses_ = 0;
        out->buttons = keys & 0x1fffff;
        std::fill(std::begin(out->axes), std::end(out->axes), 128);
        if (physical.connected) {
            out->buttons |= physical.buttons | physical_presses_[player];
            std::copy(physical.axes.begin(), physical.axes.end(), out->axes);
            std::copy(physical.triggers.begin(), physical.triggers.end(), out->triggers);
        }
        physical_presses_[player]=0;
        if (bool(keys & (1u << 24)) != bool(keys & (1u << 25))) out->axes[0] = keys & (1u << 24) ? 0 : 255;
        if (bool(keys & (1u << 26)) != bool(keys & (1u << 27))) out->axes[1] = keys & (1u << 26) ? 0 : 255;
        if (keys & 0x100) out->triggers[0] = 255;
        if (keys & 0x200) out->triggers[1] = 255;
        if (input_blocked) {
            keys_ = pending_presses_ = 0;
            out->buttons = 0;
            std::fill(std::begin(out->axes), std::end(out->axes),128);
            out->triggers[0] = out->triggers[1] = 0;
        }
        out->orientation[3] = 1;
        out->connected = out->connection_count = connected?1:0;
        out->timestamp = static_cast<U>(std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
        return 0;
    }
    if (operation == 4) {
        if (!a[1]) return 0x80920001;
        auto* out = reinterpret_cast<Info*>(a[1]);
        *out = {};
        out->density = 44.86f; out->width = 1920; out->height = 943;
        out->dead_zones[0] = out->dead_zones[1] = 2;
        out->connected = out->connection_count = connected?1:0;
        return 0;
    }
    if (operation == 5) return 0; // Keyboard orientation is always the identity.
    throw std::runtime_error("unsupported keyboard pad import");
}

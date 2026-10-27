// SPDX-License-Identifier: GPL-3.0-or-later
#include "user_service.hpp"
#include "local_players.hpp"
#include <array>
#include <cstring>
#include <stdexcept>

namespace {
constexpr std::array<std::string_view, 7> names{
    "j3YMu1MVNNo#libSceUserService#libSceUserService",
    "bwFjS+bX9mA#libSceUserService#libSceUserService",
    "CdWp0oHWGr0#libSceUserService#libSceUserService",
    "fPhymKNvK-A#libSceUserService#libSceUserService",
    "1xxcMiGu2fo#libSceUserService#libSceUserService",
    "yH17Q6NWtVg#libSceUserService#libSceUserService",
    "lUoqwTQu4Go#libSceUserService#libSceUserService"};
constexpr std::uint64_t invalid = 0x80960005;
}
bool UserService::supports(std::string_view identity) noexcept {
    for (auto name : names) if (identity == name) return true;
    return false;
}
std::uint64_t UserService::call(std::string_view identity, const std::uint64_t* a) {
    std::lock_guard lock(lock_);
    if (identity == names[0]) {
        if (initialized_) return 0x80960003;
        if (a[0]) priority_ = *reinterpret_cast<const std::int32_t*>(a[0]);
        initialized_=true;second_seen_=false;events_.clear();events_.push_back({0,0x1000});
        return 0;
    }
    if (!initialized_) return 0x80960002;
    const bool second=LocalPlayers::second_connected.load();
    if(second!=second_seen_) {
        // Bound an unconsumed hotplug stream; the newest login list remains
        // authoritative if a client stops draining notifications.
        if(events_.size()>=32)events_.pop_front();
        events_.push_back({second?0:1,0x1001});second_seen_=second;
    }
    if (identity == names[1]) { initialized_ = false;events_.clear();return 0; }
    if (identity == names[2]) {
        if (!a[0]) return invalid;
        *reinterpret_cast<std::int32_t*>(a[0]) = 0x1000;
        return 0;
    }
    if (identity == names[3]) {
        if (!a[0]) return invalid;
        auto* out = reinterpret_cast<std::int32_t*>(a[0]);
        out[0]=0x1000;out[1]=second?0x1001:-1;out[2]=out[3]=-1;
        return 0;
    }
    if (identity == names[4]) {
        if ((a[0]!=0x1000 && !(a[0]==0x1001 && second)) || !a[1])return invalid;
        const char* name=a[0]==0x1000?"Player 1":"Player 2";
        if (a[2] < std::strlen(name)+1) return 0x8096000a;
        std::memcpy(reinterpret_cast<void*>(a[1]),name,std::strlen(name)+1);
        return 0;
    }
    if (identity == names[5]) {
        if (!a[0]) return invalid;
        if(events_.empty())return 0x80960007;
        auto* out = reinterpret_cast<std::int32_t*>(a[0]);
        out[0]=events_.front()[0];out[1]=events_.front()[1];events_.pop_front();
        return 0;
    }
    if (identity == names[6]) {
        if ((a[0]!=0x1000 && !(a[0]==0x1001 && second)) || !a[1])return invalid;
        *reinterpret_cast<std::int32_t*>(a[1]) = a[0]==0x1000?0:1; // Blue local user.
        return 0;
    }
    throw std::runtime_error("unsupported user service import");
}

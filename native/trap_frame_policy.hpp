// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "level_event_protocol.hpp"
#include <cctype>
#include <string>
#include <string_view>

namespace TrapFramePolicy {
struct Gates {
    bool cutscenes_valid=false,control_valid=false,control_ready=false,pc_menu=false,pause_ui=false;
    bool movies_valid=false,portal_ui=false;
    std::uint32_t movies=0;
    std::uint32_t cutscenes=0,active_script_groups=0;
};
struct Decision {int fps;std::string_view phase;};
inline std::string canonical(std::string_view name) {
    const auto slash=name.find('/');
    if(slash==std::string_view::npos)return "level/"+std::string(name);
    auto category=name.substr(0,slash);
    while(!category.empty() && category.back()>='0' && category.back()<='9')category.remove_suffix(1);
    return std::string(category)+std::string(name.substr(slash));
}
class Upshift {
    std::uint64_t ready_since_=0,generation_=UINT64_MAX;
    bool qualified_=false;
public:
    int apply(int wanted,std::uint64_t now,std::uint64_t generation=0) {
        if(generation_!=generation) {generation_=generation;qualified_=false;ready_since_=0;}
        if(wanted!=60) {ready_since_=0;return 30;}
        if(qualified_)return 60;
        if(!ready_since_ || now<ready_since_)ready_since_=now;
        // Qualify only the first gameplay entry in this world. Once verified,
        // Pause/portal resumes follow the engine gates immediately.
        if(now-ready_since_>=500000)qualified_=true;
        return qualified_?60:30;
    }
};
class State {
    bool healthy_=true,loading_=false,paused_=false;
    std::string pending_,root_;
    std::uint64_t generation_=0;
public:
    std::uint64_t generation() const {return generation_;}
    void lost() {++generation_;healthy_=false;loading_=false;pending_.clear();root_.clear();paused_=false;}
    void consume(const LevelProtocol::Event& event) {
        const auto name=canonical(event.label());
        if(event.kind==3) {
            pending_=name;loading_=true;
            if(name.starts_with("level/")) {++generation_;root_.clear();}
        } else if(event.kind==2) {
            if(name==pending_) {loading_=false;pending_.clear();}
            if(name.starts_with("level/")) {if(root_!=name)++generation_;root_=name;healthy_=true;}
            if(name=="misc/ui_pausemenu_streamed")paused_=true;
            else if(name=="misc/")paused_=false;
        }
    }
    Decision decide(const Gates& gates) const {
        if(!healthy_)return {30,"unknown"};
        // Native PC drawers do not change the guest phase. Keep the game's
        // gameplay, pause, portal, loading or cinematic decision underneath.
        // Unloading the pause stream is cleanup, not loading a new world.
        // Visible gameplay and a hidden pause container prove control returned
        // before that stream's deferred commit; all other gates still apply.
        const bool resumed=healthy_ && pending_=="misc/" && gates.control_valid &&
            gates.control_ready && !gates.pause_ui;
        // A verified live trace loaded outfit/Hat_202 while control stayed
        // ready in the committed world. This cosmetic stream is background
        // work, not a level transition. Keep the whitelist narrow: character,
        // item and unknown streams still require their existing loading gates.
        constexpr std::string_view hat_prefix="outfit/Hat_";
        const auto pending=std::string_view(pending_);
        const bool hat_name=pending.starts_with(hat_prefix) && pending.size()>hat_prefix.size() &&
            pending.substr(hat_prefix.size()).find_first_not_of("0123456789")==std::string_view::npos;
        const bool cosmetic=hat_name && root_.starts_with("level/Level_") &&
            gates.control_valid && gates.control_ready && !gates.pause_ui &&
            gates.cutscenes_valid && gates.cutscenes==0;
        if(loading_ && !resumed && !cosmetic)return {30,"loading"};
        if(!root_.starts_with("level/Level_"))return {30,"menu"};
        if((paused_ && !resumed) || gates.pause_ui)return {30,"pause"};
        if(!gates.cutscenes_valid)return {30,"unknown"};
        if(gates.movies_valid && gates.movies)return {30,"video"};
        if(gates.cutscenes) {
            if(gates.movies_valid && gates.control_valid && !gates.portal_ui)
                return {60,"realtime-cinematic"};
            return {30,"cutscene"};
        }
        if(!gates.control_valid)return {30,"unknown"};
        if(!gates.control_ready) {
            // In-engine camera/script sequences can hide the gameplay HUD
            // without registering a cutscene. A visible portal container is a
            // separate timing guard; it must never be inferred from hidden HUD.
            if(gates.movies_valid && !gates.portal_ui)return {60,"realtime-cinematic"};
            return {30,"portal"};
        }
        return {60,"gameplay"};
    }
};
}

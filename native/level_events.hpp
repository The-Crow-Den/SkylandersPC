// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Guest lifecycle events plus native UI/cutscene gates. Callers must first
// match an exact Trap Team build (trap_team_hooks.cpp); no check happens here.
// Automatic mode fails closed to 30 FPS; manual mode only observes.
#include "trap_team_probe.hpp"
#include "level_event_protocol.hpp"
#include "trap_frame_policy.hpp"
#include "pc_settings.hpp"
#include "trap_ui_gate.hpp"
#include "trap_movie_gate.hpp"
#include "trap_portal_audio_probe.hpp"
#include <charconv>

namespace LevelEvents {
inline TrapFramePolicy::Gates runtime_gates(std::uint64_t now,bool pc_menu,bool us_update) {
    TrapFramePolicy::Gates gates;gates.pc_menu=pc_menu;
    std::uintptr_t directory=0,type=0,list=0;
    if(!TrapTeamProbe::read(0x10a0a30,&directory,8) ||
       !TrapTeamProbe::read(0x10879e8,&type,8))return gates;
    const auto system=TrapTeamProbe::service(directory,type);
    if(!system || !TrapTeamProbe::read(system+16,&list,8))return gates;
    const auto items=TrapTeamProbe::pointer_list(list,64);
    if(!items.valid)return gates;
    gates.cutscenes_valid=true;gates.cutscenes=items.count;
    // These additional offsets are corroborated for the updated US build.
    // Other builds retain their existing conservative cutscene policy.
    if(us_update) {
        TrapPortalAudioProbe::sample(TrapTeamProbe::read);
        const auto movies=TrapMovieGate::sample(TrapTeamProbe::read);
        gates.movies_valid=movies.valid;gates.movies=movies.count;
        static std::uint64_t old=UINT64_MAX;
        const std::uint64_t signature=(std::uint64_t(movies.valid)<<32)|movies.count;
        if(old!=signature) {
            old=signature;
            std::fprintf(stderr,"{\"event\":\"trap-movie-list\",\"observed_us\":%llu,\"valid\":%s,\"count\":%u}\n",
                static_cast<unsigned long long>(now),movies.valid?"true":"false",movies.count);
        }
    }
    const auto ui=TrapUiGate::sample(TrapTeamProbe::read);
    gates.control_valid=ui.valid;gates.pause_ui=ui.valid && ui.pause;gates.portal_ui=ui.valid && ui.portal;
    gates.control_ready=ui.gameplay && !ui.pause && !ui.portal;
    std::uintptr_t app=0,core=0;
    if(!SkyPc::automatic.load() && TrapTeamProbe::read(0x1087480,&app,8) && app && TrapTeamProbe::read(app+96,&core,8)) {
        // The legacy probe called this "players", but this is the script
        // manager's active placement/group count, not proof of player control.
        const auto activities=TrapTeamProbe::players(TrapTeamProbe::activity_manager(core));
        if(activities.valid)gates.active_script_groups=activities.count;
    }
    static auto previous=UINT32_MAX;
    if(previous!=items.count) {
      previous=items.count;
    std::fprintf(stderr,"{\"event\":\"trap-cutscene-list\",\"observed_us\":%llu,\"count\":%u,\"diagnostic_only\":true}\n",
        static_cast<unsigned long long>(now),items.count);
    }
    return gates;
}
inline void sample(bool us_update,bool pc_menu=false) {
    static const auto address=[] {
        const char* text=std::getenv("SKY_LEVEL_EVENT_MAILBOX");
        std::uintptr_t value=0;
        if(!text)return value;
        const auto end=text+std::strlen(text);
        const auto parsed=std::from_chars(text,end,value);
        if(parsed.ec!=std::errc{} || parsed.ptr!=end || value<0x400000 ||
           value>0x20000000-20480 || value%8)return std::uintptr_t{0};
        return value;
    }();
    if(!address)return;
    const auto now=TrapTeamProbe::timestamp();
    static std::atomic<std::uint64_t> last=0;
    auto previous=last.load(std::memory_order_relaxed);
    if((!SkyPc::automatic.load() && now-previous<100000) || !last.compare_exchange_strong(previous,now,std::memory_order_relaxed))return;
    static std::mutex lock;
    std::unique_lock guard(lock,std::try_to_lock);
    if(!guard.owns_lock())return;
    const auto gates=runtime_gates(now,pc_menu,us_update);
    static TrapFramePolicy::State policy;
    static LevelProtocol::Cursor cursor;
    const auto result=LevelProtocol::drain(address,cursor,TrapTeamProbe::read,[now](const LevelProtocol::Event& event) {
        policy.consume(event);
        std::string escaped;
        for(char ch:event.label()) {if(ch=='"' || ch=='\\')escaped+='\\';escaped+=ch;}
        const char* kind=event.kind==1?"switch":event.kind==2?"commit":"load-begin";
        std::fprintf(stderr,"{\"event\":\"trap-level-event\",\"observed_us\":%llu,\"sequence\":%llu,\"kind\":\"%s\",\"name\":\"%s\",\"diagnostic_only\":true}\n",
            static_cast<unsigned long long>(now),static_cast<unsigned long long>(event.sequence),kind,escaped.c_str());
    });
    if(result!=LevelProtocol::Result::Ok)policy.lost();
    const auto decision=policy.decide(gates);
    const bool actuated=SkyPc::automatic.load();
    static TrapFramePolicy::Upshift upshift;
    const int applied=upshift.apply(decision.fps,now,policy.generation());
    if(actuated)SkyPc::apply_automatic_limit(applied);
    static std::string old_phase;
    if(old_phase!=decision.phase) {
        old_phase=decision.phase;
        std::fprintf(stderr,"{\"event\":\"trap-frame-policy-observation\",\"observed_us\":%llu,\"phase\":\"%s\",\"wanted_fps\":%d,\"control_valid\":%s,\"active_script_groups\":%u,\"cutscenes_valid\":%s,\"cutscenes\":%u,\"actuated\":%s}\n",
            static_cast<unsigned long long>(now),old_phase.c_str(),decision.fps,gates.control_valid?"true":"false",gates.active_script_groups,
            gates.cutscenes_valid?"true":"false",gates.cutscenes,actuated?"true":"false");
    }
    static auto previous_result=LevelProtocol::Result::Ok;
    if(result!=previous_result && result!=LevelProtocol::Result::Ok)
        std::fprintf(stderr,"{\"event\":\"trap-level-event-reader-error\",\"code\":%u,\"diagnostic_only\":true}\n",static_cast<unsigned>(result));
    previous_result=result;
}
}

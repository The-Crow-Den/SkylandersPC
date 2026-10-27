// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Optional read-only research probe. No game state or timing is modified.
// Fixed addresses are valid only for builds matched in trap_team_hooks.cpp.
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>
#include <string_view>
#include <mutex>
#include <fcntl.h>
#include <time.h>
#include <unistd.h>

namespace TrapTeamProbe {
inline bool read(std::uintptr_t address, void* output, std::size_t size) {
    struct Memory {
        int fd=open("/proc/self/mem",O_RDONLY|O_CLOEXEC);
        ~Memory() {if(fd>=0)close(fd);}
    };
    static Memory memory;
    return memory.fd>=0 && pread(memory.fd,output,size,static_cast<off_t>(address))==static_cast<ssize_t>(size);
}
template<class T, std::size_t N>
T field(const std::array<unsigned char,N>& data, std::size_t offset) {
    T result{};
    if (offset <= N && sizeof(T) <= N-offset) std::memcpy(&result,data.data()+offset,sizeof(T));
    return result;
}
template<std::size_t N>
std::string hex(const std::array<unsigned char,N>& data) {
    constexpr char digits[]="0123456789abcdef";
    std::string result(N*2,'0');
    for(std::size_t i=0;i<N;++i) {
        result[2*i]=digits[data[i]>>4]; result[2*i+1]=digits[data[i]&15];
    }
    return result;
}
inline std::uint64_t timestamp() {
    timespec t{}; clock_gettime(CLOCK_MONOTONIC,&t);
    return std::uint64_t(t.tv_sec)*1000000+std::uint64_t(t.tv_nsec)/1000;
}
inline bool enabled() {
    static const bool value=[] {const auto* p=std::getenv("SKY_TRAP_PHASE_PROBE");return p && !std::strcmp(p,"1");}();
    return value;
}
inline std::uintptr_t service(std::uintptr_t directory,std::uintptr_t type) {
    std::int16_t index=-1;
    std::uintptr_t list=0,storage=0,object=0;
    std::uint32_t count=0;
    if(!read(type+128,&index,sizeof(index)) || index<0 || index>=4096 ||
       !read(directory+104,&list,sizeof(list)) ||
       !read(list+12,&count,sizeof(count)) || count>4096 || unsigned(index)>=count ||
       !read(list+32,&storage,sizeof(storage)) ||
       storage>UINTPTR_MAX-unsigned(index)*sizeof(object) ||
       !read(storage+unsigned(index)*sizeof(object),&object,sizeof(object)))return 0;
    return object;
}
struct PointerList {
    bool valid=false;
    std::uint32_t count=0;
    std::uintptr_t storage=0;
};
inline PointerList pointer_list(std::uintptr_t address, std::uint32_t limit=256) {
    std::array<unsigned char,40> data{};
    if(!address || !read(address,data.data(),data.size()))return {};
    const auto count=field<std::uint32_t>(data,12),capacity=field<std::uint32_t>(data,16);
    const auto storage=field<std::uintptr_t>(data,32);
    if(count>capacity || count>limit || (count && (!storage || storage>UINTPTR_MAX-count*8ull)))return {};
    return {true,count,storage};
}
inline bool list_item(const PointerList& list,std::uint32_t index,std::uintptr_t& value) {
    return list.valid && index<list.count && read(list.storage+index*8ull,&value,sizeof(value));
}
inline std::uintptr_t activity_manager(std::uintptr_t core) {
    std::uintptr_t updaters=0,list_address=0;
    if(!read(core+64,&updaters,sizeof(updaters)) ||
       !read(updaters+16,&list_address,sizeof(list_address)))return 0;
    const auto list=pointer_list(list_address);
    for(std::uint32_t i=0;i<list.count;++i) {
        std::uintptr_t object=0,vtable=0;
        if(!list_item(list,i,object) || !object)continue;
        if(read(object,&vtable,sizeof(vtable)) && vtable==0xf36e00)return object;
    }
    return 0;
}
struct Players {bool valid=false;std::uint32_t count=0;};
inline Players players(std::uintptr_t manager) {
    std::uintptr_t groups_address=0;
    if(!manager || !read(manager+16,&groups_address,sizeof(groups_address)))return {};
    const auto groups=pointer_list(groups_address);
    if(!groups.valid)return {};
    Players result{true,0};
    for(std::uint32_t i=0;i<groups.count;++i) {
        std::uintptr_t group=0;
        if(!list_item(groups,i,group))return {};
        if(!group)continue;
        const auto placements=pointer_list(group,4096);
        if(!placements.valid)return {};
        for(std::uint32_t j=0;j<placements.count;++j) {
            std::uintptr_t placement=0;
            std::uint32_t state=0xffffffff;
            if(!list_item(placements,j,placement))return {};
            if(!placement)continue;
            if(!read(placement+112,&state,sizeof(state)))return {};
            if(state==0)++result.count;
        }
    }
    return result;
}
inline void script_samples(std::uintptr_t core) {
    const auto address=activity_manager(core);
    const auto player=players(address);
    std::fprintf(stderr,"{\"event\":\"trap-player-probe\",\"monotonic_us\":%llu,\"manager\":%llu,\"valid\":%s,\"players\":%u}\n",
        static_cast<unsigned long long>(timestamp()),static_cast<unsigned long long>(address),
        player.valid?"true":"false",player.count);
}
inline void viewport_samples() {
    std::uintptr_t directory=0,type=0;
    if(!read(0x10a0a30,&directory,sizeof(directory)) ||
       !read(0x103b7d0,&type,sizeof(type)))return;
    const auto system=service(directory,type);
    if(!system)return;
    std::array<unsigned char,56> data{};
    if(!read(system,data.data(),data.size()))return;
    for(unsigned slot: {16u,24u,32u}) {
        const auto viewport=field<std::uintptr_t>(data,slot);
        std::array<unsigned char,480> view{};
        if(!viewport || !read(viewport,view.data(),view.size()))continue;
        std::fprintf(stderr,"{\"event\":\"trap-viewport-probe\",\"monotonic_us\":%llu,\"slot\":%u,\"address\":%llu,\"enabled\":%u,\"content\":%u,\"wanted\":%u,\"cutscene\":%llu,\"controller\":%llu}\n",
            static_cast<unsigned long long>(timestamp()),slot,static_cast<unsigned long long>(viewport),
            unsigned(view[332]),field<std::uint32_t>(view,428),field<std::uint32_t>(view,436),
            static_cast<unsigned long long>(field<std::uintptr_t>(view,368)),
            static_cast<unsigned long long>(field<std::uintptr_t>(view,360)));
    }
}
struct PauseStack {
    bool valid=false;
    std::uint32_t depth=0, token=0;
};
// Diagnostic only: inspect the renderer's bounded frame arenas, never the
// general heap. A matching provider table identifies the time getter's input,
// but does not identify a particular material or prove a GPU uniform's value.
inline void render_node_clocks(std::uint64_t now) {
    unsigned char active=0;
    if(!read(0x108b4c0,&active,1) || !active)return;
    for(unsigned slot=0;slot<3;++slot) {
        std::uintptr_t buffer=0;
        std::array<unsigned char,32> header{},after{};
        if(!read(0x108b4d0+slot*8ull,&buffer,8) || !buffer ||
           !read(buffer+0x82008,header.data(),header.size()))continue;
        const auto arena=field<std::uintptr_t>(header,0);
        const auto capacity=field<std::uint32_t>(header,8);
        const auto used=field<std::uint32_t>(header,12);
        const auto world=field<float>(header,28);
        if(!arena || !used || used>capacity || capacity>32*1024*1024 ||
           used<132 || arena>UINTPTR_MAX-used || !std::isfinite(world))continue;
        std::vector<unsigned char> bytes(used);
        if(!read(arena,bytes.data(),bytes.size()) ||
           !read(buffer+0x82008,after.data(),after.size()) || header!=after)continue;
        unsigned count=0,world_count=0,invalid=0,reported=0;
        for(std::size_t offset=0;offset+132<=bytes.size();offset+=8) {
            std::uintptr_t table=0;std::memcpy(&table,bytes.data()+offset,8);
            if(table!=0xf692a0 && table!=0xf69310)continue;
            float seconds=0;std::memcpy(&seconds,bytes.data()+offset+128,4);
            ++count;
            if(!std::isfinite(seconds)) {++invalid;continue;}
            if(std::fabs(seconds-world)<0.001f) {++world_count;continue;}
            if(reported++<16)std::fprintf(stderr,
                "{\"event\":\"trap-node-clock\",\"observed_us\":%llu,\"slot\":%u,\"offset\":%zu,\"provider_type\":%u,\"seconds\":%.9g,\"world_seconds\":%.9g,\"diagnostic_only\":true}\n",
                static_cast<unsigned long long>(now),slot,offset,table==0xf692a0?2u:3u,seconds,world);
        }
        std::fprintf(stderr,
            "{\"event\":\"trap-node-clock-summary\",\"observed_us\":%llu,\"slot\":%u,\"world_seconds\":%.9g,\"nodes\":%u,\"world_clock_nodes\":%u,\"invalid_nodes\":%u,\"diagnostic_only\":true}\n",
            static_cast<unsigned long long>(now),slot,world,count,world_count,invalid);
    }
}
inline PauseStack pause_stack(std::uintptr_t address) {
    std::array<unsigned char,40> data{};
    if(!read(address,data.data(),data.size()))return {};
    const auto count=field<std::uint32_t>(data,12);
    const auto capacity=field<std::uint32_t>(data,16);
    const auto storage=field<std::uintptr_t>(data,32);
    if(count>capacity || capacity>256)return {};
    PauseStack result{true,count,0};
    if(count && (storage>UINTPTR_MAX-(count-1)*sizeof(std::uint32_t) ||
        !read(storage+(count-1)*sizeof(std::uint32_t),&result.token,sizeof(result.token)))) return {};
    return result;
}
inline void clock_sample() {
    static const bool active=[] {const auto* p=std::getenv("SKY_TRAP_CLOCK_PROBE");return p && !std::strcmp(p,"1");}();
    if(!active)return;
    static std::atomic<std::uint64_t> last=0;
    const auto now=timestamp();auto previous=last.load();
    if(now-previous<500000 || !last.compare_exchange_strong(previous,now))return;
    std::uintptr_t app=0,core=0,clock=0,vt=0;
    std::array<unsigned char,40> data{};
    if(!read(0x1087480,&app,8) || !app || !read(app+96,&core,8) || !core ||
       !read(core+40,&clock,8) || !clock || !read(clock,&vt,8) || vt!=0xfd0570 ||
       !read(clock,data.data(),data.size()))return;
    std::uintptr_t directory=0,type=0;float shader_seconds=0;
    const bool shader_valid=read(0x10a0a30,&directory,8) && read(0x103b4c0,&type,8) &&
        directory && type && [&] {const auto parameters=service(directory,type);std::uintptr_t table=0;
            return parameters && read(parameters,&table,8) && table==0xf34ba0 && read(parameters+208,&shader_seconds,4);}();
    std::fprintf(stderr,"{\"event\":\"trap-render-clock\",\"observed_us\":%llu,\"active\":%u,\"scale\":%.9g,\"minimum_step\":%.9g,\"maximum_step\":%.9g,\"seconds\":%.9g,\"delta\":%.9g,\"shader_valid\":%s,\"shader_seconds\":%.9g,\"diagnostic_only\":true}\n",
        static_cast<unsigned long long>(now),unsigned(data[12]),field<float>(data,16),field<float>(data,20),field<float>(data,24),
        field<std::int32_t>(data,28)/8192.0,field<float>(data,32),shader_valid?"true":"false",shader_seconds);
    render_node_clocks(now);
}
inline void sample() {
    clock_sample();
    if(!enabled()) return;
    static std::atomic<std::uint64_t> last_sample=0;
    const auto now=timestamp();
    auto previous=last_sample.load(std::memory_order_relaxed);
    if(now-previous<500000 || !last_sample.compare_exchange_strong(previous,now,std::memory_order_relaxed)) return;
    static std::mutex sampling;
    std::unique_lock guard(sampling,std::try_to_lock);
    if(!guard.owns_lock())return;
    // Two independent unchanged instruction sites corroborate the reflected
    // object offsets. Diagnostic only: this is not an automatic patch gate.
    constexpr std::array<unsigned char,16> expected{
        0xc5,0xfa,0x10,0x88,0xc0,0,0,0,0xc5,0xfa,0x10,0x80,0xc4,0,0,0};
    std::array<unsigned char,16> code{};
    if(!read(0x4945d2,code.data(),code.size()) || code!=expected) return;
    std::uintptr_t app=0;
    if(!read(0x1087480,&app,sizeof(app)) || app<0x400000 || app>=0x2000000000ull) return;
    std::array<unsigned char,208> data{};
    if(!read(app,data.data(),data.size())) return;
    if(field<std::uint32_t>(data,188)>0) {script_samples(field<std::uintptr_t>(data,96));viewport_samples();}
    const auto layer=field<std::uint32_t>(data,40);
    const auto logic=field<std::uint64_t>(data,48),stack=field<std::uint64_t>(data,168);
    std::array<unsigned char,24> logic_data{};
    std::array<unsigned char,56> stack_data{};
    const auto bounded=[](std::uint64_t p) {return p>=0x400000 && p<0x2000000000ull;};
    const auto logic_hex=bounded(logic)&&read(logic,logic_data.data(),logic_data.size())?hex(logic_data):std::string{};
    const auto stack_hex=bounded(stack)&&read(stack,stack_data.data(),stack_data.size())?hex(stack_data):std::string{};
    unsigned char platform_pause=255;
    if(!read(app+1680,&platform_pause,1))platform_pause=255;
    const auto app_hex=hex(data);
    const auto pause=pause_stack(stack);
    std::fprintf(stderr,"{\"event\":\"trap-pause-stack\",\"monotonic_us\":%llu,\"valid\":%s,\"depth\":%u,\"token\":%u}\n",
        static_cast<unsigned long long>(now),pause.valid?"true":"false",pause.depth,pause.token);
    std::fprintf(stderr,"{\"event\":\"trap-phase-probe\",\"monotonic_us\":%llu,\"app\":%llu,\"state\":%u,\"render_disabled\":%u,\"time_layer\":%u,\"frame_layer\":%u,\"frame\":%u,\"presentation_bits\":%u,\"delta_bits\":%u,\"platform_pause\":%u,\"app_hex\":\"%s\",\"logic_hex\":\"%s\",\"stack_hex\":\"%s\"}\n",
        static_cast<unsigned long long>(timestamp()),static_cast<unsigned long long>(app),
        field<std::uint32_t>(data,24),unsigned(data[32]),field<std::uint32_t>(data,36),
        layer,field<std::uint32_t>(data,188),field<std::uint32_t>(data,192),field<std::uint32_t>(data,196),
        unsigned(platform_pause),app_hex.c_str(),logic_hex.c_str(),stack_hex.c_str());
}
}

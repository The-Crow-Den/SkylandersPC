// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
// US 01.01 reflection layout, enabled only by its exact-build event profile.
// An empty movie list proves no movie object is attached. A nonempty list is
// conservatively treated as video, even if a codec is preparing/finishing it.
namespace TrapMovieGate {
struct Result {bool valid=false;std::uint32_t count=0;};
template<class Read> Result sample(Read read) {
    auto word=[&](std::uintptr_t address,std::uintptr_t& value) {return read(address,&value,8);};
    std::uintptr_t directory=0,type=0,services=0,storage=0,system=0,player=0,list=0,data=0;
    std::int16_t index=-1;
    std::uint32_t count=0,capacity=0;
    if(!word(0x10a0a30,directory) || !directory || !word(0x10876f8,type) || !type ||
       !read(type+128,&index,2) || index<0 || index>=4096 ||
       !word(directory+104,services) || !services ||
       !read(services+12,&count,4) || !read(services+16,&capacity,4) ||
       count>capacity || count>4096 || unsigned(index)>=count ||
       !word(services+32,storage) || !storage || storage>UINTPTR_MAX-unsigned(index)*8ull ||
       !word(storage+unsigned(index)*8ull,system) || !system ||
       !word(system+16,player) || !player || !word(player+40,list) || !list ||
       !read(list+12,&count,4) || !read(list+16,&capacity,4) ||
       count>capacity || count>64 || !word(list+32,data) ||
       (count && (!data || data>UINTPTR_MAX-count*8ull)))return {};
    // Re-resolve the service's player/list and count across unload transitions.
    std::uintptr_t check_player=0,check_list=0;
    std::uint32_t check_count=0;
    if(!word(system+16,check_player) || check_player!=player ||
       !word(player+40,check_list) || check_list!=list ||
       !read(list+12,&check_count,4) || check_count!=count)return {};
    return {true,count};
}
}

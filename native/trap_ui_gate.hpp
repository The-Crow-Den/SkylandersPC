// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>
#include <cstring>
namespace TrapUiGate {
struct Result {bool valid=false,gameplay=false,pause=false,portal=false;};
// Exact-build global level directory, not a heap scan or cached actor pointer.
// Fixed directory slots are corroborated by each object's type AND full name.
// Re-resolve on every sample so unloading/replacing the directory fails closed.
template<class Read> Result sample(Read read) {
    auto word=[&](std::uintptr_t address,std::uintptr_t& value) {return read(address,&value,8);};
    std::uintptr_t node=0,vt=0,directory=0,list=0,storage=0;
    std::uint32_t count=0,capacity=0;
    if(!word(0x1039d40,node) || !node || !word(node,vt) || vt!=0xf5d700 ||
       !word(node+296,directory) || !directory || !word(directory,vt) || vt!=0xf86cd0 ||
       !word(directory+40,list) || !list || !word(list,vt) || vt!=0xf798b0 ||
       !read(list+12,&count,4) || !read(list+16,&capacity,4) ||
       count<311 || count>10000 || count>capacity || !word(list+32,storage) || !storage ||
       storage>UINTPTR_MAX-311*8)return {};
    constexpr std::array<unsigned,3> indices{284,287,310};
    constexpr const char* names[]{"_Gameplay_Container","_UI_PauseContainer","PortalUI_Container"};
    std::array<bool,3> visible{};
    for(unsigned i=0;i<3;++i) {
        std::uintptr_t object=0,name=0;
        std::array<char,32> text{};
        std::uint32_t flags=0;
        if(!word(storage+indices[i]*8,object) || !object || object>UINTPTR_MAX-248 ||
           !word(object,vt) || vt!=0xf378b0 || !word(object+16,name) || !name ||
           !read(name,text.data(),text.size()) || !std::memchr(text.data(),0,text.size()) ||
           std::strcmp(text.data(),names[i]) || !read(object+244,&flags,4))return {};
        visible[i]=(flags&(1u<<16))!=0;
    }
    return {true,visible[0],visible[1],visible[2]};
}
}

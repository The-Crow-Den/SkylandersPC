// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
// Read-only diagnostics for the exact updated US build. Never reads PCM,
// invokes a guest function, scans a heap, or changes portal state.
namespace TrapPortalAudioProbe {
template<class Read> void sample(Read read) {
    static const bool enabled=[] {const auto* value=std::getenv("SKY_PORTAL_AUDIO_PROBE");return value && !std::strcmp(value,"1");}();
    if(!enabled)return;
    std::uintptr_t portal=0,buffer=0,vtable=0,position_getter=0;
    std::uint32_t length=0;
    if(!read(0x103ca40,&portal,8) || !read(0x103ca48,&buffer,8) || !read(0x103ca50,&length,4))return;
    if(portal && (!read(portal,&vtable,8) || vtable<0xc00000 || vtable>0x1100000 || !read(vtable+0xc0,&position_getter,8)))return;
    static std::uintptr_t old_portal=UINTPTR_MAX,old_buffer=UINTPTR_MAX;
    static std::uint32_t old_length=UINT32_MAX;
    if(portal==old_portal && buffer==old_buffer && length==old_length)return;
    old_portal=portal;old_buffer=buffer;old_length=length;
    std::fprintf(stderr,"{\"event\":\"portal-audio-state-probe\",\"portal\":%llu,\"buffer\":%llu,\"length\":%u,\"vtable\":%llu,\"position_getter\":%llu,\"diagnostic_only\":true}\n",
        static_cast<unsigned long long>(portal),static_cast<unsigned long long>(buffer),length,
        static_cast<unsigned long long>(vtable),static_cast<unsigned long long>(position_getter));
}
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstring>
#include <string>
#include "platform/host_files.hpp"

namespace PcOverlay {
class FrameReader {
    static constexpr std::size_t header=64,capacity=3840*2160*4,total=header+capacity;
    SkyHost::PrivateFileMapping mapping;
public:
    explicit FrameReader(const char* path) {
        if(path)mapping.open(std::filesystem::path(std::u8string(path,path+std::strlen(path))),total);
    }
    FrameReader(const FrameReader&)=delete;
    FrameReader& operator=(const FrameReader&)=delete;
    bool copy(void* pixels,int size,int* width,int* height,unsigned* generation) const {
        const auto* memory=static_cast<const std::uint32_t*>(mapping.data());
        if(!memory||!pixels||!width||!height||!generation||memory[0]!=0x534b594d)return false;
        const auto before=__atomic_load_n(memory+1,__ATOMIC_ACQUIRE);
        if(!before||(before&1)||before==*generation)return false;
        const auto w=memory[2],h=memory[3],bytes=memory[4];
        if(!w||w>3840||!h||h>2160||bytes!=w*h*4||size<0||bytes>static_cast<unsigned>(size))return false;
        std::memcpy(pixels,reinterpret_cast<const unsigned char*>(memory)+header,bytes);
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if(before!=__atomic_load_n(memory+1,__ATOMIC_ACQUIRE))return false;
        *width=static_cast<int>(w);*height=static_cast<int>(h);*generation=before;return true;
    }
};
}

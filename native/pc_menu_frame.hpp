// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace PcOverlay {
class FrameReader {
    static constexpr std::size_t header=64,capacity=3840*2160*4,total=header+capacity;
    const std::uint32_t* memory=nullptr;
public:
    explicit FrameReader(const char* path) {
        if(!path)return;
        const int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
        if(fd<0)return;
        struct stat info{};
        if(fstat(fd,&info)==0&&S_ISREG(info.st_mode)&&info.st_uid==getuid()&&
           (info.st_mode&077)==0&&info.st_size==total) {
            const auto* address=mmap(nullptr,total,PROT_READ,MAP_SHARED,fd,0);
            if(address!=MAP_FAILED)memory=static_cast<const std::uint32_t*>(address);
        }
        close(fd);
    }
    ~FrameReader(){if(memory)munmap(const_cast<std::uint32_t*>(memory),total);}
    FrameReader(const FrameReader&)=delete;
    FrameReader& operator=(const FrameReader&)=delete;
    bool copy(void* pixels,int size,int* width,int* height,unsigned* generation) const {
        if(!memory||!pixels||!width||!height||!generation||memory[0]!=0x534b594d)return false;
        const auto before=__atomic_load_n(memory+1,__ATOMIC_ACQUIRE);
        if(!before||(before&1)||before==*generation)return false;
        const auto w=memory[2],h=memory[3],bytes=memory[4];
        if(!w||w>3840||!h||h>2160||bytes!=w*h*4||size<0||bytes>static_cast<unsigned>(size))return false;
        std::memcpy(pixels,reinterpret_cast<const unsigned char*>(memory)+header,bytes);
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if(before!=__atomic_load_n(memory+1,__ATOMIC_ACQUIRE))return false;
        *width=w;*height=h;*generation=before;return true;
    }
};
}

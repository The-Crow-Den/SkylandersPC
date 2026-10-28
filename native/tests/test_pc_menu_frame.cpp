// SPDX-License-Identifier: GPL-3.0-or-later
#include "../pc_menu_frame.hpp"
#include <array>
#include <stdexcept>
#include <iostream>

int main(){
    const auto check=[](bool ok){if(!ok)throw std::runtime_error("PC menu frame assertion");};
    char path[]="/tmp/sky-menu-frame-XXXXXX";
    const int fd=mkstemp(path);
    if(fd<0)return 1;
    constexpr std::size_t size=64+3840*2160*4;
    if(ftruncate(fd,size)!=0){close(fd);unlink(path);return 1;}
    auto* memory=static_cast<std::uint32_t*>(mmap(nullptr,size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0));
    close(fd);if(memory==MAP_FAILED){unlink(path);return 1;}
    int result=0;
    try{
        PcOverlay::FrameReader reader(path);
        std::array<unsigned char,8> pixels{};int width=0,height=0;unsigned generation=0;
        const auto copy=[&]{return reader.copy(pixels.data(),pixels.size(),&width,&height,&generation);};
        memory[0]=0x534b594d;memory[1]=2;memory[2]=2;memory[3]=1;memory[4]=8;
        std::memcpy(reinterpret_cast<unsigned char*>(memory)+64,"RGBAdata",8);
        check(copy()&&width==2&&height==1&&generation==2&&std::memcmp(pixels.data(),"RGBAdata",8)==0);
        check(!copy()); // Do not upload the same generation again.
        memory[1]=3;check(!copy()); // Writer has not finished.
        memory[1]=4;memory[2]=3841;check(!copy());
        memory[2]=2;memory[4]=9;check(!copy());
        memory[4]=8;check(!reader.copy(pixels.data(),7,&width,&height,&generation));
        memory[0]=0;check(!copy());memory[0]=0x534b594d;
        check(copy()&&generation==4);
        const std::string link=std::string(path)+"-link";
        check(symlink(path,link.c_str())==0);
        PcOverlay::FrameReader symlink_reader(link.c_str());generation=0;
        check(!symlink_reader.copy(pixels.data(),8,&width,&height,&generation));unlink(link.c_str());
        chmod(path,0644);PcOverlay::FrameReader public_reader(path);
        check(!public_reader.copy(pixels.data(),8,&width,&height,&generation));
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';result=1;}
    munmap(memory,size);unlink(path);return result;
}

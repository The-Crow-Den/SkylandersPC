// SPDX-License-Identifier: GPL-3.0-or-later
#include "../trap_movie_skip.hpp"
#include <cstring>
#include <map>
#include <stdexcept>
#include <vector>
int main() {
    auto check=[](bool ok){if(!ok)throw std::runtime_error("Trap movie skip contract");};
    std::map<std::uintptr_t,unsigned char> memory;
    auto put=[&](std::uintptr_t address,const void* value,std::size_t size) {
        for(std::size_t i=0;i<size;++i)memory[address+i]=static_cast<const unsigned char*>(value)[i];
    };
    auto read=[&](std::uintptr_t address,void* out,std::size_t size) {
        for(std::size_t i=0;i<size;++i) {
            const auto found=memory.find(address+i);
            if(found==memory.end())return false;
            static_cast<unsigned char*>(out)[i]=found->second;
        }
        return true;
    };
    auto state=[&](std::uintptr_t info) {std::int32_t value=0;read(info+TrapMovieSkip::kState,&value,4);return value;};
    auto movie=[&](std::uintptr_t info,const char* path,std::int32_t value,std::int32_t type=3) {
        const std::uintptr_t text=info+0x1000;
        put(text,path,std::strlen(path)+1);put(info+TrapMovieSkip::kPath,&text,8);
        put(info+TrapMovieSkip::kType,&type,4);put(info+TrapMovieSkip::kState,&value,4);
    };
    std::vector<std::string> skipped;
    auto end=[&](std::uintptr_t address) {
        std::int32_t value=0;read(address,&value,4);
        if(value!=TrapMovieSkip::kPlay)return false;
        value=TrapMovieSkip::kEnded;put(address,&value,4);return true;
    };
    auto report=[&](const TrapMovieSkip::Skipped& item){skipped.push_back(item.name);};
    const std::uintptr_t list=0x100000,logo=0x200000,fmv=0x300000,music=0x400000;
    auto entries=[&](std::vector<std::uintptr_t> items){for(std::size_t i=0;i<items.size();++i)put(list+i*8,&items[i],8);};

    check(TrapMovieSkip::movie_name("app0:/movies/fmv1.mov")=="fmv1");
    check(TrapMovieSkip::movie_name("tfb_logo_640x456")=="tfb_logo_640x456");

    // Startup logos end as soon as they play; story movies are left alone.
    TrapMovieSkip::Skipper skipper;
    TrapMovieSkip::Settings startup{true,false};
    movie(logo,"movies/atvinewlogo_640.mov",TrapMovieSkip::kLoading);movie(fmv,"movies/fmv1.mov",TrapMovieSkip::kPlay);
    entries({logo,fmv});
    skipper.frame(list,2,true,0,false,startup,read,end,report);
    check(skipped.empty() && state(logo)==TrapMovieSkip::kLoading); // not playing yet
    movie(logo,"movies/atvinewlogo_640.mov",TrapMovieSkip::kPlay);
    skipper.frame(list,2,true,TrapMovieSkip::kCross,false,startup,read,end,report);
    check(skipped==std::vector<std::string>{"atvinewlogo_640"} && state(logo)==TrapMovieSkip::kEnded);
    check(state(fmv)==TrapMovieSkip::kPlay); // button skipping is off

    // A press only skips a movie that was already listed on an earlier frame.
    skipped.clear();
    TrapMovieSkip::Skipper buttons;
    TrapMovieSkip::Settings any{false,true};
    entries({fmv});
    buttons.frame(list,1,true,TrapMovieSkip::kCross,false,any,read,end,report);
    check(skipped.empty() && state(fmv)==TrapMovieSkip::kPlay);
    buttons.frame(list,1,true,0x10,false,any,read,end,report); // triangle does nothing
    check(skipped.empty());
    buttons.frame(list,1,true,TrapMovieSkip::kCross,true,any,read,end,report); // PC menu has input
    check(skipped.empty());
    buttons.frame(list,1,true,TrapMovieSkip::kOptions,false,any,read,end,report);
    check(skipped==std::vector<std::string>{"fmv1"} && state(fmv)==TrapMovieSkip::kEnded);

    // Audio-only streams, finished movies and unreadable lists are never touched.
    skipped.clear();
    movie(music,"movies/soulgem_450.mov",TrapMovieSkip::kPlay,2);
    entries({music});
    buttons.frame(list,1,true,0,false,any,read,end,report);
    buttons.frame(list,1,true,TrapMovieSkip::kCross,false,any,read,end,report);
    check(skipped.empty() && state(music)==TrapMovieSkip::kPlay);
    buttons.frame(list,1,false,TrapMovieSkip::kCross,false,any,read,end,report);
    buttons.frame(list,65,true,TrapMovieSkip::kCross,false,any,read,end,report);
    check(skipped.empty());
    TrapMovieSkip::Skipper off;
    movie(fmv,"movies/fmv1.mov",TrapMovieSkip::kPlay);entries({fmv});
    off.frame(list,1,true,0,false,{},read,end,report);
    off.frame(list,1,true,TrapMovieSkip::kCross,false,{},read,end,report);
    check(skipped.empty() && state(fmv)==TrapMovieSkip::kPlay);
}

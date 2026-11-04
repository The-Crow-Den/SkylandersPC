// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Movie skipping for the US 01.01 build (callers match the exact executable in
// trap_team_hooks.cpp). A playing igMovieInfo is moved from PLAY to ENDED, the
// same state the codec reaches at the last frame, so the movie system runs its
// normal end-of-movie path and whatever the game does after a movie (flags,
// saves, level changes) is unchanged. Layout comes from the build's reflection
// tables: _type +72, _path +40, _state +172; IG_MOVIE_PLAY 3, IG_MOVIE_ENDED 5.
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <string_view>

namespace TrapMovieSkip {
constexpr std::uintptr_t kPath=40,kType=72,kState=172;
constexpr std::int32_t kLoading=1,kPlay=3,kEnded=5,kAudioOnly=2;
constexpr std::uint32_t kCross=0x4000,kOptions=0x8;
constexpr std::size_t kSlots=64;

struct Settings {bool any=false;};
inline Settings settings_from_environment() {
    auto on=[](const char* name){const auto* v=std::getenv(name);return v && !std::strcmp(v,"1");};
    return {on("SKY_SKIP_CUTSCENES")};
}
inline std::string movie_name(std::string_view path) {
    if(const auto slash=path.find_last_of("/\\");slash!=path.npos)path.remove_prefix(slash+1);
    if(const auto dot=path.rfind('.');dot!=path.npos)path=path.substr(0,dot);
    return std::string(path);
}

struct Skipped {std::uintptr_t info;std::string name;};

// Read(address,out,size) -> bool reads guest memory; End(state address) moves
// PLAY to ENDED atomically and returns false if the movie changed state first.
class Skipper {
public:
    template<class Read,class End,class Report>
    void frame(std::uintptr_t data,std::uint32_t count,bool valid,std::uint32_t presses,bool input_blocked,
               const Settings& settings,Read read,End end,Report report) {
        std::array<std::uintptr_t,kSlots> current{};
        std::array<std::string,kSlots> names;
        if(!valid || count>kSlots)count=0;
        // Only a press made while a movie is already on screen skips it, so
        // the press that started a movie (or an earlier menu press) does not.
        const bool skip=settings.any && !input_blocked && (presses&(kCross|kOptions));
        for(std::uint32_t i=0;i<count;++i) {
            std::uintptr_t info=0;std::int32_t state=0,type=0;
            if(!read(data+i*8ull,&info,8) || !info || !read(info+kType,&type,4) || type==kAudioOnly ||
               !read(info+kState,&state,4))continue;
            current[i]=info;
            const auto* known=seen(info);
            names[i]=known && !known->empty()?*known:movie_name(path(read,info));
            if(state!=kPlay)continue;
            if(!skip || !known)continue;
            if(end(info+kState))report(Skipped{info,names[i]});
        }
        seen_=current;names_=std::move(names);
    }
private:
    const std::string* seen(std::uintptr_t info) const {
        for(std::size_t i=0;i<kSlots;++i)if(seen_[i]==info)return &names_[i];
        return nullptr;
    }
    template<class Read> static std::string path(Read read,std::uintptr_t info) {
        std::uintptr_t text=0;std::array<char,128> buffer{};
        if(!read(info+kPath,&text,8) || !text)return {};
        for(std::size_t i=0;i+1<buffer.size();++i)
            if(!read(text+i,&buffer[i],1) || !buffer[i])break;
        return buffer.data();
    }
    std::array<std::uintptr_t,kSlots> seen_{};
    std::array<std::string,kSlots> names_;
};
}

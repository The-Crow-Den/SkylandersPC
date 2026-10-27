// SPDX-License-Identifier: GPL-3.0-or-later
#include "../level_event_protocol.hpp"
#include <vector>
#include <stdexcept>
#include <iostream>

int main() {
    using namespace LevelProtocol;
    const auto check=[](bool ok){if(!ok)throw std::runtime_error("level event protocol assertion");};
    try {
        std::vector<unsigned char> memory(64+capacity*record_size);
        const auto put=[&](std::size_t offset,std::uint64_t value){std::memcpy(memory.data()+offset,&value,8);};
        const auto reset=[&]{std::fill(memory.begin(),memory.end(),0);std::memcpy(memory.data(),"SKYLEV02",8);put(8,2);};
        const auto publish=[&](std::uint64_t ticket,std::uint64_t kind,const char* name){
            const auto offset=64+((ticket-1)%capacity)*record_size;
            std::fill(memory.begin()+static_cast<std::ptrdiff_t>(offset),memory.begin()+static_cast<std::ptrdiff_t>(offset+record_size),0);
            put(offset,ticket);put(offset+8,kind);std::memcpy(memory.data()+offset+32,name,std::strlen(name)+1);put(32,ticket);
        };
        const auto read=[&](std::uintptr_t offset,void* dest,std::size_t size){
            if(offset>memory.size() || size>memory.size()-offset)return false;
            std::memcpy(dest,memory.data()+offset,size);return true;
        };
        Cursor cursor;std::vector<Event> received;
        const auto collect=[&](const Event& event){received.push_back(event);};
        reset();publish(1,3,"misc/ui_pausemenu_streamed");publish(2,2,"misc0/ui_pausemenu_streamed");
        check(drain(0,cursor,read,collect)==Result::Ok && received.size()==2);
        check(received[0].label()=="misc/ui_pausemenu_streamed" && received[1].kind==2);
        check(drain(0,cursor,read,collect)==Result::Ok && received.size()==2);
        // Loss invalidates the stream instead of silently reconstructing state.
        publish(67,2,"level0/Level_313_Tutorial");
        check(drain(0,cursor,read,collect)==Result::Lost && cursor.consumed==67);
        put(40,1);check(drain(0,cursor,read,collect)==Result::Lost);
        reset();cursor={};publish(1,2,"bad");put(64+16,2);
        check(drain(0,cursor,read,collect)==Result::Invalid);
        reset();cursor={};publish(1,2,"bad");std::fill(memory.begin()+96,memory.begin()+288,'x');
        check(drain(0,cursor,read,collect)==Result::Invalid);
        reset();cursor={};publish(1,2,"bad\nname");
        check(drain(0,cursor,read,collect)==Result::Invalid);
        reset();cursor={};publish(1,2,"good");
        auto racing_read=[&](std::uintptr_t offset,void* dest,std::size_t size){
            const bool ok=read(offset,dest,size);
            if(offset==64 && size==224)put(64,65);
            return ok;
        };
        check(drain(0,cursor,racing_read,collect)==Result::Lost);
        reset();cursor={};memory[0]='?';check(drain(0,cursor,read,collect)==Result::Invalid);
        check(drain(1000000,cursor,read,collect)==Result::Unavailable);
        std::cout<<"named lifecycle event ordering, bounds, publication races and loss checks passed\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}

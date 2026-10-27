// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <string_view>

namespace LevelProtocol {
constexpr std::size_t capacity=64, record_size=256, name_size=192;
struct Cursor {std::uint64_t consumed=0,dropped=0;};
struct Event {
    std::uint64_t sequence=0,kind=0,flags=0,pool=0;
    std::array<char,name_size> name{};
    std::string_view label() const {return {name.data(),std::strlen(name.data())};}
};
enum class Result {Ok,Unavailable,Invalid,Lost};
template<class T,std::size_t N> T field(const std::array<unsigned char,N>& data,std::size_t offset) {
    T result{};std::memcpy(&result,data.data()+offset,sizeof(result));return result;
}
// Reader and writer never share C++ objects: safe external-memory reads check
// each immutable publication ticket again after copying its bounded record.
template<class Read,class Consume>
Result drain(std::uintptr_t address,Cursor& cursor,Read read,Consume consume) {
    std::array<unsigned char,64> header{};
    if(!read(address,header.data(),header.size()))return Result::Unavailable;
    if(std::memcmp(header.data(),"SKYLEV02",8)||field<std::uint64_t>(header,8)!=2)return Result::Invalid;
    const auto produced=field<std::uint64_t>(header,32),dropped=field<std::uint64_t>(header,40);
    if(produced<cursor.consumed || produced-cursor.consumed>capacity || dropped!=cursor.dropped) {
        cursor={produced,dropped};return Result::Lost;
    }
    while(cursor.consumed<produced) {
        const auto ticket=cursor.consumed+1;
        const auto slot=address+64+((ticket-1)%capacity)*record_size;
        std::array<unsigned char,224> data{};
        std::uint64_t verify=0;
        if(!read(slot,data.data(),data.size()) || !read(slot,&verify,sizeof(verify)))return Result::Unavailable;
        if(field<std::uint64_t>(data,0)!=ticket || verify!=ticket) {
            cursor={produced,dropped};return Result::Lost;
        }
        Event event{ticket,field<std::uint64_t>(data,8),field<std::uint64_t>(data,16),field<std::uint64_t>(data,24),{}};
        std::memcpy(event.name.data(),data.data()+32,name_size);
        if(event.kind<1 || event.kind>3 || event.flags || !std::memchr(event.name.data(),0,name_size)) {
            cursor={produced,dropped};return Result::Invalid;
        }
        for(const unsigned char ch:event.label())if(ch<32 || ch>126) {
            cursor={produced,dropped};return Result::Invalid;
        }
        consume(event);
        cursor.consumed=ticket;
    }
    return Result::Ok;
}
}

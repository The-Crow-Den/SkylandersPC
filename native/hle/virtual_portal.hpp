// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstddef>
#include <string_view>
#include <string>
namespace VirtualPortal {
// Swap Force halves: bottoms are tag IDs 1000-1015, tops 2000-2015.
enum class SwapperHalf { none, top, bottom };
constexpr SwapperHalf swapper_half(unsigned id) {
    return id>=1000 && id<=1015 ? SwapperHalf::bottom : id>=2000 && id<=2015 ? SwapperHalf::top : SwapperHalf::none;
}
bool enabled();
void bind_audio(void(*sink)(const unsigned char*,std::size_t));
bool supports(std::string_view identity);
unsigned stack_arguments(std::string_view identity);
std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
bool load(const char* path);
bool load_trap(const char* path);
bool replace_character(const char* path);
bool replace_player(const char* path,unsigned player);
bool replace_item(const char* path);
void remove_player(unsigned player);
void remove_swapper_half(unsigned player,bool bottom);
void remove_item();
// SuperChargers vehicles (tag IDs 3220-3299) sit in their own portal slot.
constexpr bool is_vehicle(unsigned id) {return id>=3220 && id<=3299;}
bool replace_vehicle(const char* path);
void remove_vehicle();
void remove_characters();
bool create_blank(const char* path, unsigned id, unsigned variant);
unsigned creation_count();
const char* creation_name(unsigned index);
bool creation_identity(unsigned index,unsigned& id,unsigned& variant);
std::string figure_name(unsigned id, unsigned variant);
void remove_trap();
void remove();
}

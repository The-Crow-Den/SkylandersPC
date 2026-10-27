// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstddef>
#include <string_view>
#include <string>
namespace VirtualPortal {
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
void remove_item();
void remove_characters();
bool create_blank(const char* path, unsigned id, unsigned variant);
unsigned creation_count();
const char* creation_name(unsigned index);
bool creation_identity(unsigned index,unsigned& id,unsigned& variant);
std::string figure_name(unsigned id, unsigned variant);
void remove_trap();
void remove();
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <string>
namespace PortalLibrary {
void initialize(const char* initial,const char* initial_bottom=nullptr);
bool import_character(const char* path, bool select,unsigned player=0);
bool create_character(int index,bool select_after=true,unsigned player=0);
bool select(int kind,int index);
bool select_empty_trap(int element);
void remove(int kind);
std::string status();
}
extern "C" {
int sky_portal_count(int kind);
const char* sky_portal_name(int kind,int index);
const char* sky_portal_detail(int kind,int index);
int sky_portal_state(int kind,int index);
int sky_portal_portrait(int kind,int index);
const char* sky_portal_status();
const char* sky_portal_atlas();
int sky_portal_element_portrait(int index);
int sky_portal_trap_element_count();
const char* sky_portal_trap_element_name(int index);
int sky_portal_trap_element(int index);
int sky_portal_trap_capture(int index);
int sky_portal_creation_portrait(int index);
int sky_portal_creation_count();
int sky_portal_creation_kind(int index);
const char* sky_portal_creation_name(int index);
}

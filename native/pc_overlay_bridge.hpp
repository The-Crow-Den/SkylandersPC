// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
union SDL_Event;
namespace PcOverlay {void start();void geometry(int x,int y,int width,int height);bool event(const SDL_Event&);}
extern "C" int sky_pc_external_menu();
extern "C" void sky_pc_menu_visibility(int visible);
extern "C" int sky_pc_menu_gamepad(int key);

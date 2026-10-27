// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <SDL3/SDL.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

// Optional private artwork, decoded during import; the runtime needs no image
// library and never reads or changes a guest game asset for its desktop icon.
inline void apply_window_icon() {
    const char* path = std::getenv("SKY_WINDOW_ICON_RGBA");
    if (!path || !*path) return;
    FILE* input = std::fopen(path, "rb");
    if (!input) return;
    std::array<unsigned char,16> header{};
    if (std::fread(header.data(),1,header.size(),input)!=header.size() ||
        std::memcmp(header.data(),"SKYICON1",8)) {std::fclose(input);return;}
    const auto little = [&](unsigned i) {
        return unsigned(header[i]) | (unsigned(header[i+1])<<8) |
               (unsigned(header[i+2])<<16) | (unsigned(header[i+3])<<24);
    };
    const unsigned width=little(8),height=little(12);
    if (!width || !height || width>1024 || height>1024) {std::fclose(input);return;}
    std::vector<unsigned char> pixels(std::size_t(width)*height*4);
    const bool valid=std::fread(pixels.data(),1,pixels.size(),input)==pixels.size() && std::fgetc(input)==EOF;
    std::fclose(input);
    if (!valid) return;
    auto* surface=SDL_CreateSurfaceFrom(int(width),int(height),SDL_PIXELFORMAT_RGBA32,pixels.data(),int(width*4));
    if (!surface) return;
    int count=0;auto** windows=SDL_GetWindows(&count);
    for (int i=0;i<count;++i) SDL_SetWindowIcon(windows[i],surface);
    SDL_free(windows);SDL_DestroySurface(surface);
}

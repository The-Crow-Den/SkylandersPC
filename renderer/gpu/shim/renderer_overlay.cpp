// SPDX-License-Identifier: GPL-2.0-or-later
#include "renderer_overlay.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

#include <SDL3/SDL.h>
#include "renderer_settings.h"
#include "imgui.h"
#include "imgui_internal.h"
#include "imgui_impl_vulkan.h"
#include "vulkan/instance.h"
#include "render/scheduler.h"

// DejaVu Sans (Cyrillic), embedded (third_party/fonts, Bitstream Vera license).
#ifdef _WIN32
#define SKY_RENDERER_FONT_SECTION ".section .rdata,\"dr\"\n"
#define SKY_RENDERER_FONT_HIDDEN(name) ""
#define SKY_RENDERER_FONT_END ".text\n"
#else
#define SKY_RENDERER_FONT_SECTION ".section .rodata\n"
#define SKY_RENDERER_FONT_HIDDEN(name) ".hidden " name "\n"
#define SKY_RENDERER_FONT_END ".previous\n"
#endif
asm(SKY_RENDERER_FONT_SECTION
    ".balign 16\n"
    SKY_RENDERER_FONT_HIDDEN("sky_font_ttf")
    ".global sky_font_ttf\n"
    "sky_font_ttf:\n"
    ".incbin \"" SKY_RENDERER_FONT_PATH "\"\n"
    SKY_RENDERER_FONT_HIDDEN("sky_font_ttf_end")
    ".global sky_font_ttf_end\n"
    "sky_font_ttf_end:\n"
    SKY_RENDERER_FONT_END);
extern "C" const unsigned char sky_font_ttf[];
extern "C" const unsigned char sky_font_ttf_end[];


extern "C" int sky_pc_external_menu() __attribute__((weak));
extern "C" int sky_pc_fps_counter() __attribute__((weak));
extern "C" int sky_pc_set_fps_counter(int) __attribute__((weak));
extern "C" void sky_pc_report_frame_time(float) __attribute__((weak));
extern "C" void sky_pc_menu_visibility(int) __attribute__((weak));
extern "C" int sky_pc_menu_gamepad(int) __attribute__((weak));
extern "C" int sky_pc_menu_frame(void*,int,int*,int*,unsigned*) __attribute__((weak));

namespace SkyOverlay {

namespace {

bool FpsCounterEnabled() {return sky_pc_fps_counter?sky_pc_fps_counter()!=0:SkySettings::Get().show_fps.load();}

std::mutex imgui_mutex; // the ImGui context: window thread (input) and present thread
bool initialized = false;
std::atomic<bool> menu_open{false};
bool l3_down = false, r3_down = false;
bool dirty = false; // settings changed while open: saved on close
float base_scale = 1.0f;
// The game's text dialog (ImeDialog, the character name), typed on the keyboard: drawn while it
// is open. In fullscreen the window title that showed it is not visible (issues #17, #19).
std::mutex prompt_mutex;
std::atomic<bool> prompt_active{false};
/// A module's line over the game (skyrender_overlay_banner: BBSC's "joining the host" during its
/// loads, where the game itself shows a black screen).
std::mutex banner_mutex;
std::string banner_text;
std::atomic<bool> banner_active{false};
std::string prompt_title, prompt_text;

// Present rate for the FPS counter.
std::chrono::steady_clock::time_point last_present{};
float frame_ms_avg = 0.0f;

float PixelDensity(SDL_WindowID id);

void SetOpen(bool value) {
    if (menu_open.exchange(value) == value) {
        return;
    }
    if(sky_pc_menu_visibility)sky_pc_menu_visibility(value?1:0);
    // The system cursor shows over the menu (window.cpp); ImGui learns where it is now, not at
    // the next motion: mouse motion is not passed on while the menu is closed.
    if (value) {
        if (SDL_Window* window = SDL_GetMouseFocus()) {
            float x = 0.0f, y = 0.0f;
            SDL_GetMouseState(&x, &y);
            const float density = PixelDensity(SDL_GetWindowID(window));
            ImGui::GetIO().AddMousePosEvent(x * density, y * density);
        }
    }
    if (!value && dirty) {
        dirty = false;
        SkySettings::Save();
    }
}

ImGuiKey KeyFromSdl(SDL_Keycode key) {
    switch (key) {
    case SDLK_TAB: return ImGuiKey_Tab;
    case SDLK_LEFT: return ImGuiKey_LeftArrow;
    case SDLK_RIGHT: return ImGuiKey_RightArrow;
    case SDLK_UP: return ImGuiKey_UpArrow;
    case SDLK_DOWN: return ImGuiKey_DownArrow;
    case SDLK_PAGEUP: return ImGuiKey_PageUp;
    case SDLK_PAGEDOWN: return ImGuiKey_PageDown;
    case SDLK_HOME: return ImGuiKey_Home;
    case SDLK_END: return ImGuiKey_End;
    case SDLK_DELETE: return ImGuiKey_Delete;
    case SDLK_BACKSPACE: return ImGuiKey_Backspace;
    case SDLK_SPACE: return ImGuiKey_Space;
    case SDLK_RETURN: return ImGuiKey_Enter;
    case SDLK_KP_ENTER: return ImGuiKey_KeypadEnter;
    case SDLK_ESCAPE: return ImGuiKey_Escape;
    case SDLK_LCTRL: return ImGuiKey_LeftCtrl;
    case SDLK_RCTRL: return ImGuiKey_RightCtrl;
    case SDLK_LSHIFT: return ImGuiKey_LeftShift;
    case SDLK_RSHIFT: return ImGuiKey_RightShift;
    case SDLK_LALT: return ImGuiKey_LeftAlt;
    case SDLK_RALT: return ImGuiKey_RightAlt;
    default: return ImGuiKey_None;
    }
}

ImGuiKey KeyFromGamepad(u8 button) {
    switch (button) {
    case SDL_GAMEPAD_BUTTON_SOUTH: return ImGuiKey_GamepadFaceDown;
    case SDL_GAMEPAD_BUTTON_EAST: return ImGuiKey_GamepadFaceRight;
    case SDL_GAMEPAD_BUTTON_WEST: return ImGuiKey_GamepadFaceLeft;
    case SDL_GAMEPAD_BUTTON_NORTH: return ImGuiKey_GamepadFaceUp;
    case SDL_GAMEPAD_BUTTON_DPAD_UP: return ImGuiKey_GamepadDpadUp;
    case SDL_GAMEPAD_BUTTON_DPAD_DOWN: return ImGuiKey_GamepadDpadDown;
    case SDL_GAMEPAD_BUTTON_DPAD_LEFT: return ImGuiKey_GamepadDpadLeft;
    case SDL_GAMEPAD_BUTTON_DPAD_RIGHT: return ImGuiKey_GamepadDpadRight;
    case SDL_GAMEPAD_BUTTON_LEFT_SHOULDER: return ImGuiKey_GamepadL1;
    case SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER: return ImGuiKey_GamepadR1;
    case SDL_GAMEPAD_BUTTON_START: return ImGuiKey_GamepadStart;
    case SDL_GAMEPAD_BUTTON_BACK: return ImGuiKey_GamepadBack;
    default: return ImGuiKey_None;
    }
}

float PixelDensity(SDL_WindowID id) {
    SDL_Window* window = SDL_GetWindowFromID(id);
    const float density = window ? SDL_GetWindowPixelDensity(window) : 1.0f;
    return density > 0.0f ? density : 1.0f;
}

// Marks the settings dirty when a widget changed them.
template <typename T>
void Store(std::atomic<T>& target, T value, bool changed) {
    if (changed) {
        target = value;
        dirty = true;
    }
}

void Checkbox(const char* label, std::atomic<bool>& value) {
    bool v = value;
    Store(value, v, ImGui::Checkbox(label, &v));
}

void Slider(const char* label, std::atomic<float>& value, float lo, float hi) {
    float v = value;
    Store(value, v, ImGui::SliderFloat(label, &v, lo, hi, "%.2f"));
}

void Hint(const char* text) {
    ImGui::SameLine();
    ImGui::TextDisabled("(?)");
    if (ImGui::BeginItemTooltip()) {
        ImGui::PushTextWrapPos(ImGui::GetFontSize() * 30.0f);
        ImGui::TextUnformatted(text);
        ImGui::PopTextWrapPos();
        ImGui::EndTooltip();
    }
}

// SPDX-License-Identifier: GPL-2.0-or-later
extern "C" int sky_pc_frame_limit() __attribute__((weak));
extern "C" void sky_pc_set_frame_limit(int) __attribute__((weak));
extern "C" int sky_pc_frame_policy() __attribute__((weak));
extern "C" int sky_pc_auto_available() __attribute__((weak));
extern "C" int sky_pc_set_frame_policy(int) __attribute__((weak));
extern "C" int sky_pc_save_settings(int,int,int,int) __attribute__((weak));
extern "C" int sky_portal_count(int) __attribute__((weak));
extern "C" const char* sky_portal_name(int,int) __attribute__((weak));
extern "C" const char* sky_portal_detail(int,int) __attribute__((weak));
extern "C" int sky_portal_state(int,int) __attribute__((weak));
extern "C" int sky_portal_portrait(int,int) __attribute__((weak));
extern "C" const char* sky_portal_status() __attribute__((weak));
extern "C" const char* sky_portal_atlas() __attribute__((weak));
extern "C" int sky_portal_creation_count() __attribute__((weak));
extern "C" int sky_portal_creation_kind(int) __attribute__((weak));
extern "C" int sky_portal_creation_portrait(int) __attribute__((weak));
extern "C" int sky_portal_element_portrait(int) __attribute__((weak));
extern "C" int sky_portal_trap_element_count() __attribute__((weak));
extern "C" const char* sky_portal_trap_element_name(int) __attribute__((weak));
extern "C" int sky_portal_trap_element(int) __attribute__((weak));
extern "C" int sky_portal_trap_capture(int) __attribute__((weak));

extern "C" int sky_controller_family(int) __attribute__((weak));
extern "C" int sky_pc_controller_layout() __attribute__((weak));
extern "C" int sky_pc_controller_glyphs() __attribute__((weak));
extern "C" int sky_pc_set_controller_glyphs(int) __attribute__((weak));
extern "C" int sky_pc_set_controller_layout(int) __attribute__((weak));
extern "C" const char* sky_portal_creation_name(int) __attribute__((weak));
extern "C" int sky_portal_action(int,int) __attribute__((weak));
extern "C" int sky_portal_volume() __attribute__((weak));
extern "C" void sky_portal_set_volume(int) __attribute__((weak));

// Images supplied by the user's installed Steam client, imported privately.
ImTextureData* ControllerGlyphAtlas() {
    static ImTextureData* texture=nullptr;static bool attempted=false;
    if(attempted)return texture;attempted=true;
    const auto* path=std::getenv("SKY_CONTROLLER_GLYPH_ATLAS");if(!path)return nullptr;
    FILE* file=std::fopen(path,"rb");if(!file)return nullptr;
    unsigned size[2]{};
    if(std::fread(size,sizeof(size),1,file)!=1||size[0]!=512||size[1]!=256){std::fclose(file);return nullptr;}
    auto* image=IM_NEW(ImTextureData)();image->Create(ImTextureFormat_RGBA32,512,256);
    if(std::fread(image->Pixels,1,image->GetSizeInBytes(),file)!=static_cast<size_t>(image->GetSizeInBytes())){
        std::fclose(file);IM_DELETE(image);return nullptr;
    }
    std::fclose(file);image->UseColors=true;image->UniqueID=10002;
    ImGui::RegisterUserTexture(image);texture=image;return texture;
}
void PcFaceHint(int family,int button,const char* action) {
    auto* atlas=ControllerGlyphAtlas();
    if(atlas) {
        const int positions[]{0,2,1,3};
        const int cell=family==1?20+button:(family==3?10:0)+positions[button];
        const ImVec2 uv0{float(cell%8)/8.0f,float(cell/8)/4.0f};
        const ImVec2 uv1{uv0.x+1.0f/8.0f,uv0.y+1.0f/4.0f};
        ImGui::Image(atlas->GetTexRef(),{27,27},uv0,uv1);
    } else {
        const char* ps[]{"Cross","Circle","Square","Triangle"};
        const char* xbox[]{"A","B","X","Y"};const char* nintendo[]{"B","A","Y","X"};
        ImGui::TextUnformatted(family==1?ps[button]:family==3?nintendo[button]:xbox[button]);
    }
    ImGui::SameLine();ImGui::TextUnformatted(action);
}

int PcChoice(const char* key,int fallback) {const auto* p=std::getenv(key);return p?std::atoi(p):fallback;}
ImVec4 PortalColor(const char* element) {
    const std::string_view e=element?element:"";
    if(e=="Water")return {0.22f,0.64f,1,1}; if(e=="Life")return {0.4f,0.85f,0.34f,1};
    if(e=="Fire")return {1,0.4f,0.2f,1}; if(e=="Magic")return {0.75f,0.4f,1,1};
    if(e=="Earth")return {0.85f,0.62f,0.3f,1}; if(e=="Tech")return {1,0.77f,0.25f,1};
    if(e=="Undead")return {0.77f,0.78f,0.95f,1}; if(e=="Air")return {0.54f,0.86f,0.95f,1};
    if(e=="Light")return {1,0.96f,0.7f,1};return {0.76f,0.5f,0.74f,1};
}
int portal_columns=8,portal_rows=6;
ImTextureData* PortalAtlas() {
    static ImTextureData* texture=nullptr;static bool attempted=false;
    if(attempted)return texture;attempted=true;if(!sky_portal_atlas)return nullptr;
    FILE* file=std::fopen(sky_portal_atlas(),"rb");if(!file)return nullptr;unsigned size[2]{};
    if(std::fread(size,sizeof(size),1,file)!=1||!size[0]||!size[1]||size[0]>4096||size[1]>6144||
       (size[0]==1024?size[1]!=768:(size[0]%96||size[1]%96))){std::fclose(file);return nullptr;}
    const unsigned cell=size[0]==1024?128:96;portal_columns=static_cast<int>(size[0]/cell);portal_rows=static_cast<int>(size[1]/cell);
    auto* image=IM_NEW(ImTextureData)();image->Create(ImTextureFormat_RGBA32,static_cast<int>(size[0]),static_cast<int>(size[1]));
    if(std::fread(image->Pixels,1,image->GetSizeInBytes(),file)!=static_cast<size_t>(image->GetSizeInBytes())){std::fclose(file);IM_DELETE(image);return nullptr;}
    std::fclose(file);image->UseColors=true;image->UniqueID=10001;ImGui::RegisterUserTexture(image);texture=image;return texture;
}
bool PortalMatches(const char* name,const char* search) {
    std::string a=name?name:"",b=search?search:"";
    std::transform(a.begin(),a.end(),a.begin(),[](unsigned char c){return char(std::tolower(c));});
    std::transform(b.begin(),b.end(),b.begin(),[](unsigned char c){return char(std::tolower(c));});return a.find(b)!=std::string::npos;
}
void PortalImage(int cell,ImVec2 position,ImVec2 size) {
    auto* atlas=PortalAtlas();if(!atlas||cell<0||cell>=portal_columns*portal_rows)return;
    const ImVec2 uv0{float(cell%portal_columns)/float(portal_columns),float(cell/portal_columns)/float(portal_rows)};
    const ImVec2 uv1{uv0.x+1.0f/float(portal_columns),uv0.y+1.0f/float(portal_rows)};
    ImGui::GetWindowDrawList()->AddImage(atlas->GetTexRef(),position,{position.x+size.x,position.y+size.y},uv0,uv1);
}
// Portal base + swirling aperture, rather than a diamond/figure symbol.
void PcToolIcon(int icon,ImVec2 p,float side,ImU32 color) {
    auto* draw=ImGui::GetWindowDrawList();const float u=side/28.0f;const float line=1.8f*u;
    const auto point=[&](float x,float y){return ImVec2(p.x+x*u,p.y+y*u);};
    if(icon==0){draw->AddEllipse(point(14,10),{11*u,5*u},color,0,24,line);draw->AddEllipse(point(14,17),{11*u,5*u},color,0,24,line);draw->AddLine(point(3,10),point(3,17),color,line);draw->AddLine(point(25,10),point(25,17),color,line);draw->AddCircle(point(14,10),2.5f*u,color,18,line);}
    else if(icon==1){draw->AddRect(point(3,3),point(25,20),color,2*u,line);draw->AddLine(point(14,20),point(14,25),color,line);draw->AddLine(point(9,25),point(19,25),color,line);}
    else if(icon==2){draw->AddLine(point(3,24),point(3,4),color,line);draw->AddLine(point(3,24),point(25,24),color,line);draw->AddLine(point(5,19),point(11,12),color,line);draw->AddLine(point(11,12),point(17,16),color,line);draw->AddLine(point(17,16),point(25,5),color,line);}
    else if(icon==3){draw->AddRect(point(2,7),point(26,22),color,6*u,line);draw->AddLine(point(7,14),point(13,14),color,line);draw->AddLine(point(10,11),point(10,17),color,line);draw->AddCircleFilled(point(20,12),1.5f*u,color);draw->AddCircleFilled(point(22,17),1.5f*u,color);}
    else if(icon==4){draw->AddRect(point(3,10),point(9,19),color,1*u,line);draw->AddLine(point(9,10),point(15,5),color,line);draw->AddLine(point(15,5),point(15,24),color,line);draw->AddLine(point(15,24),point(9,19),color,line);draw->AddBezierCubic(point(20,7),point(28,10),point(28,20),point(20,23),color,line);}
    else{draw->AddCircle(point(14,14),11*u,color,24,line);draw->AddLine(point(14,12),point(14,21),color,line);draw->AddCircleFilled(point(14,7),1.4f*u,color);}
}
int portal_slot=0;bool portal_coop=false;
int PortalSelected(int kind){for(int i=0;i<sky_portal_count(kind);++i)if(sky_portal_state(kind,i)&2)return i;return -1;}
bool PortalCard(const char* id,const char* name,int cell,float width,float height,bool selected,const char* detail=nullptr,int emblem=-1) {
    const float scale=base_scale;const auto position=ImGui::GetCursorScreenPos();
    ImGui::PushStyleColor(ImGuiCol_Button,selected?ImVec4(0.18f,0.22f,0.24f,1):ImVec4(0.15f,0.15f,0.17f,1));
    ImGui::PushStyleColor(ImGuiCol_Border,selected?ImVec4(1,1,1,1):ImVec4(0.23f,0.23f,0.25f,1));
    ImGui::PushStyleVar(ImGuiStyleVar_FrameBorderSize,selected?2*scale:1*scale);
    const bool pressed=ImGui::Button(id,{width,height});ImGui::PopStyleVar();ImGui::PopStyleColor(2);
    const float side=std::min(width-12*scale,height-(detail?55:34)*scale);
    const ImVec2 image{position.x+(width-side)*0.5f,position.y+6*scale};
    if(cell>=0)PortalImage(cell,image,{side,side});else PcToolIcon(0,{image.x+side*0.28f,image.y+side*0.28f},side*0.44f,IM_COL32(185,190,198,255));
    auto* draw=ImGui::GetWindowDrawList();const ImVec4 clip{position.x+5*scale,position.y,position.x+width-5*scale,position.y+height};
    draw->AddText(ImGui::GetFont(),13*scale,{position.x+8*scale,image.y+side+5*scale},IM_COL32(250,250,250,255),name,nullptr,width-16*scale,&clip);
    if(detail){float x=position.x+8*scale;if(emblem>=0){PortalImage(emblem,{x,position.y+height-22*scale},{17*scale,17*scale});x+=21*scale;}
        draw->AddText(ImGui::GetFont(),11*scale,{x,position.y+height-21*scale},IM_COL32(191,191,201,255),detail,nullptr,width-16*scale,&clip);}
    return pressed;
}
void PortalCollection(int kind) {
    const float scale=base_scale;static char search[3][96]{};const int collection=kind==0&&portal_slot==3?3:kind;
    if(kind==1){
        ImGui::TextUnformatted("Place an empty trap");ImGui::Spacing();
        const int count=sky_portal_trap_element_count?sky_portal_trap_element_count():0;const int columns=6;const float gap=6*scale;const float available=ImGui::GetContentRegionAvail().x;const float width=(available-gap*5)/6;
        for(int row=0;row*columns<count;++row){const int n=std::min(columns,count-row*columns);const float start=ImGui::GetCursorPosX()+(available-(width*n+gap*(n-1)))*0.5f;
            for(int col=0;col<n;++col){const int element=row*columns+col;if(col)ImGui::SameLine(0,gap);else ImGui::SetCursorPosX(start);ImGui::PushID(element);
                const auto pos=ImGui::GetCursorScreenPos();const int current=PortalSelected(1);const bool selected=current>=0&&sky_portal_trap_capture(current)==0&&sky_portal_trap_element(current)==element;
                ImGui::PushStyleColor(ImGuiCol_Button,selected?ImVec4(1,1,1,1):ImVec4(0.16f,0.16f,0.18f,1));
                if(ImGui::Button("##element",{width,84*scale})&&sky_portal_action)sky_portal_action(12,element);ImGui::PopStyleColor();
                PortalImage(sky_portal_element_portrait?sky_portal_element_portrait(element):-1,{pos.x+(width-36*scale)/2,pos.y+10*scale},{36*scale,36*scale});
                const char* name=sky_portal_trap_element_name(element);const float text_width=ImGui::CalcTextSize(name).x*12*scale/ImGui::GetFontSize();
                ImGui::GetWindowDrawList()->AddText(ImGui::GetFont(),12*scale,{pos.x+(width-text_width)/2,pos.y+58*scale},selected?IM_COL32(17,17,17,255):IM_COL32(245,245,245,255),name);ImGui::PopID();
            }
        }
        ImGui::Spacing();ImGui::TextUnformatted("Captured villains");ImGui::Spacing();
    }else{
        ImGui::SetNextItemWidth(-1);ImGui::InputTextWithHint("##collection_search",kind==2?"Search items...":"Search Skylanders...",search[kind],sizeof(search[kind]));
        const float half=(ImGui::GetContentRegionAvail().x-ImGui::GetStyle().ItemSpacing.x)/2;
        if(ImGui::Button(kind==2?"Create item":"Create figure",{half,44*scale}))ImGui::OpenPopup("create_figure");ImGui::SameLine();
        if(ImGui::Button("Import file",{half,44*scale})&&sky_portal_action)sky_portal_action(collection==3?11:2,0);
        ImGui::SetNextWindowSize({std::min(520*scale,ImGui::GetMainViewport()->WorkSize.x-30*scale),std::min(620*scale,ImGui::GetMainViewport()->WorkSize.y-40*scale)},ImGuiCond_Always);
        if(ImGui::BeginPopup("create_figure")){
            static char filter[96]{};ImGui::TextUnformatted(kind==2?"Create an item":"Create a Skylander");ImGui::TextWrapped("New figures start fresh. Your saved figures are kept.");ImGui::SetNextItemWidth(-1);ImGui::InputTextWithHint("##create_filter","Search characters and editions...",filter,sizeof(filter));
            ImGui::BeginChild("creator_grid",{0,-52*scale});
            if(sky_portal_creation_count&&ImGui::BeginTable("create_cards",3,ImGuiTableFlags_SizingStretchSame)){
                for(int i=0;i<sky_portal_creation_count();++i){if(sky_portal_creation_kind(i)!=kind)continue;const std::string name=sky_portal_creation_name(i);if(!PortalMatches(name.c_str(),filter))continue;ImGui::TableNextColumn();ImGui::PushID(i);const float width=ImGui::GetContentRegionAvail().x;
                    if(PortalCard("##create",name.c_str(),sky_portal_creation_portrait?sky_portal_creation_portrait(i):-1,width,width+40*scale,false)&&sky_portal_action){sky_portal_action(collection==3?10:5,i);ImGui::CloseCurrentPopup();}ImGui::PopID();}
                ImGui::EndTable();}
            ImGui::EndChild();if(ImGui::Button("Cancel",{-1,44*scale}))ImGui::CloseCurrentPopup();ImGui::EndPopup();}
    }
    int shown=0;std::vector<int> entries;
    if(kind==1){for(int element=0;element<sky_portal_trap_element_count();++element)for(int i=0;i<sky_portal_count(1);++i)if(sky_portal_trap_element(i)==element)entries.push_back(i);}
    else for(int i=0;i<sky_portal_count(kind);++i)entries.push_back(i);
    if(ImGui::BeginTable("saved_cards",3,ImGuiTableFlags_SizingStretchSame)){
        for(int i:entries){const auto state=sky_portal_state(collection,i);if(kind==1&&(!(state&1)||sky_portal_trap_capture(i)==0))continue;const std::string name=sky_portal_name(kind,i);if(kind!=1&&!PortalMatches(name.c_str(),search[kind]))continue;
            ++shown;ImGui::TableNextColumn();ImGui::PushID(i);const float width=ImGui::GetContentRegionAvail().x;const auto* detail=kind==1?sky_portal_detail(kind,i):nullptr;const int emblem=kind==1&&sky_portal_element_portrait?sky_portal_element_portrait(sky_portal_trap_element(i)):-1;
            if(PortalCard("##saved",name.c_str(),sky_portal_portrait(kind,i),width,width+(kind==1?55:38)*scale,(state&2)!=0,detail,emblem)&&sky_portal_action)sky_portal_action(kind==2?8:collection==3?6:kind,i);
            ImGui::PopID();}
        ImGui::EndTable();}
    if(!shown)ImGui::TextWrapped(kind==1?"Captured villains appear here after an in-game capture.":"Create or import a figure to add it to your collection.");
}
void PortalPanel() {
    const float scale=base_scale;static bool initialized=false;
    if(!initialized){portal_coop=PortalSelected(3)>=0;initialized=true;}
    const int kinds[]{0,3,1,2};const int columns=portal_coop?2:3;
    if(ImGui::BeginTable("portal_slots",columns,ImGuiTableFlags_SizingStretchSame)){
        for(int kind:kinds){if(kind==3&&!portal_coop)continue;ImGui::TableNextColumn();ImGui::PushID(kind);const int active=PortalSelected(kind);const auto* title=kind==0?"Player 1":kind==3?"Player 2":kind==1?"Trap":"Item";
            const std::string name=active>=0?sky_portal_name(kind,active):"Empty";int portrait=active>=0?sky_portal_portrait(kind,active):-1;
            if(kind==1&&active>=0&&portrait<0&&sky_portal_element_portrait)portrait=sky_portal_element_portrait(sky_portal_trap_element(active));
            if(PortalCard("##slot",title,portrait,ImGui::GetContentRegionAvail().x,151*scale,portal_slot==kind,name.c_str()))portal_slot=kind;ImGui::PopID();}
        ImGui::EndTable();}
    const float half=(ImGui::GetContentRegionAvail().x-ImGui::GetStyle().ItemSpacing.x)/2;
    if(ImGui::Button(portal_coop?"Remove Player 2":"Add Player 2",{half,44*scale})){
        portal_coop=!portal_coop;if(!portal_coop){if(sky_portal_action)sky_portal_action(7,0);if(portal_slot==3)portal_slot=0;}else portal_slot=3;}
    ImGui::SameLine();if(ImGui::Button(portal_slot==1?"Eject trap":portal_slot==2?"Remove item":"Remove figure",{half,44*scale})&&sky_portal_action)sky_portal_action(portal_slot==1?4:portal_slot==2?9:portal_slot==3?7:3,0);
    ImGui::Spacing();PortalCollection(portal_slot==3?0:portal_slot);ImGui::Spacing();if(sky_portal_status)ImGui::TextWrapped("%s",sky_portal_status());
}

void PcMenu() {
    static int resolution=std::clamp(PcChoice("SKY_PC_RESOLUTION",2),0,5);
    static int quality=std::clamp(PcChoice("SKY_PC_QUALITY",1),0,2),page=-1;
    static bool fullscreen=PcChoice("SKY_FULLSCREEN",0)!=0,failed=false,portal_open=true;
    bool counter=FpsCounterEnabled();
    static float expansion=0;
    const auto* v=ImGui::GetMainViewport();const float scale=base_scale;
    const float margin=16*scale,rail_height=442*scale;
    const ImVec2 rail_pos{v->WorkPos.x+margin,v->WorkPos.y+margin};
    const bool hover=ImGui::IsMouseHoveringRect(rail_pos,{rail_pos.x+(68+122*expansion)*scale,rail_pos.y+rail_height},false);
    expansion+=(float(hover)-expansion)*std::min(1.0f,ImGui::GetIO().DeltaTime*14);
    const float rail_width=(68+122*expansion)*scale;
    const auto flags=ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoResize|ImGuiWindowFlags_NoMove|ImGuiWindowFlags_NoCollapse|ImGuiWindowFlags_NoSavedSettings;
    ImGui::PushStyleColor(ImGuiCol_WindowBg,{0.075f,0.075f,0.08f,1});
    ImGui::PushStyleColor(ImGuiCol_ChildBg,{0,0,0,0});ImGui::PushStyleColor(ImGuiCol_Header,{0.22f,0.22f,0.24f,1});
    ImGui::PushStyleColor(ImGuiCol_Button,{0.17f,0.17f,0.19f,1});ImGui::PushStyleColor(ImGuiCol_ButtonHovered,{0.28f,0.28f,0.30f,1});
    ImGui::PushStyleColor(ImGuiCol_FrameBg,{0.16f,0.16f,0.18f,1});
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,{18*scale,18*scale});ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding,12*scale);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding,22*scale);ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing,{8*scale,10*scale});
    ImGui::SetNextWindowPos(rail_pos);ImGui::SetNextWindowSize({rail_width,std::min(rail_height,v->WorkSize.y-2*margin)});
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,{8*scale,14*scale});ImGui::PushStyleColor(ImGuiCol_WindowBg,{0.055f,0.055f,0.055f,1});
    if(ImGui::Begin("##pc_tool_rail",nullptr,flags|ImGuiWindowFlags_NoScrollbar)){
        const char* labels[]{"Virtual portal","Display","Performance","Controls","Audio","About"};
        for(int icon=0;icon<6;++icon){ImGui::PushID(icon);const auto pos=ImGui::GetCursorScreenPos();const bool selected=icon==0?portal_open:page==icon-1;
            ImGui::PushStyleColor(ImGuiCol_Button,selected?ImVec4(1,1,1,1):ImVec4(0,0,0,0));
            if(ImGui::Button("##tool",{-1,48*scale})){if(icon==0)portal_open=!portal_open;else page=page==icon-1?-1:icon-1;}ImGui::PopStyleColor();
            PcToolIcon(icon,{pos.x+12*scale,pos.y+11*scale},26*scale,selected?IM_COL32(20,20,20,255):IM_COL32(245,245,245,255));
            if(expansion>0.65f)ImGui::GetWindowDrawList()->AddText({pos.x+51*scale,pos.y+15*scale},selected?IM_COL32(20,20,20,255):IM_COL32(245,245,245,255),labels[icon]);
            if(ImGui::IsItemHovered())ImGui::SetTooltip("%s",labels[icon]);ImGui::PopID();if(icon==0){ImGui::Spacing();ImGui::Separator();ImGui::Spacing();}
        }
        if(ImGui::Button(expansion>0.65f?"Close":"X",{-1,40*scale}))SetOpen(false);
    }ImGui::End();ImGui::PopStyleColor();ImGui::PopStyleVar();
    const float panel_x=rail_pos.x+rail_width+12*scale;
    if(page>=0){
        const float width=std::min(350*scale,v->WorkSize.x-(panel_x-v->WorkPos.x)-margin);
        ImGui::SetNextWindowPos({panel_x,rail_pos.y});ImGui::SetNextWindowSize({width,std::min(690*scale,v->WorkSize.y-2*margin)});
        if(ImGui::Begin("##pc_settings_popout",nullptr,flags)){
            const char* titles[]{"Display","Performance","Controls","Audio","About"};
            const auto icon_pos=ImGui::GetCursorScreenPos();PcToolIcon(page+1,icon_pos,23*scale,IM_COL32(255,255,255,255));ImGui::Dummy({26*scale,25*scale});ImGui::SameLine();ImGui::TextUnformatted(titles[page]);
            ImGui::SameLine(ImGui::GetWindowWidth()-52*scale);if(ImGui::SmallButton("X##settings"))page=-1;
            ImGui::Spacing();ImGui::BeginChild("settings_body",{0,-126*scale});
        if(page==0) {
            ImGui::TextUnformatted("DISPLAY");ImGui::TextDisabled("Changes apply after restart");ImGui::Spacing();
            ImGui::TextUnformatted("Render resolution");ImGui::SetNextItemWidth(-1);
            ImGui::Combo("##resolution",&resolution,"1280 x 720\0" "1600 x 900\0" "1920 x 1080\0" "2560 x 1440\0" "2560 x 1600\0" "3840 x 2160\0");
            ImGui::TextUnformatted("Graphics quality");ImGui::SetNextItemWidth(-1);
            ImGui::Combo("##quality",&quality,"Performance\0Balanced\0High\0");
            ImGui::TextWrapped("%s",quality==0?"Lighter shadows for more GPU headroom.":quality==1?"Original shadow detail.":"Sharper shadows with a higher GPU cost.");
            ImGui::Checkbox("Fullscreen",&fullscreen);
        } else if(page==1) {
            ImGui::TextUnformatted("PERFORMANCE");ImGui::TextDisabled("Applies immediately");ImGui::Spacing();
            if(sky_pc_frame_limit&&sky_pc_set_frame_limit) {
                const bool automatic=sky_pc_frame_policy && sky_pc_frame_policy()!=0;
                if(sky_pc_set_frame_policy && sky_pc_auto_available) {
                    ImGui::BeginDisabled(!sky_pc_auto_available());
                    if(ImGui::RadioButton("Automatic (30 / 60 FPS)",automatic))sky_pc_set_frame_policy(1);
                    ImGui::EndDisabled();
                    if(!sky_pc_auto_available())ImGui::TextWrapped("Automatic requires the verified game-state mod. Enable it in the launcher.");
                }
                const int cap=sky_pc_frame_limit();
                if(ImGui::RadioButton("30 FPS",!automatic && cap==30))sky_pc_set_frame_limit(30);
                ImGui::SameLine();ImGui::BeginDisabled(!PcChoice("SKY_ALLOW_60",0));
                if(ImGui::RadioButton("60 FPS",!automatic && cap==60))sky_pc_set_frame_limit(60);ImGui::EndDisabled();
            }
            if(ImGui::Checkbox("Show FPS counter",&counter)){
                if(sky_pc_set_fps_counter)sky_pc_set_fps_counter(counter?1:0);
                SkySettings::Get().show_fps=counter;
            }
            ImGui::TextWrapped("Automatic keeps videos at 30 and supported in-engine cinematics at 60. Loading, menus and portal arrival retain protective gates. Manual buttons or Shift+F1 take control; select Automatic to resume scene switching.");
            ImGui::TextWrapped("MangoHud is an optional external overlay.");
        } else if(page==2) {
            ImGui::TextUnformatted("CONTROLS");ImGui::Spacing();
            if(sky_pc_controller_layout && sky_pc_set_controller_layout) {
                int layout=sky_pc_controller_layout();
                if(ImGui::Combo("Controller setup",&layout,"Controller(s)\0Keyboard + controller\0"))sky_pc_set_controller_layout(layout);
                ImGui::TextWrapped("Apply settings and restart to change player assignments.");
                ImGui::Spacing();
            }
            if(sky_pc_controller_glyphs && sky_pc_set_controller_glyphs) {
                int style=sky_pc_controller_glyphs();
                if(ImGui::Combo("Button glyphs",&style,"Automatic\0PlayStation\0Xbox\0Nintendo\0"))sky_pc_set_controller_glyphs(style);
                const auto* active=std::getenv("SKY_ACTIVE_CONTROLLER_GLYPHS");
                ImGui::Text("Game glyph pack: %s",active?active:"playstation");
                ImGui::TextWrapped("Apply settings and restart to change the shared in-game font. Automatic uses the first mapped controller at launch. Mixed controllers share that font.");
                ImGui::Spacing();
            }
            if(sky_controller_family)for(int player=0;player<2;++player) {
                const int family=sky_controller_family(player);
                const char* type=family==1?"PlayStation":family==2?"Xbox":family==3?"Nintendo":family==4?"Gamepad":player==0?"Keyboard":"Not connected";
                ImGui::Text("Player %d: %s",player+1,type);
                const char* buttons=family==1?"Confirm: Cross   Back: Circle\nAttack: Square   Secondary: Triangle":family==2?"Confirm: A   Back: B\nAttack: X   Secondary: Y":family==3?"Confirm: B   Back: A\nAttack: Y   Secondary: X":family==4?"Confirm: South   Back: East\nAttack: West   Secondary: North":player==0?"Confirm: Enter   Back: Escape\nAttack: Z   Secondary: X":"Connect a second controller to join.";
                if(family>=1 && family<=3) {
                    PcFaceHint(family,0,"Confirm / Jump");PcFaceHint(family,1,"Back / Attack 3");
                    PcFaceHint(family,2,"Attack 1");PcFaceHint(family,3,"Attack 2");
                } else ImGui::TextWrapped("%s",buttons);
                ImGui::Spacing();
            }
            ImGui::TextWrapped("F6 / Insert     Open or close these panels\nL3 + R3     Controller shortcut\nShift + F1     30 / 60 FPS\nF2     Import Skylander\nF3     Remove Skylander\nF5     Eject trap");
            ImGui::Spacing();ImGui::TextWrapped("The mouse is free to leave the window. Game controls are blocked while these panels are open. The world keeps running.");
        } else if(page==3) {
            ImGui::TextUnformatted("PORTAL SPEAKER");ImGui::Spacing();
            if(sky_portal_volume&&sky_portal_set_volume) {
                int volume=sky_portal_volume();ImGui::SetNextItemWidth(-1);
                if(ImGui::SliderInt("##portal_volume",&volume,0,100,"%d%%"))sky_portal_set_volume(volume);
            }
            ImGui::TextWrapped("Portal voices play quietly through your PC speakers. Default: 30%%. Set to zero to mute only the portal.");
        } else {
            ImGui::TextUnformatted("YOUR PC PORTAL");ImGui::Spacing();
            ImGui::TextWrapped("Choose an element to place an empty trap. Captured villains appear from the saved trap data; selecting a portrait keeps that trap's progress.");
            ImGui::Spacing();ImGui::TextDisabled("Portraits: Activision / darkSpyro");
            ImGui::TextWrapped("Portraits are cached locally. The game needs no network connection.");
        }

            ImGui::EndChild();ImGui::Separator();
        ImGui::TextWrapped("Save game progress before restarting.");
        ImGui::BeginDisabled(!std::getenv("SKY_PC_SETTINGS_REQUEST"));
        if(ImGui::Button("Apply settings and restart",{-1,34*scale})) {
            failed=!sky_pc_save_settings||!sky_pc_save_settings(resolution,quality,fullscreen,counter);
            if(!failed){SDL_Event event{};event.type=SDL_EVENT_QUIT;SDL_PushEvent(&event);}
        }
        ImGui::EndDisabled();if(failed)ImGui::TextWrapped("Could not save settings. Try again.");

        }ImGui::End();
    }
    if(portal_open&&(page<0||v->WorkSize.x>=1000*scale)){
        const float right=std::min(450*scale,v->WorkSize.x-rail_width-3*margin);
        ImGui::SetNextWindowPos({v->WorkPos.x+v->WorkSize.x-right-margin,v->WorkPos.y+margin});ImGui::SetNextWindowSize({right,v->WorkSize.y-2*margin});
        if(ImGui::Begin("##pc_right_portal",nullptr,flags)){
            ImGui::TextUnformatted("Virtual portal");ImGui::SameLine(ImGui::GetWindowWidth()-52*scale);if(ImGui::SmallButton("X##portal"))portal_open=false;ImGui::Spacing();
            if(sky_portal_count&&sky_portal_state&&sky_portal_name&&sky_portal_trap_capture&&sky_portal_trap_element_count)PortalPanel();
            else ImGui::TextWrapped("Virtual portal is unavailable in this build.");
        }ImGui::End();
    }
    ImGui::PopStyleVar(4);ImGui::PopStyleColor(6);
}

// Composite the same HTML/CSS menu into the swapchain. The helper paints offscreen
// and never takes desktop focus; input continues through the game's SDL window.
void HtmlMenu() {
    static std::vector<unsigned char> pixels(3840*2160*4);
    static ImTextureData* texture=nullptr;
    static unsigned generation=0;
    static int width=0,height=0;
    if(sky_pc_menu_frame(pixels.data(),static_cast<int>(pixels.size()),&width,&height,&generation)) {
        if(!texture){
            texture=IM_NEW(ImTextureData)();texture->Create(ImTextureFormat_RGBA32,3840,2160);
            std::memset(texture->Pixels,0,texture->GetSizeInBytes());
            texture->UseColors=true;texture->UniqueID=10002;ImGui::RegisterUserTexture(texture);
        }
        for(int row=0;row<height;++row)std::memcpy(texture->GetPixelsAt(0,row),pixels.data()+row*width*4,width*4);
        if(texture->Status!=ImTextureStatus_WantCreate){
            texture->UpdateRect={0,0,static_cast<unsigned short>(width),static_cast<unsigned short>(height)};
            texture->Updates.clear();texture->Updates.push_back(texture->UpdateRect);
            texture->SetStatus(ImTextureStatus_WantUpdates);
        }
    }
    if(texture){
        const auto* viewport=ImGui::GetMainViewport();
        ImGui::GetBackgroundDrawList()->AddImage(texture->GetTexRef(),viewport->Pos,
            {viewport->Pos.x+viewport->Size.x,viewport->Pos.y+viewport->Size.y},
            {0,0},{float(width)/3840,float(height)/2160});
    }
}

// Keep the host menu as a fallback when the HTML helper is unavailable.
void Menu() {
    if (sky_pc_external_menu && sky_pc_external_menu()) {
        const auto* embedded=std::getenv("SKY_PC_MENU_EMBEDDED");
        if(embedded&&embedded[0]=='1'&&sky_pc_menu_frame)HtmlMenu();
        return;
    }
    PcMenu();
}

void FpsCounter() {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const float pad = 12.0f * base_scale;
    ImGui::SetNextWindowPos(
        ImVec2(viewport->WorkPos.x + viewport->WorkSize.x - pad, viewport->WorkPos.y + pad),
        ImGuiCond_Always, ImVec2(1.0f, 0.0f));
    ImGui::SetNextWindowBgAlpha(0.5f);
    ImGui::Begin("##fps", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoSavedSettings);
    ImGui::Text(SkySettings::MenuText("%.0f FPS  %.1f ms", "%.0f FPS  %.1f мс"),
                frame_ms_avg > 0.0f ? 1000.0f / frame_ms_avg : 0.0f, frame_ms_avg);
    ImGui::End();
}


// Trophy unlock popups (skyrender_show_toast), queued and shown one at a time.
struct Toast{std::string title,text;int grade;};
std::mutex toast_mutex;std::vector<Toast> toasts;
std::chrono::steady_clock::time_point toast_start;bool toast_showing=false;

void TrophyToast() {
    Toast toast;float t;
    {
        std::scoped_lock lock{toast_mutex};
        if(toasts.empty())return;
        const auto now=std::chrono::steady_clock::now();
        if(!toast_showing){toast_start=now;toast_showing=true;}
        t=std::chrono::duration<float>(now-toast_start).count();
        if(t>5.5f){toasts.erase(toasts.begin());toast_showing=false;return;}
        toast=toasts.front();
    }
    const float in=std::min(1.0f,t/0.35f),out=std::clamp((5.5f-t)/0.5f,0.0f,1.0f);
    const float ease=1.0f-(1.0f-in)*(1.0f-in)*(1.0f-in);
    const float s=base_scale,w=360.0f*s,h=84.0f*s,pad=16.0f*s;
    const ImGuiViewport* viewport=ImGui::GetMainViewport();
    const float top=viewport->WorkPos.y+viewport->WorkSize.y-h-pad-52.0f*s;
    const float x=viewport->WorkPos.x+viewport->WorkSize.x-pad-w*ease;
    const ImU32 accents[]{IM_COL32(160,160,160,255),IM_COL32(120,200,255,255),IM_COL32(240,196,60,255),
                          IM_COL32(200,206,214,255),IM_COL32(205,127,50,255)};
    const ImU32 accent=accents[(toast.grade>=0&&toast.grade<=4)?toast.grade:0];
    const auto alpha=[&](ImU32 c,float a){return (c&0x00FFFFFFu)|(static_cast<ImU32>(((c>>24)&0xFF)*a*out)<<24);};
    ImDrawList* draw=ImGui::GetForegroundDrawList();
    const ImVec2 a{x,top},b{x+w,top+h};
    draw->AddRectFilled(a,b,alpha(IM_COL32(22,26,34,255),0.94f),8.0f*s);
    draw->AddRectFilled(a,ImVec2(x+5.0f*s,top+h),alpha(accent,1),8.0f*s,ImDrawFlags_RoundCornersLeft);
    const ImVec2 c{x+48.0f*s,top+h*0.5f};
    draw->AddCircleFilled(c,26.0f*s,alpha(IM_COL32(40,46,58,255),1));
    draw->AddCircle(c,26.0f*s,alpha(accent,1),0,3.0f*s);
    // A small cup: bowl, stem and base.
    draw->AddRectFilled(ImVec2(c.x-10*s,c.y-13*s),ImVec2(c.x+10*s,c.y+1*s),alpha(accent,1),0,0);
    draw->AddCircleFilled(ImVec2(c.x,c.y+1*s),10*s,alpha(accent,1));
    draw->AddRectFilled(ImVec2(c.x-2.5f*s,c.y+8*s),ImVec2(c.x+2.5f*s,c.y+14*s),alpha(accent,1));
    draw->AddRectFilled(ImVec2(c.x-9*s,c.y+14*s),ImVec2(c.x+9*s,c.y+18*s),alpha(accent,1),2*s);
    ImFont* font=ImGui::GetFont();const float size=ImGui::GetFontSize();
    const float tx=x+88.0f*s,clip=x+w-12.0f*s;
    draw->AddText(font,size*0.85f,ImVec2(tx,top+16*s),alpha(accent,1),toast.title.c_str());
    const ImVec4 rect{tx,top,clip,top+h};
    draw->AddText(font,size*1.05f,ImVec2(tx,top+38*s),alpha(IM_COL32(240,242,246,255),1),
                  toast.text.c_str(),nullptr,clip-tx,&rect);
}
} // namespace

extern "C" void skyrender_show_toast(const char* title,const char* text,int grade) {
    std::scoped_lock lock{toast_mutex};
    if(toasts.size()<16)toasts.push_back({title?title:"",text?text:"",grade});
}

namespace {
void TextPrompt() {
    std::string title, text;
    {
        std::scoped_lock lock{prompt_mutex};
        title = prompt_title;
        text = prompt_text;
    }
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + viewport->WorkSize.y * 0.5f),
                            ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowBgAlpha(0.9f);
    ImGui::Begin("##textprompt", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::TextUnformatted(title.c_str());
    ImGui::Separator();
    ImGui::Text("%s_", text.c_str());
    ImGui::Separator();
    ImGui::TextUnformatted("Keyboard: type, Backspace = delete, Enter = OK, Esc = cancel");
    ImGui::End();
}

/// SKY_RENDERER_MENU_KEYS_FILE=<file> (scripted tests): tokens toggle up down left right enter back l1 r1,
/// consumed when the file appears (it is removed), one key press per frame.
void ScriptedKeys() {
    static const char* path = std::getenv("SKY_RENDERER_MENU_KEYS_FILE");
    static std::chrono::steady_clock::time_point last_check{};
    static std::vector<std::string> queue;
    static bool release = false;
    static ImGuiKey held = ImGuiKey_None;
    if (!path) {
        return;
    }
    ImGuiIO& io = ImGui::GetIO();
    if (release) {
        io.AddKeyEvent(held, false);
        release = false;
        return;
    }
    const auto now = std::chrono::steady_clock::now();
    if (queue.empty() && now - last_check > std::chrono::milliseconds(100)) {
        last_check = now;
        if (FILE* f = std::fopen(path, "r")) {
            char token[32];
            while (std::fscanf(f, "%31s", token) == 1) {
                queue.emplace_back(token);
            }
            std::fclose(f);
            std::remove(path);
        }
    }
    if (queue.empty()) {
        return;
    }
    const std::string token = queue.front();
    queue.erase(queue.begin());
    if (token == "toggle") {
        SetOpen(!menu_open);
        return;
    }
    held = token == "up" ? ImGuiKey_GamepadDpadUp : token == "down" ? ImGuiKey_GamepadDpadDown
         : token == "left" ? ImGuiKey_GamepadDpadLeft : token == "right" ? ImGuiKey_GamepadDpadRight
         : token == "enter" ? ImGuiKey_GamepadFaceDown : token == "l1" ? ImGuiKey_GamepadL1
         : token == "r1" ? ImGuiKey_GamepadR1 : token == "kdown" ? ImGuiKey_DownArrow
         : token == "kup" ? ImGuiKey_UpArrow : ImGuiKey_None;
    if (token == "back") {
        SetOpen(false);
        return;
    }
    if (held != ImGuiKey_None) {
        io.AddKeyEvent(held, true);
        release = true;
    }
}

} // namespace

void SetTextPrompt(bool active, const std::string& prompt, const std::string& text) {
    {
        std::scoped_lock lock{prompt_mutex};
        prompt_title = prompt;
        prompt_text = text;
    }
    prompt_active = active;
}

void Init(const Vulkan::Instance& instance, vk::Format format, u32 image_count) {
    std::scoped_lock lock{imgui_mutex};
    if (initialized) {
        return;
    }
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr; // window positions are not kept
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
    io.BackendFlags |= ImGuiBackendFlags_HasGamepad;
    io.BackendPlatformName = "renderer";

    ImGui::StyleColorsDark();
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowRounding = 6.0f;
    style.FrameRounding = 4.0f;
    style.GrabRounding = 4.0f;
    style.Colors[ImGuiCol_WindowBg].w = 0.92f;

    ImFontConfig font_config;
    font_config.FontDataOwnedByAtlas = false;
    io.Fonts->AddFontFromMemoryTTF(const_cast<unsigned char*>(sky_font_ttf),
                                   int(sky_font_ttf_end - sky_font_ttf), 18.0f, &font_config);

    const vk::Instance vk_instance = instance.GetInstance();
    ImGui_ImplVulkan_LoadFunctions(
        instance.ApiVersion(),
        [](const char* name, void* user) {
            return VULKAN_HPP_DEFAULT_DISPATCHER.vkGetInstanceProcAddr(
                *static_cast<const vk::Instance*>(user), name);
        },
        const_cast<vk::Instance*>(&vk_instance));

    const VkFormat color_format = static_cast<VkFormat>(format);
    ImGui_ImplVulkan_InitInfo info{};
    info.ApiVersion = instance.ApiVersion();
    info.Instance = vk_instance;
    info.PhysicalDevice = instance.GetPhysicalDevice();
    info.Device = instance.GetDevice();
    info.QueueFamily = instance.GetGraphicsQueueFamilyIndex();
    info.Queue = instance.GetGraphicsQueue();
    info.DescriptorPoolSize = 16;
    info.MinImageCount = std::max(image_count, 2u);
    info.ImageCount = std::max(image_count, 2u);
    info.UseDynamicRendering = true;
    info.PipelineInfoMain.PipelineRenderingCreateInfo = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO_KHR,
        .colorAttachmentCount = 1,
        .pColorAttachmentFormats = &color_format,
    };
    if (!ImGui_ImplVulkan_Init(&info)) {
        std::printf("Overlay: ImGui Vulkan backend init failed\n");
        ImGui::DestroyContext();
        return;
    }
    if(!sky_pc_fps_counter && std::getenv("SKY_FPS_COUNTER"))
        SkySettings::Get().show_fps=PcChoice("SKY_FPS_COUNTER",1)!=0;
    initialized = true;
    std::printf("Overlay: menu ready (Insert or L3+R3)\n");
}

void UpdateTextInput(SDL_Window* window) {
    bool want = false;
    {
        std::scoped_lock lock{imgui_mutex};
        const auto* embedded=std::getenv("SKY_PC_MENU_EMBEDDED");
        want = initialized && menu_open && (ImGui::GetIO().WantTextInput ||
            (embedded&&embedded[0]=='1'&&sky_pc_external_menu&&sky_pc_external_menu()));
    }
    if (want != SDL_TextInputActive(window)) {
        if (want) {
            SDL_StartTextInput(window);
        } else {
            SDL_StopTextInput(window);
        }
    }
}

extern "C" void skyrender_pc_menu_toggle(){std::scoped_lock lock{imgui_mutex};if(initialized)SetOpen(!menu_open);}

bool HandleEvent(const SDL_Event& event) {
    std::scoped_lock lock{imgui_mutex};
    if (!initialized) {
        return false;
    }
    ImGuiIO& io = ImGui::GetIO();
    const bool is_open = menu_open;
    switch (event.type) {
    case SDL_EVENT_KEY_DOWN:
    case SDL_EVENT_KEY_UP: {
        const bool down = event.type == SDL_EVENT_KEY_DOWN;
        if (down && !event.key.repeat &&
            (event.key.key == SDLK_INSERT || (is_open && event.key.key == SDLK_ESCAPE))) {
            SetOpen(event.key.key == SDLK_INSERT ? !is_open : false);
            return true;
        }
        if (!is_open) {
            return false;
        }
        io.AddKeyEvent(ImGuiMod_Ctrl, (event.key.mod & SDL_KMOD_CTRL) != 0);
        io.AddKeyEvent(ImGuiMod_Shift, (event.key.mod & SDL_KMOD_SHIFT) != 0);
        io.AddKeyEvent(ImGuiMod_Alt, (event.key.mod & SDL_KMOD_ALT) != 0);
        if (const ImGuiKey key = KeyFromSdl(event.key.key); key != ImGuiKey_None) {
            io.AddKeyEvent(key, down);
        }
        return true;
    }
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
    case SDL_EVENT_GAMEPAD_BUTTON_UP: {
        const bool down = event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN;
        const u8 button = event.gbutton.button;
        if (button == SDL_GAMEPAD_BUTTON_LEFT_STICK) {
            l3_down = down;
        } else if (button == SDL_GAMEPAD_BUTTON_RIGHT_STICK) {
            r3_down = down;
        }
        if (down && l3_down && r3_down) {
            SetOpen(!is_open);
            return true;
        }
        if (!is_open) {
            return false;
        }
        if(sky_pc_external_menu&&sky_pc_external_menu()&&sky_pc_menu_gamepad){
            const int key=button==SDL_GAMEPAD_BUTTON_DPAD_UP?1:button==SDL_GAMEPAD_BUTTON_DPAD_DOWN?2:button==SDL_GAMEPAD_BUTTON_DPAD_LEFT?3:button==SDL_GAMEPAD_BUTTON_DPAD_RIGHT?4:button==SDL_GAMEPAD_BUTTON_SOUTH?5:button==SDL_GAMEPAD_BUTTON_EAST?6:0;
            if(key)sky_pc_menu_gamepad(down?key:-key);return true;
        }
        if (const ImGuiKey key = KeyFromGamepad(button); key != ImGuiKey_None) {
            io.AddKeyEvent(key, down);
        }
        return true;
    }
    case SDL_EVENT_TEXT_INPUT: {
        // Typed characters (Ctrl+click on a slider, a text field): key events alone erase but
        // do not type. SDL sends them while text input is on (UpdateTextInput).
        if (!is_open) {
            return false;
        }
        io.AddInputCharactersUTF8(event.text.text);
        return true;
    }
    case SDL_EVENT_MOUSE_MOTION: {
        if (!is_open) {
            return false;
        }
        const float density = PixelDensity(event.motion.windowID);
        io.AddMousePosEvent(event.motion.x * density, event.motion.y * density);
        return true;
    }
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
    case SDL_EVENT_MOUSE_BUTTON_UP: {
        if (!is_open) {
            return false;
        }
        const int button = event.button.button == SDL_BUTTON_LEFT    ? 0
                           : event.button.button == SDL_BUTTON_RIGHT  ? 1
                           : event.button.button == SDL_BUTTON_MIDDLE ? 2
                                                                      : -1;
        if (button >= 0) {
            io.AddMouseButtonEvent(button, event.type == SDL_EVENT_MOUSE_BUTTON_DOWN);
        }
        return true;
    }
    case SDL_EVENT_MOUSE_WHEEL:
        if (!is_open) {
            return false;
        }
        io.AddMouseWheelEvent(event.wheel.x, event.wheel.y);
        return true;
    default:
        return false;
    }
}

void SetBanner(const char* text) {
    {
        std::scoped_lock lock{banner_mutex};
        banner_text = text ? text : "";
    }
    banner_active = text != nullptr && text[0] != 0;
}

bool Visible() {
    return initialized && (menu_open || prompt_active || banner_active ||
                           FpsCounterEnabled());
}

bool MenuOpen() {
    return menu_open;
}

bool CapturesInput() {
    // The text dialog too: keys typed into it (Backspace is the touchpad) stay out of the game.
    return menu_open || prompt_active;
}

void Render(vk::CommandBuffer cmdbuf, vk::ImageView view, vk::Extent2D extent) {

    // Present interval for the FPS readout (measured also while nothing is drawn).
    const auto now = std::chrono::steady_clock::now();
    const float ms = std::chrono::duration<float, std::milli>(now - last_present).count();
    last_present = now;
    if (ms > 0.0f && ms < 1000.0f) {
        frame_ms_avg = frame_ms_avg == 0.0f ? ms : frame_ms_avg * 0.95f + ms * 0.05f;
    }
    if (sky_pc_report_frame_time) sky_pc_report_frame_time(frame_ms_avg);
    // SKY_RENDERER_FPS_PRINT=1: the present rate every 5 s on stdout, without the cost of SKY_RENDERER_FRAME_STATS
    // (its timers are in the draw path): to measure as players run the game.
    static const bool fps_print = [] {
        const char* env = std::getenv("SKY_RENDERER_FPS_PRINT");
        return env && env[0] == '1';
    }();
    if (fps_print) {
        static auto window_start = now;
        static std::uint64_t presents = 0;
        ++presents;
        if (const double s = std::chrono::duration<double>(now - window_start).count(); s >= 5.0) {
            std::printf("Present rate: %.1f FPS over %.1f s\n", presents / s, s);
            std::fflush(stdout);
            window_start = now;
            presents = 0;
        }
    }
    if (std::getenv("SKY_RENDERER_MENU_KEYS_FILE") && initialized) {
        std::scoped_lock lock{imgui_mutex};
        ScriptedKeys();
    }
    if (!Visible()) {
        return;
    }
    std::scoped_lock lock{imgui_mutex};
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(float(extent.width), float(extent.height));
    io.DeltaTime = ms > 0.0f && ms < 1000.0f ? ms / 1000.0f : 1.0f / 60.0f;
    // UI scale follows the display height (1080p = 1).
    const float scale = std::max(float(extent.height) / 1080.0f, 0.75f);
    if (std::abs(scale - base_scale) > 0.01f) {
        ImGuiStyle& style = ImGui::GetStyle();
        style.ScaleAllSizes(scale / base_scale);
        style.FontScaleMain = scale;
        base_scale = scale;
    }

    ImGui_ImplVulkan_NewFrame();
    ImGui::NewFrame();
    if (menu_open) {
        Menu();
    }
    if (FpsCounterEnabled()) {
        FpsCounter();
    }
    TrophyToast();
    if (prompt_active && !menu_open) {
        TextPrompt();
    }
    if (banner_active) {
        std::string text;
        {
            std::scoped_lock banner_lock{banner_mutex};
            text = banner_text;
        }
        const ImVec2 size = ImGui::CalcTextSize(text.c_str());
        auto* draw = ImGui::GetForegroundDrawList();
        const ImVec2 at{(io.DisplaySize.x - size.x) * 0.5f, io.DisplaySize.y * 0.82f};
        draw->AddRectFilled({at.x - 24.0f, at.y - 12.0f}, {at.x + size.x + 24.0f, at.y + size.y + 12.0f},
                            IM_COL32(0, 0, 0, 170), 6.0f);
        draw->AddText(at, IM_COL32(230, 220, 200, 255), text.c_str());
    }
    ImGui::Render();

    const vk::RenderingAttachmentInfo attachment{
        .imageView = view,
        .imageLayout = vk::ImageLayout::eColorAttachmentOptimal,
        .loadOp = vk::AttachmentLoadOp::eLoad,
        .storeOp = vk::AttachmentStoreOp::eStore,
    };
    cmdbuf.beginRendering(vk::RenderingInfo{
        .renderArea = {{0, 0}, extent},
        .layerCount = 1,
        .colorAttachmentCount = 1,
        .pColorAttachments = &attachment,
    });
    {
        // Font atlas uploads submit to the graphics queue themselves.
        std::scoped_lock submit_lock{Vulkan::Scheduler::submit_mutex};
        ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), cmdbuf);
    }
    cmdbuf.endRendering();
}

} // namespace SkyOverlay

extern "C" void skyrender_overlay_banner(const char* text) {
    SkyOverlay::SetBanner(text);
}

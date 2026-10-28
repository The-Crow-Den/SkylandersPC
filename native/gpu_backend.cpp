// SPDX-License-Identifier: GPL-3.0-or-later
#include "gpu_backend.hpp"
#ifdef SKY_RENDERER
#include "window_icon.hpp"
#endif
#include "thread_context.hpp"
#include "guest_start.hpp"
#include "hle/kernel_clock.hpp"
#include "hle/keyboard_pad.hpp"
#include "game_hooks.hpp"
#include "pc_settings.hpp"
#include "controller_layout.hpp"
#include "portal_library.hpp"
#include "pc_overlay_bridge.hpp"
#include "hle/virtual_portal.hpp"
#include <array>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
#include <unistd.h>
#include <atomic>
#include <filesystem>
#include <mutex>
#include <unordered_map>
#include <signal.h>

#ifdef SKY_RENDERER
#include <csetjmp>
#include <pthread.h>
#include "renderer_adapter.hpp"
#include <SDL3/SDL.h>
extern "C" {
#include "runtime.h"
}

namespace {
using U = std::uint64_t;
KernelClock gpu_clock;
std::string game_serial = "UNKNOWN", gpu_user_directory;
std::uint32_t sdk_version = 0, psf_attributes = 0;
std::once_flag presenter_once;
std::atomic<bool> presenter_ready = false;
std::atomic<U> last_video_size = 0;
KeyboardPad* keyboard_pad = nullptr;
std::array<bool, SDL_SCANCODE_COUNT> pressed_keys{}; // Only the SDL window thread updates this.
std::array<SDL_Gamepad*,2> physical_gamepads{};
std::array<std::atomic<int>,2> controller_families{};
extern "C" int sky_controller_family(int player){return player>=0 && player<2?controller_families[static_cast<unsigned>(player)].load():0;}
std::mutex gamepad_mutex;
void (*portal_load)(const char*) = nullptr;
void (*portal_remove)() = nullptr;
void (*portal_trap)(const char*) = nullptr;
void (*portal_remove_trap)() = nullptr;
int trap_dialog_tag,second_dialog_tag;
std::atomic<int> portal_volume{30};
SDL_AudioStream* portal_audio_stream=nullptr;
std::mutex portal_audio_mutex;
extern "C" int sky_portal_volume(){return portal_volume.load();}
extern "C" void sky_portal_set_volume(int value){if(value>=0&&value<=100)portal_volume=value;}
void portal_speaker(const unsigned char* bytes,std::size_t size) {
    if(size!=64 || !bytes)return;
    std::lock_guard guard(portal_audio_mutex);
    if(!portal_audio_stream) {
        if(!SDL_WasInit(SDL_INIT_AUDIO) && !SDL_InitSubSystem(SDL_INIT_AUDIO)){std::fprintf(stderr,"Portal speaker initialization failed: %s\n",SDL_GetError());return;}
        SDL_AudioSpec spec{SDL_AUDIO_S16LE,1,8000};
        portal_audio_stream=SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK,&spec,nullptr,nullptr);
        if(!portal_audio_stream){std::fprintf(stderr,"Portal speaker: %s\n",SDL_GetError());return;}
        SDL_ResumeAudioStreamDevice(portal_audio_stream);
        std::printf("Portal speaker: 8000 Hz mono PCM to PC output; default gain 30%%\n");
    }
    SDL_SetAudioStreamGain(portal_audio_stream,static_cast<float>(portal_volume.load())/100.0f);
    if(SDL_GetAudioStreamQueued(portal_audio_stream)>3200)SDL_ClearAudioStream(portal_audio_stream);
    SDL_PutAudioStreamData(portal_audio_stream,bytes,static_cast<int>(size));
}
std::atomic<Uint32> portal_action_event{0};
extern "C" int sky_portal_action(int action,int index) {
    const auto type=portal_action_event.load();if(!type)return 0;
    SDL_Event event{};event.type=type;event.user.code=action;
    event.user.data1=reinterpret_cast<void*>(static_cast<std::intptr_t>(index));
    return SDL_PushEvent(&event)?1:0;
}
void portal_dialog(void* tag, const char* const* paths, int) {
    if(!paths || !paths[0])return;
    if(tag==&trap_dialog_tag){if(portal_trap)portal_trap(paths[0]);}
    else PortalLibrary::import_character(paths[0],true,tag==&second_dialog_tag?1:0);
}
void update_gamepad(const SDL_Event* event = nullptr) {
    std::lock_guard guard(gamepad_mutex);
    bool enumerate=!event || event->type==SDL_EVENT_GAMEPAD_ADDED || event->type==SDL_EVENT_GAMEPAD_REMOVED;
    for(auto& pad:physical_gamepads) {
        if(pad && (!SDL_GamepadConnected(pad) || (event && event->type==SDL_EVENT_GAMEPAD_REMOVED && SDL_GetGamepadID(pad)==event->gdevice.which))) {
            SDL_CloseGamepad(pad);pad=nullptr;enumerate=true;
        }
    }
    if(enumerate) {
    int count=0;auto* ids=SDL_GetGamepads(&count);
    for(int i=0;i<count;++i) {
        if(std::any_of(physical_gamepads.begin(),physical_gamepads.end(),[&](auto* pad){return pad && SDL_GetGamepadID(pad)==ids[i];}))continue;
        const auto* mode=std::getenv("SKY_CONTROLLER_LAYOUT");
        const bool keyboard_and_pad=mode && !std::strcmp(mode,"keyboard-and-pad");
        std::array<std::uint32_t,2> assigned{};
        for(unsigned slot=0;slot<physical_gamepads.size();++slot)
            if(physical_gamepads[slot])assigned[slot]=SDL_GetGamepadID(physical_gamepads[slot]);
        const int chosen=ControllerLayout::assign(assigned,ids[i],keyboard_and_pad);
        if(chosen>=0) {
            const auto slot=static_cast<unsigned>(chosen);
            physical_gamepads[slot]=SDL_OpenGamepad(ids[i]);
            if(physical_gamepads[slot])std::printf("Controller %u: %s connected via SDL\n",slot+1,SDL_GetGamepadName(physical_gamepads[slot]));
        }
    }
    SDL_free(ids);
    }
    for(unsigned slot=0;slot<physical_gamepads.size();++slot) {
    auto* physical_gamepad=physical_gamepads[slot];
    int family=0;
    if(physical_gamepad) {
        const auto type=SDL_GetGamepadType(physical_gamepad);
        family=(type==SDL_GAMEPAD_TYPE_PS3 || type==SDL_GAMEPAD_TYPE_PS4 || type==SDL_GAMEPAD_TYPE_PS5)?1:
            (type==SDL_GAMEPAD_TYPE_XBOX360 || type==SDL_GAMEPAD_TYPE_XBOXONE)?2:
            (type==SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_PRO || type==SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT || type==SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT || type==SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_PAIR)?3:4;
    }
    controller_families[slot].store(family);
    KeyboardPad::PhysicalState state;
    state.connected = physical_gamepad && SDL_GamepadConnected(physical_gamepad);
    if (state.connected && !Renderer::overlay_captures_input()) {
        constexpr std::pair<SDL_GamepadButton, std::uint32_t> buttons[]{
            {SDL_GAMEPAD_BUTTON_SOUTH,0x4000}, {SDL_GAMEPAD_BUTTON_EAST,0x2000},
            {SDL_GAMEPAD_BUTTON_WEST,0x8000}, {SDL_GAMEPAD_BUTTON_NORTH,0x1000},
            {SDL_GAMEPAD_BUTTON_DPAD_UP,0x10}, {SDL_GAMEPAD_BUTTON_DPAD_RIGHT,0x20},
            {SDL_GAMEPAD_BUTTON_DPAD_DOWN,0x40}, {SDL_GAMEPAD_BUTTON_DPAD_LEFT,0x80},
            {SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,0x400}, {SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,0x800},
            {SDL_GAMEPAD_BUTTON_LEFT_STICK,2}, {SDL_GAMEPAD_BUTTON_RIGHT_STICK,4},
            {SDL_GAMEPAD_BUTTON_START,8}, {SDL_GAMEPAD_BUTTON_GUIDE,0x10000},
            {SDL_GAMEPAD_BUTTON_TOUCHPAD,0x100000}};
        for (const auto& [button, mask] : buttons) if (SDL_GetGamepadButton(physical_gamepad, button)) state.buttons |= mask;
        constexpr SDL_GamepadAxis axes[]{SDL_GAMEPAD_AXIS_LEFTX,SDL_GAMEPAD_AXIS_LEFTY,SDL_GAMEPAD_AXIS_RIGHTX,SDL_GAMEPAD_AXIS_RIGHTY};
        for (unsigned i=0;i<4;++i) state.axes[i] = static_cast<unsigned char>((static_cast<int>(SDL_GetGamepadAxis(physical_gamepad,axes[i]))+32768)/256);
        for (unsigned i=0;i<2;++i) {
            const auto value = SDL_GetGamepadAxis(physical_gamepad, i ? SDL_GAMEPAD_AXIS_RIGHT_TRIGGER : SDL_GAMEPAD_AXIS_LEFT_TRIGGER);
            state.triggers[i] = static_cast<unsigned char>(std::max(0,static_cast<int>(value))*255/32767);
            if (value > 0x1000) state.buttons |= i ? 0x200 : 0x100;
        }
    }
    if (keyboard_pad) keyboard_pad->set_physical(state,slot);
    }
}
int keyboard_event(const void* raw_event, void*) {
    if (!keyboard_pad) return 0;
    const auto& event = *static_cast<const SDL_Event*>(raw_event);
    if(event.type==SDL_EVENT_WINDOW_MOVED||event.type==SDL_EVENT_WINDOW_RESIZED||event.type==SDL_EVENT_WINDOW_FOCUS_GAINED||event.type==SDL_EVENT_KEY_DOWN) {
        const auto id=event.type==SDL_EVENT_KEY_DOWN?event.key.windowID:event.window.windowID;
        if(auto* window=SDL_GetWindowFromID(id)){int x=0,y=0,w=0,h=0;SDL_GetWindowPosition(window,&x,&y);SDL_GetWindowSize(window,&w,&h);PcOverlay::geometry(x,y,w,h);}
    }
    if(event.type==portal_action_event.load()) {
        const auto index=static_cast<int>(reinterpret_cast<std::intptr_t>(event.user.data1));
        if(event.user.code==0 || event.user.code==1 || event.user.code==6 || event.user.code==8)PortalLibrary::select(event.user.code==6?3:event.user.code==8?2:event.user.code,index);
        else if(event.user.code==2 || event.user.code==11) {
            static const SDL_DialogFileFilter filters[]{{"Skylander figure dump","sky;bin"}};
            SDL_ShowOpenFileDialog(&portal_dialog,event.user.code==11?&second_dialog_tag:nullptr,nullptr,filters,1,nullptr,false);
        } else if(event.user.code==3 || event.user.code==4)PortalLibrary::remove(event.user.code-3);
        else if(event.user.code==5 || event.user.code==10)PortalLibrary::create_character(index,true,event.user.code==10?1:0);
        else if(event.user.code==12)PortalLibrary::select_empty_trap(index);
        else if(event.user.code==7 || event.user.code==9)PortalLibrary::remove(event.user.code==7?3:2);
        else if(event.user.code==20){if(Renderer::overlay_captures_input())Renderer::toggle_menu();}
        else if(event.user.code==21){SDL_Event quit{};quit.type=SDL_EVENT_QUIT;SDL_PushEvent(&quit);}
        return 1;
    }
    if (event.type == SDL_EVENT_KEY_DOWN && !event.key.repeat &&
        (event.key.scancode == SDL_SCANCODE_F6 || event.key.scancode == SDL_SCANCODE_INSERT) && Renderer::has_menu_toggle()) {
        pressed_keys.fill(false); keyboard_pad->release_keys();
        Renderer::toggle_menu(); return 1;
    }
    if (event.type == SDL_EVENT_KEY_DOWN && !event.key.repeat &&
        event.key.scancode == SDL_SCANCODE_F1 && (event.key.mod & SDL_KMOD_SHIFT) &&
        !std::getenv("SKY_EXTERNAL_FRAME_CAP")) {
        sky_pc_set_frame_limit(sky_pc_frame_limit() == 30 ? 60 : 30);
        return 1;
    }
    if (Renderer::overlay_captures_input()) {
        pressed_keys.fill(false); keyboard_pad->release_keys();
        if (event.type >= SDL_EVENT_GAMEPAD_AXIS_MOTION && event.type <= SDL_EVENT_GAMEPAD_STEAM_HANDLE_UPDATED) update_gamepad(&event);
        return 0; // The renderer routes this event into the PC menu.
    }
    if (event.type == SDL_EVENT_KEY_DOWN && !event.key.repeat) {
        if (event.key.scancode == SDL_SCANCODE_F2 && portal_load) {
            static const SDL_DialogFileFilter filters[]{{"Skylander figure dump", "sky;bin"}};
            SDL_ShowOpenFileDialog(&portal_dialog,nullptr,nullptr,filters,1,nullptr,false);
            return 0;
        }
        if (event.key.scancode == SDL_SCANCODE_F3 && portal_remove) { PortalLibrary::remove(0); return 0; }
        if (event.key.scancode == SDL_SCANCODE_F4 && portal_trap) {
            static const SDL_DialogFileFilter filters[]{{"Trap dump", "sky;bin"}};
            SDL_ShowOpenFileDialog(&portal_dialog,&trap_dialog_tag,nullptr,filters,1,nullptr,false);return 0;
        }
        if(event.key.scancode==SDL_SCANCODE_F5 && portal_remove_trap){PortalLibrary::remove(1);return 0;}
    }
    if (event.type >= SDL_EVENT_GAMEPAD_AXIS_MOTION && event.type <= SDL_EVENT_GAMEPAD_STEAM_HANDLE_UPDATED) {
        update_gamepad(&event); return 0;
    }
    if (event.type == SDL_EVENT_WINDOW_FOCUS_LOST) { pressed_keys.fill(false); keyboard_pad->release_keys(); return 0; }
    if (event.type != SDL_EVENT_KEY_DOWN && event.type != SDL_EVENT_KEY_UP) return 0;
    const auto code = static_cast<std::size_t>(event.key.scancode);
    if (code >= pressed_keys.size()) return 0;
    pressed_keys[code] = event.type == SDL_EVENT_KEY_DOWN;
    constexpr std::pair<SDL_Scancode, std::uint32_t> mappings[]{
        {SDL_SCANCODE_N, 0x4000}, {SDL_SCANCODE_SPACE, 0x4000}, {SDL_SCANCODE_RETURN, 0x4000},
        {SDL_SCANCODE_ESCAPE, 0x2000}, {SDL_SCANCODE_Z, 0x8000}, {SDL_SCANCODE_X, 0x1000},
        {SDL_SCANCODE_UP, 0x10}, {SDL_SCANCODE_RIGHT, 0x20}, {SDL_SCANCODE_DOWN, 0x40}, {SDL_SCANCODE_LEFT, 0x80},
        {SDL_SCANCODE_Q, 0x400}, {SDL_SCANCODE_E, 0x800}, {SDL_SCANCODE_TAB, 0x8},
        {SDL_SCANCODE_LSHIFT, 0x2}, {SDL_SCANCODE_LCTRL, 0x4},
        {SDL_SCANCODE_A, 1u << 24}, {SDL_SCANCODE_D, 1u << 25},
        {SDL_SCANCODE_W, 1u << 26}, {SDL_SCANCODE_S, 1u << 27},
    };
    std::uint32_t keys = 0;
    for (const auto& [scan, mask] : mappings) if (pressed_keys[scan]) keys |= mask;
    keyboard_pad->set_keys(keys);
    return 0;
}
thread_local std::int32_t background_errno = 0;
const char* media_symbol(const char* identity);
struct MemorySymbol { const char* name; const char* identity; };
constexpr std::array<MemorySymbol, 7> memory_symbols{{
    {"sceKernelGetDirectMemorySize", "pO96TwzOm5E#libkernel#libkernel"},
    {"sceKernelAllocateDirectMemory", "rTXw65xmLIA#libkernel#libkernel"},
    {"sceKernelMapDirectMemory", "L-Q3LEjIbgA#libkernel#libkernel"},
    {"sceKernelReleaseDirectMemory", "MBuItvba6z8#libkernel#libkernel"},
    {"sceKernelMunmap", "cQke9UuBQOk#libkernel#libkernel"},
    {"sceKernelMapFlexibleMemory", "IWIBBdTHit4#libkernel#libkernel"},
    {"sceKernelVirtualQuery", "rVjRvHJ0X6c#libkernel#libkernel"},
}};
}
extern "C" {
int32_t* runtime_errno() {
    auto* context = GuestThreadContext::current();
    return context ? context->error_pointer() : &background_errno;
}
const char* runtime_symbol(const char* identity) {
    for (const auto& symbol : memory_symbols) if (std::strcmp(identity, symbol.identity) == 0 || std::strcmp(identity, symbol.name) == 0) return symbol.name;
    return media_symbol(identity);
}
uintptr_t runtime_lookup(const RuntimeExport* table, size_t count, const char* identity) {
    const auto* name = runtime_symbol(identity);
    if (!name) return 0;
    for (size_t i = 0; i < count; ++i) if (!std::strcmp(table[i].name, name)) return reinterpret_cast<uintptr_t>(table[i].function);
    return 0;
}
void runtime_guest_call_sites(uint64_t out[3]) { out[0] = out[1] = out[2] = 0; }
void runtime_restart() { dprintf(STDERR_FILENO, "custom runtime restart is unsupported\n"); _exit(75); }
int runtime_file_translate(const char*, char*, size_t) { return -1; }
int runtime_file_host_path(const char*, char*, size_t) { return -1; }
int runtime_pad_mouse_look() { return 0; }
int runtime_pad_prompt_device() { return 0; }
unsigned runtime_pad_prompt_generation() { return 0; }
int runtime_pad_prompt(const char*, int, char* label, int size) { if (label && size > 0) label[0] = 0; return 0; }
void runtime_re_watch(uint64_t) {} // Optional Bloodborne reverse-engineering watch is disabled.
void runtime_thread_attach_host(const char* name) { if (name) pthread_setname_np(pthread_self(), name); }
void runtime_wait_report(double) { dprintf(STDERR_FILENO, "GPU wait profiling is disabled\n"); }
void runtime_sleep_stats(uint64_t* calls, uint64_t* ns) { *calls = *ns = 0; } // GPU-library-specific profiler is disabled.
uint64_t runtime_process_time_us() {
    const std::array<U, 6> args{};
    return gpu_clock.call("4J2sUJmuHZQ#libkernel#libkernel", args.data());
}
uint64_t runtime_process_time_counter() { return runtime_process_time_us() * 1000; }
uint64_t runtime_tsc_frequency() {
    const std::array<U, 6> args{};
    return gpu_clock.call("1j3S3n-tTW4#libkernel#libkernel", args.data());
}
}
#endif

namespace {
struct GpuContract { std::string_view identity; unsigned parameters; bool returns_void; unsigned provider = 0; const char* symbol = nullptr; };
constexpr GpuContract gpu_contracts[] = {
#include "gpu_contracts.inc"
#include "media_contracts.inc"
};
const GpuContract* contract(std::string_view identity) {
    static const auto index = [] {
        std::unordered_map<std::string_view, const GpuContract*> result;
        result.reserve(std::size(gpu_contracts));
        for (const auto& item : gpu_contracts) {
            if (!result.emplace(item.identity, &item).second)
                throw std::runtime_error("duplicate scoped GPU contract");
        }
        return result;
    }();
    const auto found = index.find(identity);
    return found == index.end() ? nullptr : found->second;
}
#ifdef SKY_RENDERER
const char* media_symbol(const char* identity) {
    const auto* item = contract(identity);
    return item && item->provider ? item->symbol : nullptr;
}
#endif
}
namespace SkyGpu {
bool captures_input() {
#ifdef SKY_RENDERER
    return presenter_ready && Renderer::overlay_captures_input();
#else
    return false;
#endif
}

void bind_portal(void (*load)(const char*), void (*remove)(),void (*trap)(const char*),void (*remove_trap)()) {
#ifdef SKY_RENDERER
    portal_load=load; portal_remove=remove;
    portal_trap=trap;portal_remove_trap=remove_trap;
#else
    (void)load;(void)remove;(void)trap;(void)remove_trap;
#endif
}
void bind_keyboard(KeyboardPad* pad) {
#ifdef SKY_RENDERER
    keyboard_pad = pad;
    if(pad)for(unsigned slot=0;slot<2;++slot)pad->bind_rumble([slot](unsigned char large,unsigned char small){
        std::lock_guard guard(gamepad_mutex);
        auto* controller=physical_gamepads[slot];
        return controller && SDL_GamepadConnected(controller) &&
            SDL_RumbleGamepad(controller,static_cast<Uint16>(large*257u),static_cast<Uint16>(small*257u),1000);
    },slot);
    Renderer::add_event_filter(&keyboard_event);
#else
    (void)pad;
#endif
}
void prepare_cpu_write(std::uint64_t address, std::uint64_t size) {
#ifdef SKY_RENDERER
    if (address && size) runtime_memory_prepare_cpu_write(address, size);
#else
    (void)address; (void)size;
#endif
}
void note_cpu_write(std::uint64_t address, std::uint64_t size) {
#ifdef SKY_RENDERER
    if (address && size) runtime_memory_note_write(address, size);
#else
    (void)address; (void)size;
#endif
}
void configure(const std::string& serial, std::uint32_t sdk, std::uint32_t attributes) {
#ifdef SKY_RENDERER
    game_serial = serial; sdk_version = sdk; psf_attributes = attributes;
    PortalLibrary::initialize(std::getenv("SKY_PORTAL_FIGURE"));
    VirtualPortal::bind_audio(&portal_speaker);
    if(const auto* volume=std::getenv("SKY_PORTAL_VOLUME"))portal_volume=std::clamp(std::atoi(volume),0,100);
    // SKY_GPU_USER_DIR selects another settings/pipeline-cache directory,
    // e.g. an empty one for cold-cache profiling.
    const auto* user_directory = std::getenv("SKY_GPU_USER_DIR");
    gpu_user_directory = std::filesystem::absolute(user_directory && *user_directory ? user_directory : "out/native-gpu-user").string();
    std::filesystem::create_directories(gpu_user_directory);
    Renderer::set_option("GPU_USER_DIR", gpu_user_directory.c_str(), true);
    Renderer::set_option("CONFIG", (gpu_user_directory + "/" + Renderer::settings_file).c_str(), true);
    Renderer::set_option("GAME_PROFILE", "none", true);
    Renderer::set_option("GAME_MENU", "0", true);
    setenv("SKY_PC_MENU", "1", 1);
    Renderer::set_option("NATIVE_MOUSE", "0", true);
    Renderer::set_option("FREE_MOUSE", "1", true);
    Renderer::set_option("CURSOR", "0", true);
    Renderer::set_option("UPSCALER", "off", true);
    Renderer::set_option("OBJECT_MOTION", "0", true);
    Renderer::set_option("FRAME_GEN", "0", true);
    Renderer::set_option("SUBMIT_LOCK", "gpu", true);
    // The renderer defaults to forced 16x filtering, which this title does not
    // use. Preserve its own samplers unless the user explicitly overrides.
    Renderer::set_option("ANISO", "0", false);
    std::printf("Texture filtering: SKY_RENDERER_ANISO=%s (0 preserves game samplers)\n",Renderer::option("ANISO"));
    const auto* incomplete=std::getenv("SKY_ALLOW_INCOMPLETE_PIPELINES");
    const bool skip_draws=incomplete && std::strcmp(incomplete,"1")==0;
    Renderer::set_option("ASYNC_PIPELINES",skip_draws?"1":"0",true);
    Renderer::set_option("PIPELINE_CACHE","1",true);
    std::printf("Renderer: pipeline cache on; incomplete pipeline draw skipping %s\n",skip_draws?"enabled (diagnostic)":"disabled");
    if (const char* timing = std::getenv("SKY_TIMING_TRACE"); timing && std::strcmp(timing, "1") == 0) {
        Renderer::set_option("FRAME_STATS", "1", true);
        Renderer::set_option("AUDIO_STATS", "1", true);
        std::printf("{\"event\":\"timing-diagnostics\",\"enabled\":true,\"changes_frame_limit\":false}\n");
    }
    Renderer::register_kernel();
#else
    (void)serial; (void)sdk; (void)attributes;
#endif
}
bool handle_fault(int signal, void* info, void* context) {
#ifdef SKY_RENDERER
    if (signal != SIGSEGV && signal != SIGBUS) return false;
    if (runtime_fault_recover) siglongjmp(*runtime_fault_recover, 1);
    return presenter_ready && Renderer::handle_fault(context, static_cast<siginfo_t*>(info)->si_addr);
#else
    (void)signal; (void)info; (void)context;
    return false;
#endif
}
bool enabled() noexcept {
#ifdef SKY_RENDERER
    return true;
#else
    return false;
#endif
}
bool supports(std::string_view identity) noexcept {
    return enabled() && (identity == "jg33rEKLfVs#libSceGnmDriver#libSceGnmDriver" ||
        identity == "rVjRvHJ0X6c#libkernel#libkernel" || contract(identity));
}
unsigned stack_arguments(std::string_view identity) noexcept {
    if (!enabled()) return 0;
    const auto* item = contract(identity);
    return item && item->parameters > 6 ? item->parameters - 6 : 0;
}
std::uint64_t call(std::string_view identity, const std::uint64_t* a) {
#ifdef SKY_RENDERER
    if(identity=="yvZ73uQUqrk#libSceGnmDriver#libSceGnmDriver")
        GameHooks::frame(Renderer::overlay_captures_input());
    if (identity == "rVjRvHJ0X6c#libkernel#libkernel") return memory_call(identity, a);
    if (identity == "i6-sR91Wt-4#libSceVideoOut#libSceVideoOut") {
        const auto width = static_cast<std::uint32_t>(a[4]);
        const auto height = static_cast<std::uint32_t>(a[5]);
        const U size = (U{width} << 32) | height;
        if (last_video_size.exchange(size, std::memory_order_relaxed) != size)
            std::printf("{\"event\":\"guest-video-buffer-size\",\"width\":%u,\"height\":%u,\"pitch\":%u}\n",
                width, height, static_cast<unsigned>(a[6]));
    }
    if (identity == "CBiu4mCE1DA#libSceVideoOut#libSceVideoOut")
        std::printf("{\"event\":\"guest-flip-rate-request\",\"handle\":%u,\"rate\":%d}\n",
            static_cast<unsigned>(a[0]), static_cast<int>(a[1]));
    // bool sceGnmIsUserPaEnabled(void): no user performance-analysis facility.
    // Interface: https://ps4-opengnm.github.io/opengnm/reference/driver/
    if (identity == "jg33rEKLfVs#libSceGnmDriver#libSceGnmDriver") return 0;
    if (identity == "Idffwf3yh8s#libSceGnmDriver#libSceGnmDriver")
        return Renderer::draw_init_default_hardware_state(reinterpret_cast<std::uint32_t*>(a[0]), static_cast<std::uint32_t>(a[1]));
    if (identity == "Up36PTk687E#libSceVideoOut#libSceVideoOut") {
        std::call_once(presenter_once, [] {
            std::int32_t window_width = 1280, window_height = 720;
            if (const auto* size = std::getenv("SKY_WINDOW_SIZE")) {
                bool found = false;
                for (const auto& preset : std::array<std::pair<std::int32_t,std::int32_t>,6>{
                         {{1280,720},{1600,900},{1920,1080},{2560,1440},{2560,1600},{3840,2160}}}) {
                    const auto name = std::to_string(preset.first) + "x" + std::to_string(preset.second);
                    if (name == size) {
                        window_width = preset.first; window_height = preset.second; found = true; break;
                    }
                }
                if (!found) throw std::runtime_error("unsupported SKY_WINDOW_SIZE preset");
            }
            // SDL_APP_ID from the launcher environment takes precedence.
            SDL_SetHint(SDL_HINT_APP_ID,"org.skylanders.PS4Native");
            const auto* build = GameHooks::active();
            const auto title = build ? std::string(build->window_title) : "PS4 native runtime — " + game_serial;
            const Renderer::WindowConfig config{title.c_str(), game_serial.c_str(), gpu_user_directory.c_str(),
                sdk_version, psf_attributes, window_width, window_height};
            if (!Renderer::init(config)) throw std::runtime_error("Vulkan presenter initialization failed");
            apply_window_icon();
            if (const auto* fullscreen = std::getenv("SKY_FULLSCREEN"); fullscreen && !std::strcmp(fullscreen,"1")) {
                int count=0; auto** windows=SDL_GetWindows(&count);
                if (count > 0) SDL_SetWindowFullscreen(windows[0],true);
                SDL_free(windows);
            }
            portal_action_event=SDL_RegisterEvents(1);
            std::printf("PC menu: F6 / Insert / L3+R3; Shift+F1 switches native 30/60 cap\n");
            std::printf("Window backend: %s\n", SDL_GetCurrentVideoDriver());
            if (!SDL_InitSubSystem(SDL_INIT_GAMEPAD))
                std::fprintf(stderr,"Controller initialization failed: %s\n",SDL_GetError());
            else update_gamepad();
            if(std::getenv("SKY_PC_OVERLAY_DIR"))SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS,"1");
            PcOverlay::start();
            presenter_ready = true;
        });
    }
    if (identity == "U46NwOiJpys#libSceVideoOut#libSceVideoOut" ||
        identity == "xbxNatawohc#libSceGnmDriver#libSceGnmDriver" ||
        identity == "Ga6r7H6Y0RI#libSceGnmDriver#libSceGnmDriver") SkyPc::pace();
    const auto* item = contract(identity);
    if (!item) throw std::runtime_error("unregistered GPU signature");
    // Contract identities are static string literals. Resolve each exact scoped
    // entry once, rather than allocate a string and search provider tables on
    // every guest call. Providers remain loaded for the host's lifetime.
    static std::array<std::atomic<std::uintptr_t>, std::size(gpu_contracts)> functions{};
    auto& cached = functions[static_cast<std::size_t>(item - gpu_contracts)];
    auto function = cached.load(std::memory_order_relaxed);
    if (!function) {
        function = item->provider == 1 ? runtime_ajm_resolve(item->identity.data()) :
            item->provider == 2 ? runtime_audio_resolve(item->identity.data()) : Renderer::resolve(item->identity.data());
        if (function) cached.store(function, std::memory_order_relaxed);
    }
    if (!function) throw std::runtime_error("scoped GPU provider is missing");
    const auto result = sky_host_call_integer(reinterpret_cast<void*>(function), a);
    return item->returns_void ? 0 : result;
#else
    (void)identity; (void)a;
#endif
    throw std::runtime_error("unsupported GPU import");
}
std::uint64_t memory_call(std::string_view identity, const std::uint64_t* a) {
#ifdef SKY_RENDERER
    // Canonical identities are checked before the reference's broader resolver.
    std::size_t operation = 0;
    while (operation < memory_symbols.size() && identity != memory_symbols[operation].identity) ++operation;
    if (operation == memory_symbols.size()) throw std::runtime_error("unregistered GPU memory import scope");
    const auto address = runtime_memory_resolve(memory_symbols[operation].identity);
    if (!address) throw std::runtime_error("GPU memory provider lacks registered service");
    using U = std::uint64_t;
    using I = std::int32_t;
    switch (operation) {
    case 0: return reinterpret_cast<U(*)()>(address)();
    case 1: return static_cast<std::uint32_t>(reinterpret_cast<I(*)(std::int64_t, std::int64_t, U, U, I, std::int64_t*)>(address)(
        static_cast<std::int64_t>(a[0]), static_cast<std::int64_t>(a[1]), a[2], a[3], static_cast<I>(a[4]), reinterpret_cast<std::int64_t*>(a[5])));
    case 2: {
        auto** out = reinterpret_cast<void**>(a[0]);
        if (out && (a[3] & 0x10) && (reinterpret_cast<std::uintptr_t>(*out) < 0x1000000000 ||
            reinterpret_cast<std::uintptr_t>(*out) >= 0xfc00000000 || a[1] > 0xfc00000000 - reinterpret_cast<std::uintptr_t>(*out)))
            return 0x80020016;
        return static_cast<std::uint32_t>(reinterpret_cast<I(*)(void**, U, I, I, std::int64_t, U)>(address)(out,
            a[1], static_cast<I>(a[2]), static_cast<I>(a[3]), static_cast<std::int64_t>(a[4]), a[5]));
    }
    case 3: return static_cast<std::uint32_t>(reinterpret_cast<I(*)(std::int64_t, U)>(address)(static_cast<std::int64_t>(a[0]), a[1]));
    case 4: return static_cast<std::uint32_t>(reinterpret_cast<I(*)(void*, U)>(address)(reinterpret_cast<void*>(a[0]), a[1]));
    case 5: return static_cast<std::uint32_t>(reinterpret_cast<I(*)(void**, U, I, I)>(address)(reinterpret_cast<void**>(a[0]), a[1], static_cast<I>(a[2]), static_cast<I>(a[3])));
    case 6: return static_cast<std::uint32_t>(reinterpret_cast<I(*)(const void*, I, void*, U)>(address)(reinterpret_cast<const void*>(a[0]), static_cast<I>(a[1]), reinterpret_cast<void*>(a[2]), a[3]));
    }
#else
    (void)identity; (void)a;
#endif
    throw std::runtime_error("GPU memory backend is unavailable");
}
}

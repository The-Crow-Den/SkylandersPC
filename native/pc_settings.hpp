// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <mutex>
#include <string>

extern "C" int sky_portal_volume() __attribute__((weak));
namespace SkyPc {
struct Resolution { const char* name; int width, height; };
// Same order as PRESETS in tools/resolution.py: the menu sends an index.
inline constexpr std::array<Resolution,8> resolutions{{
    {"480p",854,480},{"720p",1280,720},{"800p",1280,800},{"900p",1600,900},
    {"1080p",1920,1080},{"1440p",2560,1440},{"1600p",2560,1600},{"2160p",3840,2160}}};
inline constexpr int default_resolution = 4; // 1080p
inline std::atomic<bool> show_fps{[] {
    const auto* value=std::getenv("SKY_FPS_COUNTER");
    return !value || std::strcmp(value,"0")!=0;
}()};
inline std::atomic<float> frame_time_ms{0.0f};
inline std::atomic<int> frame_limit{[] {
    const auto* value = std::getenv("SKY_FRAME_LIMIT");
    return value && !std::strcmp(value,"0") ? 0 : value && !std::strcmp(value,"60") ? 60 : 30;
}()};
inline std::atomic<int> manual_limit{[] {
    const auto* value=std::getenv("SKY_MANUAL_FRAME_LIMIT");
    if(!value)return frame_limit.load();
    return value && !std::strcmp(value,"60")?60:value && !std::strcmp(value,"0")?0:30;
}()};
inline bool automatic_available() {
    const auto* value=std::getenv("SKY_AUTO_FRAME_POLICY_AVAILABLE");
    return value && !std::strcmp(value,"1");
}
inline std::atomic<bool> automatic{[] {
    const auto* value=std::getenv("SKY_FRAME_POLICY");
    return automatic_available() && value && !std::strcmp(value,"auto");
}()};
inline std::atomic<int> controller_layout{[] {
    const auto* value=std::getenv("SKY_CONTROLLER_LAYOUT");
    return value && !std::strcmp(value,"keyboard-and-pad")?1:0;
}()};
inline std::atomic<int> controller_glyphs{[] {
    const auto* value=std::getenv("SKY_CONTROLLER_GLYPHS");
    return !value?0:!std::strcmp(value,"playstation")?1:!std::strcmp(value,"xbox")?2:!std::strcmp(value,"nintendo")?3:0;
}()};
inline std::mutex frame_policy_mutex;
// The display's refresh period (0: unknown), set once the game window exists.
inline std::atomic<long long> display_refresh_ns{0};
// The frame period for `fps`: a whole number of display refreshes when the refresh rate is known,
// so frames reach the display on a fixed refresh cadence (30 FPS on 240 Hz: every 8th refresh)
// instead of drifting against it.
inline long long frame_period_ns(int fps) {
    if (fps <= 0) return 0;
    const long long nominal = 1'000'000'000LL / fps;
    const long long refresh = display_refresh_ns.load(std::memory_order_relaxed);
    if (refresh <= 0 || refresh > nominal) return nominal;
    const long long count = (nominal + refresh / 2) / refresh;
    const long long locked = count * refresh;
    // Only lock when the rate stays within 1% of the request (e.g. not 30 on a 75 Hz display).
    return locked * 100 >= nominal * 99 && locked * 100 <= nominal * 101 ? locked : nominal;
}
inline bool apply_frame_limit(int fps) {
    const auto* allow=std::getenv("SKY_ALLOW_60");
    if(fps!=0 && fps!=30 && !(fps==60 && allow && !std::strcmp(allow,"1")))return false;
    if(frame_limit.load()==fps)return true;
    const auto previous=frame_limit.exchange(fps);
    if(previous!=fps)std::printf("{\"event\":\"pc-frame-limit\",\"fps\":%d,\"source\":\"%s\"}\n",fps,automatic.load()?"mod":"manual");
    return true;
}
inline void apply_automatic_limit(int fps) {
    std::lock_guard guard(frame_policy_mutex);
    if(automatic.load())apply_frame_limit(fps);
}
inline void pace() {
    // Gate the submitting guest thread before presenting, without changing the
    // platform vblank frequency, dropping frames, or spinning a CPU core.
    using Clock = std::chrono::steady_clock;
    thread_local auto deadline = Clock::now();
    thread_local int previous = 0;
    const int fps = frame_limit.load(std::memory_order_relaxed);
    if (fps == 0) { previous = 0; deadline = Clock::now(); return; }
    const auto period = std::chrono::nanoseconds(frame_period_ns(fps));
    const auto now = Clock::now();
    if (previous != fps || now - deadline > period) deadline = now;
    previous = fps;
    if (deadline > now) std::this_thread::sleep_until(deadline);
    deadline += period;
}
}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_fps_counter() {return SkyPc::show_fps.load()?1:0;}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_set_fps_counter(int enabled) {
    if(enabled!=0 && enabled!=1)return 0;
    SkyPc::show_fps.store(enabled!=0);return 1;
}
extern "C" __attribute__((used,visibility("default"))) inline void sky_pc_report_frame_time(float milliseconds) {
    if(milliseconds>0.0f && milliseconds<1000.0f)SkyPc::frame_time_ms.store(milliseconds,std::memory_order_relaxed);
}
extern "C" __attribute__((used,visibility("default"))) inline float sky_pc_frame_time() {return SkyPc::frame_time_ms.load(std::memory_order_relaxed);}
// For the renderer's present pacing: the period the guest is paced at (0: uncapped) and the
// display refresh period (0: unknown).
extern "C" __attribute__((used,visibility("default"))) inline long long sky_pc_frame_period_ns() {
    return SkyPc::frame_period_ns(SkyPc::frame_limit.load(std::memory_order_relaxed));
}
extern "C" __attribute__((used,visibility("default"))) inline long long sky_pc_display_refresh_ns() {
    return SkyPc::display_refresh_ns.load(std::memory_order_relaxed);
}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_frame_limit() { return SkyPc::frame_limit.load(std::memory_order_relaxed); }
extern "C" __attribute__((used,visibility("default"))) inline void sky_pc_set_frame_limit(int fps) {
    std::lock_guard guard(SkyPc::frame_policy_mutex);
    // Explicit user changes take ownership until automatic mode is re-enabled.
    const auto* allow=std::getenv("SKY_ALLOW_60");
    if(fps==30 || (fps==60 && allow && !std::strcmp(allow,"1"))) {
        SkyPc::automatic.store(false);
        SkyPc::manual_limit.store(fps);
        SkyPc::apply_frame_limit(fps);
    }
}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_auto_available() {return SkyPc::automatic_available();}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_frame_policy() {return SkyPc::automatic.load()?1:0;}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_set_frame_policy(int automatic) {
    std::lock_guard guard(SkyPc::frame_policy_mutex);
    if((automatic!=0 && automatic!=1) || (automatic && !SkyPc::automatic_available()))return 0;
    SkyPc::automatic.store(automatic!=0);
    // Opening the drawer or re-enabling auto always starts conservatively.
    // The next game-state sample may qualify a return to 60.
    const int manual=SkyPc::manual_limit.load();
    SkyPc::apply_frame_limit(automatic?30:manual);
    std::printf("{\"event\":\"pc-frame-policy\",\"mode\":\"%s\"}\n",automatic?"auto":"manual");
    return 1;
}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_controller_layout() {return SkyPc::controller_layout.load();}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_set_controller_layout(int value) {
    if(value<0 || value>1)return 0;
    SkyPc::controller_layout.store(value);return 1;
}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_controller_glyphs() {return SkyPc::controller_glyphs.load();}
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_set_controller_glyphs(int value) {
    if(value<0 || value>3)return 0;
    SkyPc::controller_glyphs.store(value);return 1;
}
// The UI sends only fixed-choice integers. The launcher validates the resulting
// request again and applies it to a fresh, private session after orderly exit.
extern "C" __attribute__((used,visibility("default"))) inline int sky_pc_save_settings(int resolution, int quality, int fullscreen, int counter) {
    const auto& resolutions = SkyPc::resolutions;
    constexpr const char* qualities[]{"performance","balanced","high"};
    const auto* path = std::getenv("SKY_PC_SETTINGS_REQUEST");
    if (!path || resolution < 0 || resolution >= int(resolutions.size()) || quality < 0 || quality >= 3 ||
        (fullscreen != 0 && fullscreen != 1) || (counter != 0 && counter != 1)) return 0;
    std::lock_guard guard(SkyPc::frame_policy_mutex);
    const std::string temporary = std::string(path) + ".tmp";
    auto* file = std::fopen(temporary.c_str(),"wx");
    if (!file) return 0;
    const bool wrote = std::fprintf(file,
        "{\"resolution\":\"%s\",\"quality\":\"%s\",\"fullscreen\":%s,\"fps_counter\":%s,\"frame_limit\":%d,\"frame_policy\":\"%s\",\"portal_volume\":%d,\"controller_layout\":\"%s\",\"controller_glyphs\":\"%s\"}\n",
        resolutions[resolution].name,qualities[quality],fullscreen?"true":"false",counter?"true":"false",SkyPc::manual_limit.load(),SkyPc::automatic.load()?"auto":"manual",sky_portal_volume?sky_portal_volume():30,SkyPc::controller_layout.load()?"keyboard-and-pad":"auto",
        std::array<const char*,4>{"auto","playstation","xbox","nintendo"}[SkyPc::controller_glyphs.load()]) > 0;
    const bool closed = std::fclose(file) == 0;
    if (!wrote || !closed || std::rename(temporary.c_str(),path)) { std::remove(temporary.c_str()); return 0; }
    return 1;
}

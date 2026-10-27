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
    const auto period = std::chrono::nanoseconds(1'000'000'000 / fps);
    const auto now = Clock::now();
    if (previous != fps || now - deadline > period) deadline = now;
    previous = fps;
    if (deadline > now) std::this_thread::sleep_until(deadline);
    deadline += period;
}
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
    constexpr const char* resolutions[]{"720p","900p","1080p","1440p","1600p","2160p"};
    constexpr const char* qualities[]{"performance","balanced","high"};
    const auto* path = std::getenv("SKY_PC_SETTINGS_REQUEST");
    if (!path || resolution < 0 || resolution >= 6 || quality < 0 || quality >= 3 ||
        (fullscreen != 0 && fullscreen != 1) || (counter != 0 && counter != 1)) return 0;
    std::lock_guard guard(SkyPc::frame_policy_mutex);
    const std::string temporary = std::string(path) + ".tmp";
    auto* file = std::fopen(temporary.c_str(),"wx");
    if (!file) return 0;
    const bool wrote = std::fprintf(file,
        "{\"resolution\":\"%s\",\"quality\":\"%s\",\"fullscreen\":%s,\"fps_counter\":%s,\"frame_limit\":%d,\"frame_policy\":\"%s\",\"portal_volume\":%d,\"controller_layout\":\"%s\",\"controller_glyphs\":\"%s\"}\n",
        resolutions[resolution],qualities[quality],fullscreen?"true":"false",counter?"true":"false",SkyPc::manual_limit.load(),SkyPc::automatic.load()?"auto":"manual",sky_portal_volume?sky_portal_volume():30,SkyPc::controller_layout.load()?"keyboard-and-pad":"auto",
        std::array<const char*,4>{"auto","playstation","xbox","nintendo"}[SkyPc::controller_glyphs.load()]) > 0;
    const bool closed = std::fclose(file) == 0;
    if (!wrote || !closed || std::rename(temporary.c_str(),path)) { std::remove(temporary.c_str()); return 0; }
    return 1;
}

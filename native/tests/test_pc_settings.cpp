// SPDX-License-Identifier: GPL-3.0-or-later
#include "../pc_settings.hpp"
#include <stdexcept>
#include "../platform/host_compat.hpp"
#include <filesystem>
#include <unistd.h>
#include <fstream>
#include <iterator>

int main() {
    const auto check=[](bool v){if(!v)throw std::runtime_error("PC settings contract failed");};
    // Frame periods lock to whole display refreshes when within 1% of the request.
    check(SkyPc::frame_period_ns(30)==33'333'333 && SkyPc::frame_period_ns(0)==0);
    SkyPc::display_refresh_ns.store(4'167'709); // 239.94 Hz
    check(SkyPc::frame_period_ns(30)==8*4'167'709 && SkyPc::frame_period_ns(60)==4*4'167'709);
    SkyPc::display_refresh_ns.store(13'333'333); // 75 Hz: 30 FPS is not a whole number of refreshes
    check(SkyPc::frame_period_ns(30)==33'333'333);
    SkyPc::display_refresh_ns.store(16'683'350); // 59.94 Hz
    check(SkyPc::frame_period_ns(30)==2*16'683'350);
    SkyPc::display_refresh_ns.store(0);
    check(sky_pc_set_fps_counter(0) && sky_pc_fps_counter()==0);
    check(!sky_pc_set_fps_counter(2) && sky_pc_fps_counter()==0);
    check(sky_pc_set_fps_counter(1) && sky_pc_fps_counter()==1);
    sky_pc_report_frame_time(16.0f);check(sky_pc_frame_time()==16.0f);
    sky_pc_report_frame_time(-1.0f);sky_pc_report_frame_time(1000.0f);check(sky_pc_frame_time()==16.0f);
    SkyHost::unset_environment("SKY_AUTO_FRAME_POLICY_AVAILABLE");
    check(!sky_pc_set_frame_policy(1));check(!sky_pc_set_frame_policy(2));
    SkyHost::unset_environment("SKY_ALLOW_60");
    sky_pc_set_frame_limit(30); sky_pc_set_frame_limit(60);
    check(sky_pc_frame_limit()==30);
    SkyHost::set_environment("SKY_ALLOW_60","1");
    sky_pc_set_frame_limit(60); check(sky_pc_frame_limit()==60);
    SkyPc::automatic.store(true);
    SkyPc::apply_frame_limit(30);check(SkyPc::automatic.load() && sky_pc_frame_limit()==30);
    sky_pc_set_frame_limit(60);check(!SkyPc::automatic.load() && sky_pc_frame_limit()==60);
    sky_pc_set_frame_limit(120); check(sky_pc_frame_limit()==60);
    SkyHost::set_environment("SKY_AUTO_FRAME_POLICY_AVAILABLE","1");
    check(sky_pc_auto_available());check(sky_pc_set_frame_policy(1));
    check(sky_pc_frame_policy()==1 && sky_pc_frame_limit()==30);
    SkyPc::apply_automatic_limit(60);check(sky_pc_frame_limit()==60);
    sky_pc_set_frame_limit(30);check(sky_pc_frame_policy()==0);
    SkyPc::apply_automatic_limit(60);check(sky_pc_frame_limit()==30);
    sky_pc_set_frame_limit(60);check(sky_pc_set_frame_policy(1));
    check(sky_pc_frame_limit()==30 && SkyPc::manual_limit.load()==60);
    const std::string path=(std::filesystem::temp_directory_path()/("sky-pc-settings-"+std::to_string(getpid())+".json")).string();
    SkyHost::set_environment("SKY_PC_SETTINGS_REQUEST",path.c_str());
    check(!sky_pc_save_settings(99,0,0,0));check(!sky_pc_save_settings(8,0,0,0));
    check(access(path.c_str(),F_OK)!=0);
    check(!sky_pc_set_controller_layout(2));check(sky_pc_set_controller_layout(1));
    check(sky_pc_controller_layout()==1);
    check(!sky_pc_set_controller_glyphs(4));check(!sky_pc_set_controller_glyphs(-1));
    check(sky_pc_set_controller_glyphs(3) && sky_pc_controller_glyphs()==3);
    check(sky_pc_save_settings(6,0,1,0));
    std::ifstream file(path);
    const std::string contents((std::istreambuf_iterator<char>(file)),{});
    check(contents.find("nintendo")!=contents.npos);
    check(contents.find("keyboard-and-pad")!=contents.npos);
    check(contents.find("1600p")!=contents.npos && contents.find("performance")!=contents.npos);
    check(contents.find("\"frame_limit\":60")!=contents.npos);
    check(contents.find("\"frame_policy\":\"auto\"")!=contents.npos);
    check(sky_pc_set_frame_policy(0));check(sky_pc_frame_policy()==0 && sky_pc_frame_limit()==60);
    unlink(path.c_str());
    return 0;
}

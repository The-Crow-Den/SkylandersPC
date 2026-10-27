// SPDX-License-Identifier: GPL-3.0-or-later
#include "../pc_settings.hpp"
#include <stdexcept>
#include <unistd.h>
#include <fstream>
#include <iterator>

int main() {
    const auto check=[](bool v){if(!v)throw std::runtime_error("PC settings contract failed");};
    unsetenv("SKY_AUTO_FRAME_POLICY_AVAILABLE");
    check(!sky_pc_set_frame_policy(1));check(!sky_pc_set_frame_policy(2));
    unsetenv("SKY_ALLOW_60");
    sky_pc_set_frame_limit(30); sky_pc_set_frame_limit(60);
    check(sky_pc_frame_limit()==30);
    setenv("SKY_ALLOW_60","1",1);
    sky_pc_set_frame_limit(60); check(sky_pc_frame_limit()==60);
    SkyPc::automatic.store(true);
    SkyPc::apply_frame_limit(30);check(SkyPc::automatic.load() && sky_pc_frame_limit()==30);
    sky_pc_set_frame_limit(60);check(!SkyPc::automatic.load() && sky_pc_frame_limit()==60);
    sky_pc_set_frame_limit(120); check(sky_pc_frame_limit()==60);
    setenv("SKY_AUTO_FRAME_POLICY_AVAILABLE","1",1);
    check(sky_pc_auto_available());check(sky_pc_set_frame_policy(1));
    check(sky_pc_frame_policy()==1 && sky_pc_frame_limit()==30);
    SkyPc::apply_automatic_limit(60);check(sky_pc_frame_limit()==60);
    sky_pc_set_frame_limit(30);check(sky_pc_frame_policy()==0);
    SkyPc::apply_automatic_limit(60);check(sky_pc_frame_limit()==30);
    sky_pc_set_frame_limit(60);check(sky_pc_set_frame_policy(1));
    check(sky_pc_frame_limit()==30 && SkyPc::manual_limit.load()==60);
    const std::string path="/tmp/sky-pc-settings-"+std::to_string(getpid())+".json";
    setenv("SKY_PC_SETTINGS_REQUEST",path.c_str(),1);
    check(!sky_pc_save_settings(99,0,0,0));
    check(access(path.c_str(),F_OK)!=0);
    check(!sky_pc_set_controller_layout(2));check(sky_pc_set_controller_layout(1));
    check(sky_pc_controller_layout()==1);
    check(!sky_pc_set_controller_glyphs(4));check(!sky_pc_set_controller_glyphs(-1));
    check(sky_pc_set_controller_glyphs(3) && sky_pc_controller_glyphs()==3);
    check(sky_pc_save_settings(4,0,1,0));
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

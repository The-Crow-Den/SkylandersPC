// SPDX-License-Identifier: GPL-3.0-or-later
#include "pc_overlay_bridge.hpp"
#include "portal_library.hpp"
#include "pc_settings.hpp"
#include <SDL3/SDL.h>
#include <array>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <thread>
#include <vector>
#include <algorithm>
#include <sys/stat.h>
#include <unistd.h>
extern "C" int sky_portal_action(int,int);
extern "C" int sky_portal_volume();
extern "C" void sky_portal_set_volume(int);
namespace {
namespace fs=std::filesystem;
std::atomic<bool> connected{false},visible{false};
std::mutex geometry_mutex,input_mutex;
std::array<int,4> window_geometry{0,0,1280,720};
std::vector<int> input;
std::string quote(const char* text){std::ostringstream out;out<<'"';for(const unsigned char ch:std::string(text?text:"")){if(ch=='"'||ch=='\\')out<<'\\'<<char(ch);else if(ch<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<unsigned(ch)<<std::dec;else out<<char(ch);}out<<'"';return out.str();}
bool regular(const fs::path& path,std::uintmax_t limit){std::error_code ec;return !fs::is_symlink(path,ec)&&fs::is_regular_file(path,ec)&&fs::file_size(path,ec)<=limit&&!ec;}
std::string read(const fs::path& path,std::uintmax_t limit){if(!regular(path,limit))return {};std::ifstream file(path,std::ios::binary);return {(std::istreambuf_iterator<char>(file)),{}};}
bool owner_directory(const fs::path& path){struct stat info{};std::error_code ec;return fs::weakly_canonical(path,ec)==path&&!ec&&lstat(path.c_str(),&info)==0&&S_ISDIR(info.st_mode)&&info.st_uid==getuid()&&(info.st_mode&077)==0;}
std::string snapshot(unsigned long long sequence,const std::vector<int>& keys){
    std::array<int,4> geometry;{std::lock_guard lock(geometry_mutex);geometry=window_geometry;}
    std::ostringstream out;out<<"{\"version\":1,\"pid\":"<<getpid()<<",\"visible\":"<<(visible?"true":"false")<<",\"geometry\":["<<geometry[0]<<','<<geometry[1]<<','<<geometry[2]<<','<<geometry[3]<<"],\"inputSequence\":"<<sequence<<",\"keys\":[";
    for(unsigned i=0;i<keys.size();++i){if(i)out<<',';out<<keys[i];}out<<']';
    if(visible){out<<",\"collections\":{";
        for(int kind=0;kind<4;++kind){if(kind)out<<',';out<<'"'<<kind<<"\":[";const int count=std::min(1024,sky_portal_count(kind));
            for(int i=0;i<count;++i){if(i)out<<',';out<<"{\"index\":"<<i<<",\"name\":"<<quote(sky_portal_name(kind,i))<<",\"detail\":"<<quote(sky_portal_detail(kind,i))<<",\"state\":"<<sky_portal_state(kind,i)<<",\"portrait\":"<<sky_portal_portrait(kind,i);
                if(kind==1)out<<",\"element\":"<<sky_portal_trap_element(i)<<",\"capture\":"<<sky_portal_trap_capture(i);out<<'}';}out<<']';}
        out<<"},\"elements\":[";
        for(int i=0;i<sky_portal_trap_element_count();++i){if(i)out<<',';out<<"{\"index\":"<<i<<",\"name\":"<<quote(sky_portal_trap_element_name(i))<<",\"portrait\":"<<sky_portal_element_portrait(i)<<'}';}
        out<<"],\"creation\":[";
        for(int i=0;i<sky_portal_creation_count();++i){if(i)out<<',';out<<"{\"index\":"<<i<<",\"name\":"<<quote(sky_portal_creation_name(i))<<",\"kind\":"<<sky_portal_creation_kind(i)<<",\"portrait\":"<<sky_portal_creation_portrait(i)<<'}';}
        out<<"],\"status\":"<<quote(sky_portal_status())<<",\"settings\":{\"resolution\":"<<(std::getenv("SKY_PC_RESOLUTION")?std::atoi(std::getenv("SKY_PC_RESOLUTION")):2)<<",\"quality\":"<<(std::getenv("SKY_PC_QUALITY")?std::atoi(std::getenv("SKY_PC_QUALITY")):1)<<",\"fullscreen\":"<<(std::getenv("SKY_FULLSCREEN")&&!std::strcmp(std::getenv("SKY_FULLSCREEN"),"1")?"true":"false")<<",\"counter\":true,\"framePolicy\":"<<(sky_pc_frame_policy()?0:sky_pc_frame_limit()==60?2:1)<<",\"autoAvailable\":"<<(sky_pc_auto_available()?"true":"false")<<",\"allow60\":"<<(std::getenv("SKY_ALLOW_60")&&!std::strcmp(std::getenv("SKY_ALLOW_60"),"1")?"true":"false")<<",\"layout\":"<<sky_pc_controller_layout()<<",\"glyphs\":"<<sky_pc_controller_glyphs()<<",\"activeGlyphs\":"<<quote(std::getenv("SKY_ACTIVE_CONTROLLER_GLYPHS")?std::getenv("SKY_ACTIVE_CONTROLLER_GLYPHS"):"playstation")<<",\"volume\":"<<sky_portal_volume()<<'}';
    }out<<'}';return out.str();
}
void command(const std::string& data){
    std::istringstream stream(data);std::string verb;stream>>verb;
    if(verb=="portal"){int action=-1,index=-1;if(stream>>action>>index && action>=0&&action<=12&&index>=0&&index<2048)sky_portal_action(action,index);}
    else if(verb=="close")sky_portal_action(20,0);
    else if(verb=="volume"){int n=-1;if(stream>>n&&n>=0&&n<=100)sky_portal_set_volume(n);}
    else if(verb=="fps"){int n=-1;if(stream>>n){if(n==0)sky_pc_set_frame_policy(1);else if(n==1)sky_pc_set_frame_limit(30);else if(n==2)sky_pc_set_frame_limit(60);}}
    else if(verb=="import"){int player=-1;stream>>player;std::string path;std::getline(stream,path);std::getline(stream,path);if(player>=0&&player<2&&!path.empty()&&path.size()<4096&&path.find('\0')==std::string::npos)PortalLibrary::import_character(path.c_str(),true,static_cast<unsigned>(player));}
    else if(verb=="settings"){
        int resolution=-1,quality=-1,fullscreen=-1,counter=-1,layout=-1,glyphs=-1;
        if(stream>>resolution>>quality>>fullscreen>>counter>>layout>>glyphs&&resolution>=0&&resolution<6&&quality>=0&&quality<3&&(fullscreen==0||fullscreen==1)&&(counter==0||counter==1)&&layout>=0&&layout<2&&glyphs>=0&&glyphs<4){
            sky_pc_set_controller_layout(layout);sky_pc_set_controller_glyphs(glyphs);
            if(sky_pc_save_settings(resolution,quality,fullscreen,counter))sky_portal_action(21,0);
        }
    }
}
class Worker {
    std::jthread thread;
public:
    explicit Worker(fs::path directory):thread([directory=std::move(directory)](std::stop_token stop){
        std::string previous;unsigned long long sequence=0;auto last=std::chrono::steady_clock::time_point{};
        while(!stop.stop_requested()){
            if(!owner_directory(directory)){connected=false;return;}
            std::error_code ec;const auto heartbeat=directory/"heartbeat";
            const bool alive=regular(heartbeat,64)&&fs::file_time_type::clock::now()-fs::last_write_time(heartbeat,ec)<std::chrono::seconds(4)&&!ec;
            connected=alive;
            std::vector<fs::path> requests;
            for(const auto& entry:fs::directory_iterator(directory,ec)){const auto name=entry.path().filename().string();if(name.starts_with("command-")&&name.ends_with(".req")&&name.size()<48&&regular(entry.path(),8192))requests.push_back(entry.path());}
            std::sort(requests.begin(),requests.end());if(requests.size()>32)requests.resize(32);
            if(alive)for(const auto& path:requests){const auto data=read(path,8192);if(!data.empty())command(data);fs::remove(path,ec);}
            const auto now=std::chrono::steady_clock::now();
            if(now-last>=std::chrono::milliseconds(150)){
                last=now;std::vector<int> keys;{std::lock_guard lock(input_mutex);keys.swap(input);}if(!keys.empty())++sequence;
                const auto state=snapshot(sequence,keys);
                if(state!=previous){const auto temporary=directory/"state.tmp";if(!fs::is_symlink(temporary,ec)){
                    std::ofstream file(temporary,std::ios::binary|std::ios::trunc);file<<state;file.close();if(file){fs::rename(temporary,directory/"state.json",ec);if(!ec)previous=state;}}
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(40));
        }
        connected=false;
    }){}
};
}
namespace PcOverlay {
void start(){const auto* value=std::getenv("SKY_PC_OVERLAY_DIR");if(!value||!*value)return;const fs::path path(value);if(!path.is_absolute()||!owner_directory(path))return;static Worker worker(path);}
void geometry(int x,int y,int width,int height){if(width<100||height<100||width>16384||height>16384)return;std::lock_guard lock(geometry_mutex);window_geometry={x,y,width,height};}
}
extern "C" int sky_pc_external_menu(){return connected?1:0;}
extern "C" void sky_pc_menu_visibility(int shown){visible=shown!=0;}
extern "C" int sky_pc_menu_gamepad(int key){if(!connected||!visible||!key||std::abs(key)>9)return 0;std::lock_guard lock(input_mutex);if(input.size()<32)input.push_back(key);return 1;}

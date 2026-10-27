// SPDX-License-Identifier: GPL-3.0-or-later
#include "virtual_portal.hpp"
#include <vector>
#include <algorithm>
#include "../portal_library.hpp"
#include "runtime/cemu_portal.hpp"
#include <libusb.h>
#include <array>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <iomanip>
int main() {
    try {
        using U=std::uint64_t;
        setenv("SKY_VIRTUAL_PORTAL","1",1);
        const auto check=[](bool ok){if(!ok)throw std::runtime_error("virtual portal contract failed");};
        const auto ptr=[](auto* p){return reinterpret_cast<U>(p);};
        const auto call=[](const char* nid,std::array<U,12> args={}){
            return VirtualPortal::call(std::string(nid)+"#libSceUsbd#libSceUsbd",args.data());
        };
        check(trapteam::cemu_portal_self_test());
        check(!VirtualPortal::supports("TOhg7P6kTH4#wrong#libSceUsbd"));
        check(call("TOhg7P6kTH4")==0);
        libusb_device** devices=nullptr;
        check(call("8qB9Ar4P5nc",{ptr(&devices)})==1 && devices[0] && !devices[1]);
        libusb_device_descriptor descriptor{};
        check(call("bhomgbiQgeo",{ptr(devices[0]),ptr(&descriptor)})==0);
        check(descriptor.idVendor==0x1430 && descriptor.idProduct==0x150);
        libusb_config_descriptor* config=nullptr;
        check(call("Dkm5qe8j3XE",{ptr(devices[0]),0,ptr(&config)})==0);
        check(config->interface[0].altsetting[0].endpoint[0].bEndpointAddress==0x81);
        check(call("Hvd3S--n25w",{ptr(config)})==0);
        libusb_device_handle* handle=nullptr;
        check(call("VJ6oMq-Di2U",{ptr(devices[0]),ptr(&handle)})==0);
        check(call("RRKFcKQ1Ka4",{ptr(handle),0x21,10,0,0,0,0,100})==0);
        check(call("RRKFcKQ1Ka4",{ptr(handle),0x21,11,1,0,0,0,100})==0);
        check(call("RRKFcKQ1Ka4",{ptr(handle),0x21,9,0x200,0,0,2,100})==0x80240002);
        std::array<unsigned char,64> command{'R'},response{};
        check(call("RRKFcKQ1Ka4",{ptr(handle),0x21,9,0x200,0,ptr(command.data()),1,100})==1);
        auto* transfer=reinterpret_cast<libusb_transfer*>(call("0ktE1PhzGFU"));
        check(transfer);
        check(call("t3J5pXxhJlI",{ptr(transfer),ptr(handle),0x81,ptr(response.data()),64,0,0,50})==0);
        check(call("L0EHgZZNVas",{ptr(transfer)})==0);
        check(call("L0EHgZZNVas",{ptr(transfer)})==0x80240006);
        check(call("EkqGLxWC-S0")==0);
        check(transfer->status==LIBUSB_TRANSFER_COMPLETED && transfer->actual_length==64 && response[0]=='R');
        check(call("-sgi7EeLSO8",{ptr(transfer)})==0);
        check(call("EQ6SCLMqzkM",{ptr(devices),1})==0);
        check(call("Fq6+0Fm55xU")==0);
        check(call("TOhg7P6kTH4")==0);
        auto* extra=reinterpret_cast<libusb_transfer*>(call("0ktE1PhzGFU",{1}));
        check(extra && extra->num_iso_packets==0);
        check(call("-sgi7EeLSO8",{ptr(extra)})==0);
        const auto old=std::filesystem::current_path();
        const auto temp=std::filesystem::temp_directory_path()/("sky-trap-test-"+std::to_string(ptr(&descriptor)));
        std::filesystem::create_directories(temp);std::filesystem::current_path(temp);
        struct Cleanup{std::filesystem::path old,temp;~Cleanup(){VirtualPortal::remove();std::filesystem::current_path(old);std::filesystem::remove_all(temp);}} cleanup{old,temp};
        std::array<unsigned char,1024> character{},trap{};character[0]=1;trap[0]=2;trap[0x10]=211;
        {std::ofstream f("character.sky",std::ios::binary);f.write(reinterpret_cast<const char*>(character.data()),character.size());}
        {std::ofstream f("trap.sky",std::ios::binary);f.write(reinterpret_cast<const char*>(trap.data()),trap.size());}
        check(VirtualPortal::load("character.sky"));
        check(!VirtualPortal::load_trap("character.sky"));
        check(VirtualPortal::load_trap("trap.sky"));
        VirtualPortal::remove_trap();
        std::array<unsigned char,64> status{};
        for(unsigned i=0;i<8;++i)status=trapteam::cemu_portal_read();
        check(status[0]=='S' && (status[1]&3)==1 && (status[1]&12)==0);
        PortalLibrary::initialize(nullptr);
        check(sky_portal_count(1)==46 && !PortalLibrary::select(1,-1));
        check(PortalLibrary::select(1,0));
        check((sky_portal_state(1,0)&3)==3);
        auto find_trap=[&] {
            for(unsigned i=0;i<64;++i)trapteam::cemu_portal_read();
            for(unsigned slot=0;slot<16;++slot) {
                const std::array<unsigned char,3> query{'Q',static_cast<unsigned char>(slot),1};
                check(trapteam::cemu_portal_command(query));
                const auto reply=trapteam::cemu_portal_read();
                if(reply[0]=='Q'&&(reply[1]&0x10)&&reply[3]==211)return slot;
            }
            throw std::runtime_error("managed trap missing");
        };
        const auto slot=find_trap();
        std::array<unsigned char,19> write{'W',static_cast<unsigned char>(slot),10};
        write[3]=0x5a;write[4]=0xa5;
        check(trapteam::cemu_portal_command(write));trapteam::cemu_portal_read();
        check(PortalLibrary::select(1,1));
        check(!(sky_portal_state(1,0)&2)&&(sky_portal_state(1,1)&2));
        check(PortalLibrary::select(1,0));
        const auto restored=find_trap();
        const std::array<unsigned char,3> query{'Q',static_cast<unsigned char>(restored),10};
        check(trapteam::cemu_portal_command(query));const auto saved=trapteam::cemu_portal_read();
        check(saved[3]==0x5a && saved[4]==0xa5);
        // Use the linked Cemu factory, preserving the inserted trap and every
        // existing file. Verify the generated tag independently of its name.
        int water=-1;
        const auto creation_count=sky_portal_creation_count();
        check(creation_count>32);
        for(int i=0;i<creation_count;++i) {
            unsigned id=0,variant=0;
            check(VirtualPortal::creation_identity(static_cast<unsigned>(i),id,variant));
            check(variant<0x4000 && !(id>=210 && id<=220) && !(id>=1000 && id<=2015));
            if(std::string(sky_portal_creation_name(i))=="Gill Grunt")water=i;
        }
        check(water>=0 && !PortalLibrary::create_character(-1) && !PortalLibrary::create_character(creation_count));
        const auto before_count=sky_portal_count(0);
        check(PortalLibrary::create_character(water));
        check(sky_portal_count(0)==before_count+1 && (sky_portal_state(0,before_count)&2));
        check(sky_portal_state(1,0)&2);
        std::filesystem::path generated;
        for(const auto& entry:std::filesystem::directory_iterator("out/portal-library/characters"))
            if(entry.is_regular_file())generated=entry.path();
        check(!generated.empty());
        std::array<unsigned char,1024> made{};
        {std::ifstream f(generated,std::ios::binary);check(bool(f.read(reinterpret_cast<char*>(made.data()),made.size())));}
        check(made[0x10]==14 && made[0x11]==0 && made[0x1c]==0 && made[0x1d]==0);
        check(made[4]==(made[0]^made[1]^made[2]^made[3]));
        // A collection tag chosen as the starting figure is used in place, not copied.
        check(PortalLibrary::import_character(generated.c_str(),false));
        check(sky_portal_count(0)==before_count+1);
        unsigned crc=0xffff;
        for(unsigned i=0;i<0x1e;++i) {
            crc^=unsigned(made[i])<<8;
            for(unsigned bit=0;bit<8;++bit)crc=((crc<<1)^((crc&0x8000)?0x1021:0))&0xffff;
        }
        check(crc==(made[0x1e]|(unsigned(made[0x1f])<<8)));
        check(!VirtualPortal::create_blank(generated.c_str(),14,0));
        const auto redirected=std::filesystem::path("redirected.sky");
        std::filesystem::create_symlink(generated,redirected);
        check(!VirtualPortal::create_blank(redirected.c_str(),14,0));
        std::array<unsigned char,1024> unchanged{};
        {std::ifstream f(generated,std::ios::binary);check(bool(f.read(reinterpret_cast<char*>(unchanged.data()),unchanged.size())));}
        check(made==unchanged);
        check(!VirtualPortal::create_blank("bad.sky",65536,0));
        check(!VirtualPortal::create_blank("bad.sky",14,65536));
        // Independent player and item slots must not eject each other or the
        // trap. Two players cannot concurrently write the same figure file.
        check(!PortalLibrary::select(3,before_count));
        check(PortalLibrary::create_character(water,true,1));
        const auto second=sky_portal_count(0)-1;
        check(PortalLibrary::select(3,second));
        check((sky_portal_state(3,second)&2) && (sky_portal_state(0,before_count)&2));
        int healing=-1;
        for(int i=0;i<creation_count;++i)if(std::string(sky_portal_creation_name(i))=="Healing Elixir")healing=i;
        check(healing>=0 && sky_portal_creation_kind(healing)==2);
        check(PortalLibrary::create_character(healing));
        check(sky_portal_count(2)==1 && (sky_portal_state(2,0)&2));
        check((sky_portal_state(3,second)&2) && (sky_portal_state(0,before_count)&2) && (sky_portal_state(1,0)&2));
        auto present_ids=[&] {
            for(unsigned i=0;i<64;++i)trapteam::cemu_portal_read();
            std::vector<unsigned> ids;
            for(unsigned slot=0;slot<16;++slot) {
                const std::array<unsigned char,3> q{'Q',static_cast<unsigned char>(slot),1};
                check(trapteam::cemu_portal_command(q));const auto reply=trapteam::cemu_portal_read();
                if(reply[0]=='Q' && (reply[1]&0x10))ids.push_back(reply[3]|(unsigned(reply[4])<<8));
            }
            std::sort(ids.begin(),ids.end());return ids;
        };
        check(present_ids()==std::vector<unsigned>({14,14,202,211}));
        PortalLibrary::remove(0);check(sky_portal_state(1,0)&2);
        check(present_ids()==std::vector<unsigned>({14,202,211}));
        PortalLibrary::remove(3);check(present_ids()==std::vector<unsigned>({202,211}));
        PortalLibrary::remove(2);check(present_ids()==std::vector<unsigned>({211}));
        // Element buttons reuse an empty tag, never clobber a previous capture.
        const auto trap_count=sky_portal_count(1);check(PortalLibrary::select_empty_trap(0));
        check(sky_portal_count(1)==trap_count+1);const auto empty_index=sky_portal_count(1)-1;
        check(sky_portal_trap_capture(empty_index)==0 && sky_portal_trap_element(empty_index)==0);
        check(PortalLibrary::select_empty_trap(0) && sky_portal_count(1)==trap_count+1);
        check(!PortalLibrary::select_empty_trap(-1) && !PortalLibrary::select_empty_trap(11));
        PortalLibrary::remove(1);
        std::filesystem::path empty_template;
        for(const auto& entry:std::filesystem::directory_iterator("out/portal-library/traps"))if(entry.path().filename().string().starts_with("element-"))empty_template=entry.path();
        check(!empty_template.empty());std::array<unsigned char,1024> original{};
        {std::ifstream f(empty_template,std::ios::binary);check(bool(f.read(reinterpret_cast<char*>(original.data()),original.size())));}
        std::uint64_t fingerprint=14695981039346656037ull;for(auto byte:original){fingerprint^=byte;fingerprint*=1099511628211ull;}
        std::ostringstream working;working<<"out/figures/import-"<<std::hex<<std::setw(16)<<std::setfill('0')<<fingerprint<<".sky";
        auto progressed=original;progressed[0x80]=0x7f;
        {std::ofstream f(working.str(),std::ios::binary);f.write(reinterpret_cast<const char*>(progressed.data()),progressed.size());}
        // Even unidentified nonblank progress must never be reused as empty.
        check(PortalLibrary::select_empty_trap(0) && sky_portal_count(1)==trap_count+2);
        check(sky_portal_trap_capture(empty_index)<0);
        std::array<unsigned char,1024> preserved{};
        {std::ifstream f(working.str(),std::ios::binary);check(bool(f.read(reinterpret_cast<char*>(preserved.data()),preserved.size())));}
        check(preserved==progressed);
        {std::ifstream f(empty_template,std::ios::binary);check(bool(f.read(reinterpret_cast<char*>(preserved.data()),preserved.size())));}
        check(preserved==original);
        PortalLibrary::remove(1);
        // Audio OUT packets are raw PCM, not HID commands, and reach the sink unchanged.
        static unsigned speaker_bytes=0;
        VirtualPortal::bind_audio([](const unsigned char* data,std::size_t size){if(size==64&&data[1]==1)speaker_bytes+=static_cast<unsigned>(size);});
        check(call("TOhg7P6kTH4")==0);
        check(call("vrQXYRo1Gwk",{0x1430,0x150})==ptr(handle));
        auto* audio=reinterpret_cast<libusb_transfer*>(call("0ktE1PhzGFU"));check(audio);
        std::array<unsigned char,64> pcm{};for(unsigned i=0;i<pcm.size();++i)pcm[i]=static_cast<unsigned char>(i);
        check(call("t3J5pXxhJlI",{ptr(audio),ptr(handle),2,ptr(pcm.data()),64,0,0,50})==0);
        check(call("L0EHgZZNVas",{ptr(audio)})==0);check(call("EkqGLxWC-S0")==0);
        check(audio->status==LIBUSB_TRANSFER_COMPLETED&&audio->actual_length==64&&speaker_bytes==64);
        check(call("-sgi7EeLSO8",{ptr(audio)})==0);
        std::cout<<"Portal ownership, independent trap progress, and PCM routing passed\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}

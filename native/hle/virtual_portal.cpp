// SPDX-License-Identifier: GPL-3.0-or-later
#include "virtual_portal.hpp"
#include <stdexcept>
#include <atomic>
#ifdef SKY_CEMU_PORTAL
#include "runtime/cemu_portal.hpp"
#include "../thread_context.hpp"
#include <libusb.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>
#include <cstdio>
#include <fstream>
namespace {
using U = std::uint64_t;
struct Contract { std::string_view identity, name; };
constexpr Contract contracts[]{
#include "usb_contracts.inc"
};
std::mutex mutex;
bool initialized = false, opened = false, figures_loaded = false;
unsigned char device_token, handle_token;
auto* device = reinterpret_cast<libusb_device*>(&device_token);
auto* handle = reinterpret_cast<libusb_device_handle*>(&handle_token);
std::unordered_set<void**> lists;
std::unordered_set<libusb_transfer*> transfers;
std::deque<libusb_transfer*> pending;
std::vector<unsigned> figure_slots;
unsigned trap_slot=16,item_slot=16,vehicle_slot=16;
std::array<unsigned,2> player_slots{16,16};
// A Swap Force swapper is two tags on the portal at once: the top half sits in
// the player's slot and the bottom half in its partner slot.
std::array<unsigned,2> bottom_slots{16,16};
std::array<bool,2> player_is_top{false,false};
std::atomic<void(*)(const unsigned char*,std::size_t)> portal_audio{nullptr};
struct Configuration {
    libusb_config_descriptor config{};
    libusb_interface interface{};
    libusb_interface_descriptor alternate{};
    std::array<libusb_endpoint_descriptor,2> endpoints{};
    std::array<unsigned char,9> hid{9,0x21,0x11,1,0,1,0x22,0x1d,0};
    Configuration() {
        config.bLength=9; config.bDescriptorType=2; config.wTotalLength=41;
        config.bNumInterfaces=1; config.bConfigurationValue=1; config.bmAttributes=0x80; config.MaxPower=0xfa;
        config.interface=&interface; interface.altsetting=&alternate; interface.num_altsetting=1;
        alternate.bLength=9; alternate.bDescriptorType=4; alternate.bNumEndpoints=2; alternate.bInterfaceClass=3;
        alternate.endpoint=endpoints.data();
        alternate.extra=hid.data();alternate.extra_length=static_cast<int>(hid.size());
        for (unsigned i=0;i<2;++i) {
            endpoints[i].bLength=7; endpoints[i].bDescriptorType=5;
            endpoints[i].bEndpointAddress=i ? 2 : 0x81; endpoints[i].bmAttributes=3;
            endpoints[i].wMaxPacketSize=64; endpoints[i].bInterval=1;
        }
    }
};
std::unordered_set<Configuration*> configurations;
U error(unsigned value) { return 0x80240000u + value; }
std::string_view name(std::string_view identity) {
    for (const auto& item : contracts) if (identity==item.identity) return item.name;
    return {};
}
unsigned figure_id(const char* path) {
    std::ifstream input(path,std::ios::binary);
    std::array<unsigned char,2> id{};input.seekg(0x10);
    if(!input.read(reinterpret_cast<char*>(id.data()),id.size()))return 65536;
    return id[0]|(static_cast<unsigned>(id[1])<<8);
}
void eject(unsigned& slot) {
    if(slot<16){trapteam::cemu_portal_remove_figure(slot);std::erase(figure_slots,slot);slot=16;}
}
bool load_locked(const char* path,bool trap=false) {
    if(trap){
        const unsigned value=figure_id(path);
        if(value>65535)return false;
        if(value<210 || value>220){std::fprintf(stderr,"Portal: selected dump is not a Trap Team trap; character unchanged\n");return false;}
    }
    trapteam::PortalFigure figure; std::string failure;
    if (!trapteam::cemu_portal_load_figure(path,&figure,&failure)) {
        std::fprintf(stderr,"Portal figure import failed: %s\n",failure.c_str()); return false;
    }
    figure_slots.push_back(figure.slot);
    if(trap){
        if(trap_slot<16){trapteam::cemu_portal_remove_figure(trap_slot);std::erase(figure_slots,trap_slot);}
        trap_slot=figure.slot;
    }
    std::printf("Virtual portal: figure loaded in slot %u (private working copy)\n",figure.slot);
    return true;
}
int control(unsigned type,unsigned request,unsigned value,unsigned index,unsigned char* data,int length) {
    if (length<0 || length>4096 || (!data && length)) return -2;
    if (request==6 && (type&0x80) && (value>>8)==2)
        return trapteam::cemu_portal_descriptor(value>>8,value&255,index,{data,static_cast<std::size_t>(length)}) ? std::min(length,41) : -9;
    if (request==9 && !(type&0x80)) {
        static unsigned traced=0;
        if(length && (data[0]=='M' || data[0]=='A' || data[0]=='R') && traced++<16)
            std::printf("Virtual portal: command %c, %d bytes\n",data[0],length);
        return trapteam::cemu_portal_command({data,static_cast<std::size_t>(length)}) ? length : -9;
    }
    if (request==1 && (type&0x80)) {
        const auto report=trapteam::cemu_portal_read(); const auto size=std::min<int>(length,report.size());
        std::memcpy(data,report.data(),size);return size;
    }
    if ((request==10 || request==11) && !(type&0x80)) return length==0?0:-2; // HID idle/protocol have no payload.
    return -12;
}
}
#endif
namespace VirtualPortal {
void bind_audio(void(*sink)(const unsigned char*,std::size_t)) {
#ifdef SKY_CEMU_PORTAL
    portal_audio=sink;
#else
    (void)sink;
#endif
}

bool enabled() {
#ifdef SKY_CEMU_PORTAL
    const auto* value=std::getenv("SKY_VIRTUAL_PORTAL"); return value && std::strcmp(value,"1")==0;
#else
    return false;
#endif
}
bool supports(std::string_view identity) {
#ifdef SKY_CEMU_PORTAL
    return enabled() && !name(identity).empty();
#else
    (void)identity; return false;
#endif
}
unsigned stack_arguments(std::string_view identity) {
#ifdef SKY_CEMU_PORTAL
    const auto api=name(identity); return api=="ControlTransfer" || api=="FillInterruptTransfer" ? 2 : 0;
#else
    (void)identity; return 0;
#endif
}
bool load(const char* path) {return replace_player(path,0);}
extern "C" bool sky_portal_blank_adapter(const char*,unsigned,unsigned);
extern "C" const char* sky_portal_name_adapter(unsigned,unsigned);
extern "C" unsigned sky_portal_creation_count_adapter();
extern "C" const char* sky_portal_creation_name_adapter(unsigned);
extern "C" bool sky_portal_creation_identity_adapter(unsigned,unsigned*,unsigned*);
unsigned creation_count() {
#ifdef SKY_CEMU_PORTAL
    return sky_portal_creation_count_adapter();
#else
    return 0;
#endif
}
const char* creation_name(unsigned index) {
#ifdef SKY_CEMU_PORTAL
    return sky_portal_creation_name_adapter(index);
#else
    (void)index;return "";
#endif
}
bool creation_identity(unsigned index,unsigned& id,unsigned& variant) {
#ifdef SKY_CEMU_PORTAL
    return sky_portal_creation_identity_adapter(index,&id,&variant);
#else
    (void)index;(void)id;(void)variant;return false;
#endif
}
bool create_blank(const char* path,unsigned id,unsigned variant) {
#ifdef SKY_CEMU_PORTAL
    if(!path || id>65535 || variant>65535)return false;
    std::lock_guard guard(mutex);return sky_portal_blank_adapter(path,id,variant);
#else
    (void)path;(void)id;(void)variant;return false;
#endif
}
std::string figure_name(unsigned id,unsigned variant) {
#ifdef SKY_CEMU_PORTAL
    return sky_portal_name_adapter(id,variant);
#else
    (void)id;(void)variant;return "Skylander";
#endif
}
void remove_characters() {
#ifdef SKY_CEMU_PORTAL
    std::lock_guard guard(mutex);
    figures_loaded=true;
    for(auto slot:figure_slots)if(slot!=trap_slot && slot!=item_slot && slot!=vehicle_slot)trapteam::cemu_portal_remove_figure(slot);
    std::erase_if(figure_slots,[](unsigned slot){return slot!=trap_slot && slot!=item_slot && slot!=vehicle_slot;});
    player_slots=bottom_slots={16,16};player_is_top={false,false};
#endif
}
bool replace_character(const char* path) {return replace_player(path,0);}
namespace {
bool replace_managed(const char* path,unsigned& slot) {
#ifdef SKY_CEMU_PORTAL
    if(!enabled() || !path)return false;
    // Validate/import before ejecting an existing figure. Other slots and their
    // progress remain mounted, including the other player and accessory.
    if(!load_locked(path))return false;
    figures_loaded=true;
    const auto added=figure_slots.back();
    if(slot<16 && slot!=added) {
        trapteam::cemu_portal_remove_figure(slot);std::erase(figure_slots,slot);
    }
    slot=added;return true;
#else
    (void)path;(void)slot;return false;
#endif
}
}
bool replace_player(const char* path,unsigned player) {
#ifdef SKY_CEMU_PORTAL
    if(player>=player_slots.size() || !path)return false;
    std::lock_guard guard(mutex);
    const auto half=swapper_half(figure_id(path));
    if(half==SwapperHalf::bottom) {
        // A bottom half only pairs with a top half; a whole Skylander leaves.
        if(!replace_managed(path,bottom_slots[player]))return false;
        if(!player_is_top[player])eject(player_slots[player]);
        return true;
    }
    if(!replace_managed(path,player_slots[player]))return false;
    player_is_top[player]=half==SwapperHalf::top;
    if(!player_is_top[player])eject(bottom_slots[player]);
    return true;
#else
    (void)path;(void)player;return false;
#endif
}
bool replace_item(const char* path) {
#ifdef SKY_CEMU_PORTAL
    std::lock_guard guard(mutex);return replace_managed(path,item_slot);
#else
    (void)path;return false;
#endif
}
void remove_player(unsigned player) {
#ifdef SKY_CEMU_PORTAL
    if(player>=player_slots.size())return;
    std::lock_guard guard(mutex);
    eject(player_slots[player]);eject(bottom_slots[player]);player_is_top[player]=false;
#else
    (void)player;
#endif
}
void remove_swapper_half(unsigned player,bool bottom) {
#ifdef SKY_CEMU_PORTAL
    if(player>=player_slots.size())return;
    std::lock_guard guard(mutex);
    if(bottom)eject(bottom_slots[player]);
    else if(player_is_top[player]){eject(player_slots[player]);player_is_top[player]=false;}
#else
    (void)player;(void)bottom;
#endif
}
bool replace_vehicle(const char* path) {
#ifdef SKY_CEMU_PORTAL
    if(!path || !is_vehicle(figure_id(path)))return false;
    std::lock_guard guard(mutex);return replace_managed(path,vehicle_slot);
#else
    (void)path;return false;
#endif
}
void remove_vehicle() {
#ifdef SKY_CEMU_PORTAL
    std::lock_guard guard(mutex);eject(vehicle_slot);
#endif
}
void remove_item() {
#ifdef SKY_CEMU_PORTAL
    std::lock_guard guard(mutex);
    if(item_slot<16){trapteam::cemu_portal_remove_figure(item_slot);std::erase(figure_slots,item_slot);item_slot=16;}
#endif
}
bool load_trap(const char* path) {
#ifdef SKY_CEMU_PORTAL
    if(!enabled()||!path)return false;
    std::lock_guard guard(mutex);return load_locked(path,true);
#else
    (void)path;return false;
#endif
}
void remove_trap() {
#ifdef SKY_CEMU_PORTAL
    std::lock_guard guard(mutex);
    if(trap_slot<16){trapteam::cemu_portal_remove_figure(trap_slot);std::erase(figure_slots,trap_slot);trap_slot=16;}
#endif
}
void remove() {
#ifdef SKY_CEMU_PORTAL
    std::lock_guard guard(mutex);
    for(auto slot:figure_slots) trapteam::cemu_portal_remove_figure(slot);
    figure_slots.clear();
    trap_slot=item_slot=vehicle_slot=16;player_slots=bottom_slots={16,16};player_is_top={false,false};
#endif
}
std::uint64_t call(std::string_view identity,const std::uint64_t* a) {
#ifdef SKY_CEMU_PORTAL
    const auto api=name(identity);
    if (!supports(identity)) throw std::runtime_error("unsupported virtual USB import");
    std::unique_lock lock(mutex);
    if (api=="Init") {
        initialized=true;
        if (!figures_loaded) {
            figures_loaded=true;
            for(const auto* key:{"SKY_PORTAL_FIGURE","SKY_PORTAL_FIGURE_BOTTOM","SKY_PORTAL_TRAP"})
                if (const auto* path=std::getenv(key);path && *path) {
                    const bool trap=std::strcmp(key,"SKY_PORTAL_TRAP")==0,bottom=std::strcmp(key,"SKY_PORTAL_FIGURE_BOTTOM")==0;
                    const auto half=swapper_half(figure_id(path));
                    // The starting bottom half is only placed under a starting top half.
                    if(bottom && (half!=SwapperHalf::bottom || !player_is_top[0]))continue;
                    if(!bottom && !trap && half==SwapperHalf::bottom)continue;
                    if(!load_locked(path,trap) || trap)continue;
                    (bottom?bottom_slots:player_slots)[0]=figure_slots.back();
                    if(!bottom)player_is_top[0]=half==SwapperHalf::top;
                }
        }
        std::printf("Virtual portal: Cemu protocol enabled\n"); return 0;
    }
    if (api=="FreeDeviceList") {
        auto** p=reinterpret_cast<void**>(a[0]);
        if(p && !lists.erase(p)) throw std::runtime_error("unknown USB list ownership");
        delete[] p;return 0;
    }
    if (api=="Exit") {
        if(!pending.empty()) throw std::runtime_error("USB exit with pending transfers");
        opened=initialized=false; return 0;
    }
    if(!initialized) return error(255);
    if(api=="GetDeviceList") {
        if(!a[0])return error(2);
        auto** p=new void*[2]{device,nullptr};lists.insert(p);*reinterpret_cast<void***>(a[0])=p;return 1;
    }
    if(api=="GetDeviceDescriptor") {
        if(a[0]!=reinterpret_cast<U>(device) || !a[1])return error(2);
        auto* d=reinterpret_cast<libusb_device_descriptor*>(a[1]);*d={};
        d->bLength=18;d->bDescriptorType=1;d->bcdUSB=0x200;d->bMaxPacketSize0=64;
        d->idVendor=0x1430;d->idProduct=0x0150;d->bcdDevice=0x100;d->bNumConfigurations=1;return 0;
    }
    if(api=="GetBusNumber" || api=="GetDeviceAddress") return a[0]==reinterpret_cast<U>(device) ? 1 : 0;
    if(api=="GetConfigDescriptor") {
        if(a[0]!=reinterpret_cast<U>(device)||a[1]||!a[2])return error(2);
        auto* p=new Configuration;configurations.insert(p);*reinterpret_cast<libusb_config_descriptor**>(a[2])=&p->config;return 0;
    }
    if(api=="FreeConfigDescriptor") {
        auto* p=reinterpret_cast<Configuration*>(a[0]);
        if(p && !configurations.erase(p))throw std::runtime_error("unknown USB config ownership");
        delete p;return 0;
    }
    if(api=="OpenDeviceWithVidPid") {
        if(a[0]!=0x1430 || a[1]!=0x0150)return 0;
        opened=true;return reinterpret_cast<U>(handle);
    }
    if(api=="Open") {
        if(a[0]!=reinterpret_cast<U>(device)||!a[1])return error(2);
        opened=true;*reinterpret_cast<libusb_device_handle**>(a[1])=handle;return 0;
    }
    if(api=="AllocTransfer") {
        const auto packets=static_cast<int>(a[0]);
        std::printf("Virtual portal: transfer allocation iso capacity %d\n",packets);
        if(packets<0 || packets>64)return 0;
        auto* t=libusb_alloc_transfer(packets);
        if(t)transfers.insert(t);
        return reinterpret_cast<U>(t);
    }
    if(api=="FreeTransfer") {
        auto* t=reinterpret_cast<libusb_transfer*>(a[0]);
        if(std::find(pending.begin(),pending.end(),t)!=pending.end())throw std::runtime_error("free pending USB transfer");
        if(!transfers.erase(t))throw std::runtime_error("unknown USB transfer ownership");
        libusb_free_transfer(t);return 0;
    }
    if(api=="FillInterruptTransfer" || api=="SubmitTransfer" || api=="CancelTransfer") {
        auto* t=reinterpret_cast<libusb_transfer*>(a[0]);
        if(!transfers.contains(t))return error(2);
        if(api=="FillInterruptTransfer") {
            t->dev_handle=reinterpret_cast<libusb_device_handle*>(a[1]);t->endpoint=static_cast<unsigned char>(a[2]);t->type=LIBUSB_TRANSFER_TYPE_INTERRUPT;
            t->buffer=reinterpret_cast<unsigned char*>(a[3]);t->length=static_cast<int>(a[4]);
            t->callback=reinterpret_cast<libusb_transfer_cb_fn>(a[5]);t->user_data=reinterpret_cast<void*>(a[6]);t->timeout=static_cast<unsigned>(a[7]);return 0;
        }
        const auto queued=std::find(pending.begin(),pending.end(),t);
        if(api=="CancelTransfer") {
            if(queued==pending.end())return error(5);
            t->status=LIBUSB_TRANSFER_CANCELLED;return 0;
        }
        if(queued!=pending.end())return error(6);
        if(!opened || t->dev_handle!=handle)return error(4);
        if(t->flags&(LIBUSB_TRANSFER_FREE_BUFFER|LIBUSB_TRANSFER_FREE_TRANSFER))return error(12);
        if(!t->buffer||t->length<0||t->length>64||t->type!=LIBUSB_TRANSFER_TYPE_INTERRUPT) {
            static unsigned rejected=0;
            if(rejected++<8)std::fprintf(stderr,"Virtual portal: rejected transfer endpoint=%02x type=%u length=%d\n",t->endpoint,unsigned(t->type),t->length);
            return error(2);
        }
        t->status=LIBUSB_TRANSFER_COMPLETED;t->actual_length=0;pending.push_back(t);return 0;
    }
    if(api=="HandleEvents"||api=="HandleEventsTimeout") {
        // One completion per poll; never invoke guest code under the USB lock.
        if(pending.empty()){lock.unlock();std::this_thread::sleep_for(std::chrono::milliseconds(1));return 0;}
        auto* t=pending.front();pending.pop_front();
        if(t->status!=LIBUSB_TRANSFER_CANCELLED) {
            if(t->endpoint==0x81) {
                const auto response=trapteam::cemu_portal_read();t->actual_length=std::min<int>(t->length,response.size());
                if(response[0]=='R' || response[0]=='M')
                    std::printf("Virtual portal: handshake %c %02x %02x %02x (%d bytes)\n",response[0],response[1],response[2],response[3],t->actual_length);
                std::memcpy(t->buffer,response.data(),t->actual_length);
            } else if(t->endpoint==2 && t->length==64) {
                const auto sink=portal_audio.load();
                static bool first=true;
                if(first){first=false;std::printf("Virtual portal: speaker PCM received, PC sink %s\n",sink?"bound":"missing");}
                if(sink)sink(t->buffer,64);
                t->actual_length=64;
            }
            else t->status=LIBUSB_TRANSFER_STALL;
        }
        const auto callback=reinterpret_cast<U>(t->callback);
        lock.unlock();
        if(t->endpoint==2 && t->length==64) {
            // Pace speaker packets (32 samples = 4 ms at 8 kHz) against an absolute clock;
            // relative sleeps plus interleaved reads ran at ~78% of real time and starved playback.
            static auto due=std::chrono::steady_clock::now();
            const auto now=std::chrono::steady_clock::now();
            if(due<now-std::chrono::milliseconds(40))due=now;
            due+=std::chrono::milliseconds(4);
            std::this_thread::sleep_until(due);
        } else std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if(callback) {
            auto* context=GuestThreadContext::current();
            if(!context)throw std::runtime_error("USB callback outside guest thread");
            context->callback(callback,t);
        }
        return 0;
    }
    if(!opened || a[0]!=reinterpret_cast<U>(handle))return error(4);
    if(api=="Close"){opened=false;return 0;}
    if(api=="CheckConnected")return 0;
    if(api=="KernelDriverActive")return a[1] ? error(5):0;
    if(api=="ClaimInterface"||api=="ReleaseInterface"||api=="AttachKernelDriver"||api=="DetachKernelDriver")return a[1] ? error(5):0;
    if(api=="ControlTransfer") {
        const auto result=control(static_cast<unsigned char>(a[1]),static_cast<unsigned char>(a[2]),
            static_cast<std::uint16_t>(a[3]),static_cast<std::uint16_t>(a[4]),reinterpret_cast<unsigned char*>(a[5]),static_cast<int>(a[6]));
        if(result<0) {
            static unsigned rejected=0;
            if(rejected++<8)std::fprintf(stderr,"Virtual portal: control rejected type=%02x request=%u value=%04x index=%u length=%u result=%d\n",
                unsigned(a[1]&255),unsigned(a[2]&255),unsigned(a[3]&65535),unsigned(a[4]&65535),unsigned(a[6]),result);
        }
        return result<0 ? error(-result):static_cast<U>(result);
    }
#else
    (void)identity;(void)a;
#endif
    throw std::runtime_error("virtual portal operation unavailable");
}
}

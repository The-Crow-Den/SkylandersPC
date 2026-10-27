// SPDX-License-Identifier: GPL-3.0-or-later
#include "save_data.hpp"
#include "kernel_file.hpp"
#include "local_players.hpp"
#include <array>
#include <cerrno>
#include <cstdlib>
#include <chrono>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <stdexcept>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
namespace {
using U=std::uint64_t;
constexpr std::array<std::string_view,8> names{
    "ZkZhskCPXFw#libSceSaveData#libSceSaveData", "32HQAQdwM2o#libSceSaveData#libSceSaveData",
    "BMR4F-Uek3E#libSceSaveData#libSceSaveData", "85zul--eGXs#libSceSaveData#libSceSaveData",
    "XgvSuIdnMlw#libSceSaveData#libSceSaveData", "c88Yy54Mx0w#libSceSaveData#libSceSaveData",
    "yKDy8S5yLA0#libSceSaveData#libSceSaveData", "S1GkePI17zQ#libSceSaveData#libSceSaveData"};
struct Mount {
    std::int32_t user,pad;U title,dir,fingerprint,blocks;std::uint32_t mode;unsigned char reserved[32];
};
struct MountResult {char point[16];U required;std::uint32_t unused,status;unsigned char reserved[28];std::uint32_t pad;};
struct Param {char title[128],subtitle[128],detail[1024];std::uint32_t user,pad;std::int64_t mtime;unsigned char reserved[32];};
struct Icon {U buffer,capacity,size;unsigned char reserved[32];};
static_assert(sizeof(Mount)==80 && sizeof(MountResult)==64 && sizeof(Param)==1328);
bool safe(std::string_view name) {
    return !name.empty() && name!="." && name!=".." && std::all_of(name.begin(),name.end(),[](unsigned char c){
        return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.';});
}
bool directory(const std::filesystem::path& path) {
    std::error_code ec;
    if(std::filesystem::weakly_canonical(path,ec)!=std::filesystem::absolute(path).lexically_normal()||ec)return false;
    std::filesystem::create_directories(path,ec);
    return !ec && std::filesystem::canonical(path,ec)==std::filesystem::absolute(path).lexically_normal() && !ec;
}
bool write_private(const std::filesystem::path& path,const void* data,std::size_t size) {
    // Never truncate the last valid metadata. Publish a fully synced sibling
    // only after every byte has been written successfully.
    struct stat original{};
    if(lstat(path.c_str(),&original)==0) {
        if(!S_ISREG(original.st_mode)||original.st_nlink!=1)return false;
    } else if(errno!=ENOENT)return false;
    const int parent=open(path.parent_path().c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(parent<0)return false;
    std::string temporary=path.string()+".pending-XXXXXX";
    const int fd=mkostemp(temporary.data(),O_CLOEXEC);
    if(fd<0){close(parent);return false;}
    bool ok=true;
    std::size_t done=0;
    while(done<size){
        const auto n=write(fd,static_cast<const unsigned char*>(data)+done,size-done);
        if(n<0 && errno==EINTR)continue;
        if(n<=0){ok=false;break;}
        done+=static_cast<std::size_t>(n);
    }
    if(ok){int result;do{result=fsync(fd);}while(result<0 && errno==EINTR);ok=result==0;}
    if(close(fd)!=0)ok=false;
    if(ok)ok=rename(temporary.c_str(),path.c_str())==0;
    if(!ok)unlink(temporary.c_str());
    else {int result;do{result=fsync(parent);}while(result<0 && errno==EINTR);ok=result==0;}
    close(parent);return ok;
}
}
struct SaveData::Impl {
    KernelFile& files;
    std::mutex mutex;
    std::filesystem::path root;
    std::string title;
    bool initialized=false;
    struct Slot {std::filesystem::path data,meta;bool read_only;};
    std::map<std::string,Slot> slots;
    explicit Impl(KernelFile& f):files(f){}
};
SaveData::SaveData(KernelFile& files):impl_(std::make_unique<Impl>(files)){}
SaveData::~SaveData()=default;
void SaveData::configure(const std::string& root,const std::string& title) {
    if(!safe(title)||title.size()!=9||!title.starts_with("CUSA"))throw std::runtime_error("save title ID unavailable");
    impl_->root=std::filesystem::absolute(root).lexically_normal();impl_->title=title;
}
bool SaveData::supports(std::string_view identity){return std::find(names.begin(),names.end(),identity)!=names.end();}
U SaveData::call(std::string_view identity,const U* a) {
    const auto op=std::find(names.begin(),names.end(),identity)-names.begin();
    if(op==static_cast<std::ptrdiff_t>(names.size()))throw std::runtime_error("unsupported SaveData import");
    std::lock_guard lock(impl_->mutex);
    if(op==0){if(impl_->initialized)return 0x809f0003;impl_->initialized=true;return 0;}
    if(!impl_->initialized)return 0x809f0001;
    if(op==6){if(!impl_->slots.empty())return 0x809f0003;impl_->initialized=false;return 0;}
    if(op==7){
        struct Request{std::int32_t user,pad;U title,dir;};
        if(!a[0]||impl_->root.empty())return 0x809f0000;
        const auto& request=*reinterpret_cast<const Request*>(a[0]);
        if(!LocalPlayers::valid_user(static_cast<std::uint64_t>(request.user)))return 0x809f0011;
        if(request.title){const auto* title=reinterpret_cast<const char*>(request.title);if(strnlen(title,10)!=9||std::string_view(title,9)!=impl_->title)return 0x809f0000;}
        if(!request.dir)return 0x809f0000;
        const auto* raw=reinterpret_cast<const char*>(request.dir);const auto length=strnlen(raw,32);
        if(length==32||!safe({raw,length}))return 0x809f0000;
        const auto parent=impl_->root/impl_->title/("user-"+std::to_string(request.user));
        const auto data=parent/std::string(raw,length),meta=parent/(std::string(raw,length)+".sce_sys");
        for(const auto& [point,slot]:impl_->slots)if(slot.data==data)return 0x809f0003;
        std::error_code ec;
        if(!std::filesystem::exists(data,ec))return ec?0x809f000b:0x809f0008;
        if(std::filesystem::canonical(data,ec)!=data||ec)return 0x809f000b;
        const auto trash=parent/".deleted";
        if(!directory(trash))return 0x809f000b;
        const auto target=trash/(std::string(raw,length)+"-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::rename(data,target,ec);if(ec)return 0x809f000b;
        if(std::filesystem::exists(meta,ec)){std::filesystem::rename(meta,target.string()+".sce_sys",ec);if(ec)return 0x809f000b;}
        return 0;
    }
    if(op==1){
        if(impl_->root.empty())throw std::runtime_error("SaveData requires a configured title ID");
        if(!a[0]||!a[1])return 0x809f0000;
        const auto& m=*reinterpret_cast<const Mount*>(a[0]);
        if(!LocalPlayers::valid_user(static_cast<std::uint64_t>(m.user)))return 0x809f0011;
        if(!m.dir || !m.mode || (m.mode&~63u) || ((m.mode&3)==3) || ((m.mode&4)&&(m.mode&32)))return 0x809f0000;
        if(m.title){const auto* title=reinterpret_cast<const char*>(m.title);if(strnlen(title,10)!=9 || std::string_view(title,9)!=impl_->title)return 0x809f0000;}
        const auto* raw=reinterpret_cast<const char*>(m.dir);const auto length=strnlen(raw,32);
        if(length==32||!safe({raw,length}))return 0x809f0000;
        if(m.mode&16)throw std::runtime_error("SaveData mount COPY_ICON is unsupported");
        const auto user_root=impl_->root/impl_->title/("user-"+std::to_string(m.user));
        if(!directory(user_root))return 0x809f000b;
        const auto data=user_root/std::string(raw,length);
        const auto meta=user_root/(std::string(raw,length)+".sce_sys");
        std::error_code ec;const bool exists=std::filesystem::exists(data,ec);
        if(ec)return 0x809f000b;
        const bool create=m.mode&(4|32),read_only=m.mode&1;
        std::printf("SaveData: mount mode=0x%x existing=%d\n",m.mode,exists);
        if(!exists&&!create)return 0x809f0008;
        if(exists&&(m.mode&4))return 0x809f0007;
        if(!directory(data)||!directory(meta))return 0x809f000b;
        for(const auto& [point,slot]:impl_->slots)if(slot.data==data)return 0x809f0003;
        unsigned index=0;std::string point;
        for(;index<16;++index){point="/savedata"+std::to_string(index);if(!impl_->slots.contains(point))break;}
        if(index==16)return 0x809f000c;
        if(!impl_->files.mount_save(point,data.string(),read_only))return 0x809f000b;
        impl_->slots.emplace(point,Impl::Slot{data,meta,read_only});
        auto& out=*reinterpret_cast<MountResult*>(a[1]);out={};std::memcpy(out.point,point.c_str(),point.size());out.status=exists?0:1;
        return 0;
    }
    if(!a[0])return 0x809f0000;
    const auto* raw=reinterpret_cast<const char*>(a[0]);const auto length=strnlen(raw,16);
    if(length==16)return 0x809f0000;
    const auto found=impl_->slots.find(std::string(raw,length));
    if(found==impl_->slots.end())return 0x809f0004;
    const auto& slot=found->second;
    if(op==2){if(!impl_->files.unmount_save(found->first))return 0x809f0003;impl_->slots.erase(found);return 0;}
    if((op==3||op==5)&&slot.read_only)return 0x809f0000;
    if(op==5){
        if(!a[1])return 0x809f0000;
        const auto& icon=*reinterpret_cast<const Icon*>(a[1]);
        if(!icon.buffer||icon.size>icon.capacity||icon.size>2*1024*1024)return 0x809f0000;
        return write_private(slot.meta/"icon0.png",reinterpret_cast<const void*>(icon.buffer),icon.size)?0:0x809f000b;
    }
    if(op==3||op==4){
        if(!a[2])return 0x809f0000;
        Param param{};std::ifstream input(slot.meta/"param.bin",std::ios::binary);
        if(input){input.read(reinterpret_cast<char*>(&param),sizeof(param));if(input.gcount()!=sizeof(param))return 0x809f000f;}
        void* field=nullptr;std::size_t size=0;
        switch(a[1]){case 0:field=&param;size=sizeof(param);break;case 1:field=param.title;size=128;break;case 2:field=param.subtitle;size=128;break;case 3:field=param.detail;size=1024;break;case 4:field=&param.user;size=4;break;default:return 0x809f0000;}
        if(op==3){
            if((a[1]==0||a[1]==4)&&a[3]<size)return 0x809f0000;
            std::memset(field,0,size);std::memcpy(field,reinterpret_cast<const void*>(a[2]),std::min<U>(a[3],size));
            return write_private(slot.meta/"param.bin",&param,sizeof(param))?0:0x809f000b;
        }
        if(a[3]<size)return 0x809f0000;
        std::memcpy(reinterpret_cast<void*>(a[2]),field,size);
        if(a[4])*reinterpret_cast<std::size_t*>(a[4])=size;
        return 0;
    }
    throw std::runtime_error("unimplemented SaveData operation");
}

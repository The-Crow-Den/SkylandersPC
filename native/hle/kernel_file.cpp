// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_file.hpp"
#include "../platform/host_files.hpp"
#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <stdexcept>
#include <vector>
#include <atomic>
#include <memory>

namespace {
using U = std::uint64_t;
constexpr std::array<std::string_view, 11> names{
    "1G3lF1Gg1k8#libkernel#libkernel", "UK2Tl2DWUns#libkernel#libkernel",
    "Cg4srZ6TKbU#libkernel#libkernel", "+r3rMFwItV4#libkernel#libkernel",
    "oib76F-12fk#libkernel#libkernel", "kBwCPsYX-m4#libkernel#libkernel",
    "eV9wAD2riIA#libkernel#libkernel", "4wSze92BhLI#libkernel#libkernel",
    "nKWi-N2HBV4#libkernel#libkernel", "fTx66l5iWIA#libkernel#libkernel",
    "VW3TVZiM4-E#libkernel#libkernel"};
U error(int code) {
    unsigned guest;
    switch (code) {
    case ENOENT: guest = 2; break; case EIO: guest = 5; break;
    case EBADF: guest = 9; break; case ENOMEM: guest = 12; break;
    case EACCES: guest = 13; break; case EFAULT: guest = 14; break;
    case EINVAL: guest = 22; break; case EMFILE: guest = 24; break;
    case EISDIR: guest = 21; break; case ENOTDIR: guest = 20; break;
    case EROFS: guest = 30; break; case ELOOP: guest = 62; break;
    case ENAMETOOLONG: guest = 63; break; case EINTR: guest = 4; break;
    case EEXIST: guest = 17; break; case ENOSPC: guest = 28; break;
    default: throw std::runtime_error("unmapped file error");
    }
    return static_cast<U>(static_cast<std::int64_t>(static_cast<std::int32_t>(0x80020000u | guest)));
}
struct Timespec { std::int64_t seconds, nanoseconds; };
struct GuestStat {
    std::uint32_t device, inode;
    std::uint16_t mode, links;
    std::uint32_t uid, gid, rdev;
    Timespec atime, mtime, ctime;
    std::int64_t size, blocks;
    std::uint32_t block_size, flags, generation;
    std::int32_t spare;
    Timespec birthtime;
};
static_assert(sizeof(GuestStat) == 120);
void convert(const SkyHost::FileInfo& s, GuestStat* out) {
    *out = {};
    out->device = s.device; out->inode = s.inode;
    out->mode = s.mode; out->links = static_cast<std::uint16_t>(s.links);
    out->size = s.size; out->blocks = s.blocks; out->block_size = s.block_size;
    out->atime = {s.atime.seconds,s.atime.nanoseconds};
    out->mtime = {s.mtime.seconds,s.mtime.nanoseconds};
    out->ctime = {s.ctime.seconds,s.ctime.nanoseconds};
    out->birthtime = {s.birthtime.seconds,s.birthtime.nanoseconds};
}
}
struct KernelFile::Impl {
    // The lock guards the tables only. Blocking I/O runs on a shared
    // descriptor outside it; the last user closes the host fd, so a
    // concurrent guest close never lets a read reach a reused fd.
    struct Descriptor {
        SkyHost::File host;
        std::string owner; // Save mount name; empty for read-only game files.
        std::atomic<bool> dirty = false;
        Descriptor(SkyHost::File&& file, std::string mount) : host(std::move(file)), owner(std::move(mount)) {}
    };
    std::mutex lock;
    SkyHost::File root;
    int next = 3;
    std::map<int, std::shared_ptr<Descriptor>> descriptors;
    struct SaveMount { SkyHost::File directory; bool read_only; };
    std::map<std::string, SaveMount> mounts;
    // Walk from the configured directory descriptor. Never follow a symlink or
    // resolve '..', even when a game path names a host absolute path.
    bool open_path(const char* input, const SkyHost::FileOpen& flags, SkyHost::File& output, std::string* owner = nullptr) {
        if (!input) { errno = EFAULT; return false; }
        const auto length = strnlen(input, 1024);
        if (length == 1024) { errno = ENAMETOOLONG; return false; }
        std::string_view path(input, length);
        const auto* selected = &root;
        bool writable = false;
        bool save_mount = false;
        if (path.starts_with("/savedata")) {
            const auto slash=path.find('/',1);
            const std::string key(path.substr(0,slash));
            const auto found=mounts.find(key);
            if(found==mounts.end()){errno=ENOENT;return false;}
            selected=&found->second.directory; writable=!found->second.read_only;
            save_mount=true;
            if(owner)*owner=key;
            path=slash==path.npos ? std::string_view{} : path.substr(slash+1);
        }
        else if (path == "/app0" || path == "/hostapp") path = "";
        else if (path.starts_with("/app0/")) path.remove_prefix(6);
        else if (path.starts_with("/hostapp/")) path.remove_prefix(9);
        else if (path.starts_with('/')) { errno = ENOENT; return false; }
        if (!writable && (flags.access != SkyHost::FileAccess::Read || flags.append || flags.create || flags.truncate)) {errno=EROFS;return false;}
        if (!selected->valid()) throw std::runtime_error("game root is required for file access");
        std::vector<std::string> components;
        while (!path.empty()) {
            const auto slash = path.find('/');
            const auto part = path.substr(0, slash);
            if (part == "..") { errno = EACCES; return false; }
            if (!part.empty() && part != ".") components.emplace_back(part);
            if (slash == std::string_view::npos) break;
            path.remove_prefix(slash + 1);
        }
        SkyHost::File directory;
        if (!selected->duplicate_directory(directory)) return false;
        for (std::size_t i = 0; i < components.size(); ++i) {
            const bool final = i + 1 == components.size();
            auto options = final ? flags : SkyHost::FileOpen{};
            if (!final) options.directory = true;
            SkyHost::File next_file;
            if (!directory.open_child(components[i],options,save_mount && final,next_file)) {
                return false;
            }
            directory = std::move(next_file);
        }
        output = std::move(directory);
        return true;
    }
};
KernelFile::KernelFile() : impl_(std::make_unique<Impl>()) {}
KernelFile::~KernelFile() = default;
bool KernelFile::mount_save(const std::string& guest,const std::filesystem::path& host,bool read_only) {
    SkyHost::File directory;
    if (!directory.open_directory(host)) return false;
    return mount_save(guest,directory,read_only);
}
bool KernelFile::mount_save(const std::string& guest,const SkyHost::File& host,bool read_only) {
    std::lock_guard lock(impl_->lock);
    if(impl_->mounts.contains(guest))return false;
    SkyHost::File directory;
    if (!host.duplicate_directory(directory)) return false;
    impl_->mounts.emplace(guest,Impl::SaveMount{std::move(directory),read_only});return true;
}
bool KernelFile::unmount_save(const std::string& guest) {
    std::lock_guard lock(impl_->lock);
    const auto mount=impl_->mounts.find(guest);
    if(mount==impl_->mounts.end())return false;
    for(const auto& [id,file]:impl_->descriptors)if(file->owner==guest)return false;
    impl_->mounts.erase(mount);return true;
}
void KernelFile::configure(const std::filesystem::path& root) {
    if (root.empty()) return;
    if (!impl_->root.open_directory(root,true)) throw std::runtime_error("cannot open game root directory");
}
bool KernelFile::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
U KernelFile::call(std::string_view identity, const U* a) {
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    if (operation == 0) {
        if ((a[1]&3)==3)return error(EINVAL);
        if (a[1] & ~0x20e8full) throw std::runtime_error("unsupported file-open flags");
        SkyHost::FileOpen flags;
        flags.access = (a[1]&3)==2 ? SkyHost::FileAccess::ReadWrite : (a[1]&3)==1 ? SkyHost::FileAccess::Write : SkyHost::FileAccess::Read;
        flags.append = (a[1]&8) != 0;
        flags.create = (a[1]&0x200) != 0;
        flags.truncate = (a[1]&0x400) != 0;
        flags.exclusive = (a[1]&0x800) != 0;
        flags.directory = (a[1]&0x20000) != 0;
        std::lock_guard lock(impl_->lock);
        std::string owner;
        SkyHost::File host;
        if (!impl_->open_path(reinterpret_cast<const char*>(a[0]),flags,host,&owner)) return error(errno);
        auto file = std::make_shared<Impl::Descriptor>(std::move(host),std::move(owner));
        const int id = impl_->next++;
        impl_->descriptors.emplace(id, std::move(file));
        std::fprintf(stderr, "{\"event\":\"game-file-open\",\"descriptor\":%d}\n", id);
        return static_cast<U>(id);
    }
    if (operation == 6) {
        if (!a[1]) return error(EFAULT);
        SkyHost::File host;
        {
            std::lock_guard lock(impl_->lock);
            if (!impl_->open_path(reinterpret_cast<const char*>(a[0]),{},host)) return error(errno);
        }
        SkyHost::FileInfo info{};
        if (!host.stat(info)) return error(errno);
        convert(info, reinterpret_cast<GuestStat*>(a[1]));
        return 0;
    }
    std::shared_ptr<Impl::Descriptor> file;
    {
        std::lock_guard lock(impl_->lock);
        const auto found = impl_->descriptors.find(static_cast<int>(a[0]));
        if (found == impl_->descriptors.end()) return error(EBADF);
        file = found->second;
        if (operation == 1) impl_->descriptors.erase(found);
    }
    auto& host = file->host;
    const bool writable = !file->owner.empty();
    if (operation == 1) {
        const int sync_status=file->dirty ? host.sync() : 0;
        const int sync_error=errno;
        if(sync_status)return error(sync_error);
        // Another thread is still in a call on this descriptor; the last user
        // closes it. Otherwise close here so its status reaches the guest.
        if(file.use_count()>1)return 0;
        const int status = host.close(), saved = errno;
        return status ? error(saved) : 0;
    }
    if (operation == 2 || operation == 3) {
        if (a[2] > 1024ull * 1024 * 1024) return error(EINVAL);
        if (!a[1] && a[2]) return error(EFAULT);
        const auto count = operation == 2 ? host.read(reinterpret_cast<void*>(a[1]), a[2]) :
            host.read_at(reinterpret_cast<void*>(a[1]), a[2], static_cast<std::int64_t>(a[3]));
        return count < 0 ? error(errno) : static_cast<U>(count);
    }
    if (operation == 4) {
        if (a[2] > 2) return error(EINVAL);
        const auto position = host.seek(static_cast<std::int64_t>(a[1]),static_cast<int>(a[2]));
        return position < 0 ? error(errno) : static_cast<U>(position);
    }
    if (operation == 5) {
        if (!a[1]) return error(EFAULT);
        SkyHost::FileInfo info{};
        if (!host.stat(info)) return error(errno);
        convert(info, reinterpret_cast<GuestStat*>(a[1])); return 0;
    }
    if(operation==9){
        if(host.sync())return error(errno);
        file->dirty=false;return 0;
    }
    if(operation==10){
        if(!writable)return error(EROFS);
        if(a[1]>1024ull*1024*1024)return error(EINVAL);
        if(host.truncate(static_cast<std::int64_t>(a[1])))return error(errno);
        file->dirty=true;return 0;
    }
    if (operation == 7 || operation == 8) {
        if(!writable)return error(EROFS);
        if(!a[1]&&a[2])return error(EFAULT);
        if(a[2]>1024ull*1024*1024)return error(EINVAL);
        if(operation==8 && static_cast<std::int64_t>(a[3])<0)return error(EINVAL);
        const auto count=operation==7 ? host.write(reinterpret_cast<const void*>(a[1]),a[2]):
            host.write_at(reinterpret_cast<const void*>(a[1]),a[2],static_cast<std::int64_t>(a[3]));
        if(count>0)file->dirty=true;
        return count<0?error(errno):static_cast<U>(count);
    }
    throw std::runtime_error("unsupported file import");
}

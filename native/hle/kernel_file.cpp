// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_file.hpp"
#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <mutex>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>
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
void convert(const struct stat& s, GuestStat* out) {
    *out = {};
    out->device = static_cast<std::uint32_t>(s.st_dev); out->inode = static_cast<std::uint32_t>(s.st_ino);
    out->mode = static_cast<std::uint16_t>(s.st_mode); out->links = static_cast<std::uint16_t>(s.st_nlink);
    out->size = s.st_size; out->blocks = s.st_blocks; out->block_size = static_cast<std::uint32_t>(s.st_blksize);
    out->atime = {s.st_atim.tv_sec, s.st_atim.tv_nsec}; out->mtime = {s.st_mtim.tv_sec, s.st_mtim.tv_nsec};
    out->ctime = {s.st_ctim.tv_sec, s.st_ctim.tv_nsec}; out->birthtime = out->ctime;
}
}
struct KernelFile::Impl {
    // The lock guards the tables only. Blocking I/O runs on a shared
    // descriptor outside it; the last user closes the host fd, so a
    // concurrent guest close never lets a read reach a reused fd.
    struct Descriptor {
        int fd;
        std::string owner; // Save mount name; empty for read-only game files.
        std::atomic<bool> dirty = false;
        Descriptor(int host, std::string mount) : fd(host), owner(std::move(mount)) {}
        ~Descriptor() { if (fd >= 0) close(fd); }
    };
    std::mutex lock;
    int root = -1, next = 3;
    std::map<int, std::shared_ptr<Descriptor>> descriptors;
    struct SaveMount { int fd; bool read_only; };
    std::map<std::string, SaveMount> mounts;
    ~Impl() { for(auto& [name,m]:mounts)close(m.fd); if (root >= 0) close(root); }
    // Walk from the configured directory descriptor. Never follow a symlink or
    // resolve '..', even when a game path names a host absolute path.
    int open_path(const char* input, int flags, std::string* owner = nullptr) {
        if (!input) { errno = EFAULT; return -1; }
        const auto length = strnlen(input, 1024);
        if (length == 1024) { errno = ENAMETOOLONG; return -1; }
        std::string_view path(input, length);
        int selected = root;
        bool writable = false;
        bool save_mount = false;
        if (path.starts_with("/savedata")) {
            const auto slash=path.find('/',1);
            const std::string key(path.substr(0,slash));
            const auto found=mounts.find(key);
            if(found==mounts.end()){errno=ENOENT;return -1;}
            selected=found->second.fd; writable=!found->second.read_only;
            save_mount=true;
            if(owner)*owner=key;
            path=slash==path.npos ? std::string_view{} : path.substr(slash+1);
        }
        else if (path == "/app0" || path == "/hostapp") path = "";
        else if (path.starts_with("/app0/")) path.remove_prefix(6);
        else if (path.starts_with("/hostapp/")) path.remove_prefix(9);
        else if (path.starts_with('/')) { errno = ENOENT; return -1; }
        if (!writable && (flags & (O_WRONLY|O_RDWR|O_APPEND|O_CREAT|O_TRUNC))) {errno=EROFS;return -1;}
        if (selected < 0) throw std::runtime_error("game root is required for file access");
        std::vector<std::string> components;
        while (!path.empty()) {
            const auto slash = path.find('/');
            const auto part = path.substr(0, slash);
            if (part == "..") { errno = EACCES; return -1; }
            if (!part.empty() && part != ".") components.emplace_back(part);
            if (slash == std::string_view::npos) break;
            path.remove_prefix(slash + 1);
        }
        int directory = dup(selected);
        if (directory < 0) return -1;
        for (std::size_t i = 0; i < components.size(); ++i) {
            const bool final=i+1==components.size();
            const int final_flags=save_mount ? flags&~O_TRUNC : flags;
            int next_fd = openat(directory, components[i].c_str(),
                O_NOFOLLOW | O_CLOEXEC | (final ? final_flags : O_RDONLY | O_DIRECTORY),0600);
            if(next_fd>=0 && final && save_mount){
                struct stat info{};
                if(fstat(next_fd,&info)||(!S_ISDIR(info.st_mode)&&(!S_ISREG(info.st_mode)||info.st_nlink!=1))){
                    close(next_fd);next_fd=-1;errno=EACCES;
                }else if((flags&O_TRUNC)&&ftruncate(next_fd,0)){const auto saved=errno;close(next_fd);next_fd=-1;errno=saved;}
            }
            const int saved = errno;
            close(directory); directory = next_fd;
            if (directory < 0) { errno = saved; return -1; }
        }
        return directory;
    }
};
KernelFile::KernelFile() : impl_(std::make_unique<Impl>()) {}
KernelFile::~KernelFile() = default;
bool KernelFile::mount_save(const std::string& guest,const std::string& host,bool read_only) {
    std::lock_guard lock(impl_->lock);
    if(impl_->mounts.contains(guest))return false;
    const int fd=open(host.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0)return false;
    impl_->mounts.emplace(guest,Impl::SaveMount{fd,read_only});return true;
}
bool KernelFile::unmount_save(const std::string& guest) {
    std::lock_guard lock(impl_->lock);
    const auto mount=impl_->mounts.find(guest);
    if(mount==impl_->mounts.end())return false;
    for(const auto& [id,file]:impl_->descriptors)if(file->owner==guest)return false;
    close(mount->second.fd);impl_->mounts.erase(mount);return true;
}
void KernelFile::configure(const std::string& root) {
    if (root.empty()) return;
    impl_->root = open(root.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (impl_->root < 0) throw std::runtime_error("cannot open game root directory");
}
bool KernelFile::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
U KernelFile::call(std::string_view identity, const U* a) {
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    if (operation == 0) {
        if ((a[1]&3)==3)return error(EINVAL);
        if (a[1] & ~0x20e8full) throw std::runtime_error("unsupported file-open flags");
        int flags=(a[1]&3)==2 ? O_RDWR : (a[1]&3)==1 ? O_WRONLY : O_RDONLY;
        if(a[1]&8)flags|=O_APPEND;
        if(a[1]&0x200)flags|=O_CREAT;
        if(a[1]&0x400)flags|=O_TRUNC;
        if(a[1]&0x800)flags|=O_EXCL;
        if(a[1]&0x20000)flags|=O_DIRECTORY;
        std::lock_guard lock(impl_->lock);
        std::string owner;
        const int fd = impl_->open_path(reinterpret_cast<const char*>(a[0]), flags,&owner);
        if (fd < 0) return error(errno);
        auto file = std::make_shared<Impl::Descriptor>(fd, std::move(owner));
        const int id = impl_->next++;
        impl_->descriptors.emplace(id, std::move(file));
        dprintf(STDERR_FILENO, "{\"event\":\"game-file-open\",\"descriptor\":%d}\n", id);
        return static_cast<U>(id);
    }
    if (operation == 6) {
        if (!a[1]) return error(EFAULT);
        int fd;
        {
            std::lock_guard lock(impl_->lock);
            fd = impl_->open_path(reinterpret_cast<const char*>(a[0]), O_RDONLY);
        }
        if (fd < 0) return error(errno);
        struct stat info{};
        const int status = fstat(fd, &info), saved = errno;
        close(fd);
        if (status) return error(saved);
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
    const int fd = file->fd;
    const bool writable = !file->owner.empty();
    if (operation == 1) {
        const int sync_status=file->dirty ? fsync(fd) : 0;
        const int sync_error=errno;
        if(sync_status)return error(sync_error);
        // Another thread is still in a call on this descriptor; the last user
        // closes it. Otherwise close here so its status reaches the guest.
        if(file.use_count()>1)return 0;
        const int status = close(fd), saved = errno;
        file->fd = -1;
        return status ? error(saved) : 0;
    }
    if (operation == 2 || operation == 3) {
        if (a[2] > 1024ull * 1024 * 1024) return error(EINVAL);
        if (!a[1] && a[2]) return error(EFAULT);
        const auto count = operation == 2 ? read(fd, reinterpret_cast<void*>(a[1]), a[2]) :
            pread(fd, reinterpret_cast<void*>(a[1]), a[2], static_cast<off_t>(a[3]));
        return count < 0 ? error(errno) : static_cast<U>(count);
    }
    if (operation == 4) {
        if (a[2] > 2) return error(EINVAL);
        const auto position = lseek(fd, static_cast<off_t>(a[1]), static_cast<int>(a[2]));
        return position < 0 ? error(errno) : static_cast<U>(position);
    }
    if (operation == 5) {
        if (!a[1]) return error(EFAULT);
        struct stat info{};
        if (fstat(fd, &info)) return error(errno);
        convert(info, reinterpret_cast<GuestStat*>(a[1])); return 0;
    }
    if(operation==9){
        if(fsync(fd))return error(errno);
        file->dirty=false;return 0;
    }
    if(operation==10){
        if(!writable)return error(EROFS);
        if(a[1]>1024ull*1024*1024)return error(EINVAL);
        if(ftruncate(fd,static_cast<off_t>(a[1])))return error(errno);
        file->dirty=true;return 0;
    }
    if (operation == 7 || operation == 8) {
        if(!writable)return error(EROFS);
        if(!a[1]&&a[2])return error(EFAULT);
        if(a[2]>1024ull*1024*1024)return error(EINVAL);
        if(operation==8 && static_cast<std::int64_t>(a[3])<0)return error(EINVAL);
        const auto count=operation==7 ? write(fd,reinterpret_cast<const void*>(a[1]),a[2]):
            pwrite(fd,reinterpret_cast<const void*>(a[1]),a[2],static_cast<off_t>(a[3]));
        if(count>0)file->dirty=true;
        return count<0?error(errno):static_cast<U>(count);
    }
    throw std::runtime_error("unsupported file import");
}

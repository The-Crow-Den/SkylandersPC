// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_files.hpp"
#include <cerrno>
#include <fcntl.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>
namespace SkyHost {
struct File::Impl {
    int fd = -1;
    ~Impl() { const auto saved = errno; if (fd >= 0) ::close(fd); errno = saved; }
};
File::File() = default;
File::~File() = default;
File::File(File&&) noexcept = default;
File& File::operator=(File&&) noexcept = default;
bool File::valid() const noexcept { return impl_ && impl_->fd >= 0; }
bool File::open_directory(const std::filesystem::path& path, bool allow_root_links) {
    if (path.empty()) { errno=ENOENT; return false; }
    if (path.native().find('\0') != std::string::npos) { errno = EINVAL; return false; }
    if (allow_root_links) {
        auto next = std::make_unique<Impl>();
        next->fd = ::open(path.c_str(),O_RDONLY | O_DIRECTORY | O_CLOEXEC);
        if (next->fd < 0) return false;
        impl_ = std::move(next);
        return true;
    }
    File current;
    auto root = std::make_unique<Impl>();
    root->fd = ::open("/",O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (root->fd < 0) return false;
    current.impl_ = std::move(root);
    FileOpen options;
    options.directory = true;
    for (const auto& component : std::filesystem::absolute(path).relative_path()) {
        const auto& name = component.native();
        if (name.empty() || name == ".") continue;
        File next;
        if (!current.open_child(name,options,false,next)) return false;
        current = std::move(next);
    }
    impl_ = std::move(current.impl_);
    return true;
}
bool File::duplicate_directory(File& output) const {
    if (&output == this) { errno=EINVAL; return false; }
    if (!valid()) { errno = EBADF; return false; }
    struct ::stat info{};
    if (::fstat(impl_->fd,&info)) return false;
    if (!S_ISDIR(info.st_mode)) { errno = ENOTDIR; return false; }
    auto next = std::make_unique<Impl>();
    next->fd = ::fcntl(impl_->fd,F_DUPFD_CLOEXEC,0);
    if (next->fd < 0) return false;
    output.impl_ = std::move(next);
    return true;
}
bool File::open_child(std::string_view name, const FileOpen& options, bool single_link, File& output) const {
    if (&output == this) { errno=EINVAL; return false; }
    if (!valid()) { errno = EBADF; return false; }
    if (name.empty() || name == "." || name == ".." || name.find('/') != name.npos || name.find('\0') != name.npos) {
        errno = EACCES; return false;
    }
    int flags = O_NOFOLLOW | O_CLOEXEC;
    switch (options.access) {
    case FileAccess::Read: flags |= O_RDONLY; break;
    case FileAccess::Write: flags |= O_WRONLY; break;
    case FileAccess::ReadWrite: flags |= O_RDWR; break;
    default: errno = EINVAL; return false;
    }
    if (options.append) flags |= O_APPEND;
    if (options.create) flags |= O_CREAT;
    if (options.exclusive) flags |= O_EXCL;
    if (options.directory) flags |= O_DIRECTORY;
    if (options.truncate && !single_link) flags |= O_TRUNC;
    auto next = std::make_unique<Impl>();
    const std::string component(name);
    next->fd = ::openat(impl_->fd,component.c_str(),flags,0600);
    if (next->fd < 0) return false;
    if (single_link) {
        struct ::stat info{};
        if (::fstat(next->fd,&info) || (!S_ISDIR(info.st_mode) && (!S_ISREG(info.st_mode) || info.st_nlink != 1))) {
            errno = EACCES; return false;
        }
        if (options.truncate && ::ftruncate(next->fd,0)) return false;
    }
    output.impl_ = std::move(next);
    return true;
}
bool File::stat(FileInfo& output) const {
    if (!valid()) { errno = EBADF; return false; }
    struct ::stat info{};
    if (::fstat(impl_->fd,&info)) return false;
    FileInfo next{};
    next.device = static_cast<std::uint32_t>(info.st_dev);
    next.inode = static_cast<std::uint32_t>(info.st_ino);
    next.mode = static_cast<std::uint16_t>(info.st_mode);
    next.links = static_cast<std::uint64_t>(info.st_nlink);
    next.size = info.st_size; next.blocks = info.st_blocks;
    next.block_size = static_cast<std::uint32_t>(info.st_blksize);
    next.atime = {info.st_atim.tv_sec,info.st_atim.tv_nsec};
    next.mtime = {info.st_mtim.tv_sec,info.st_mtim.tv_nsec};
    next.ctime = {info.st_ctim.tv_sec,info.st_ctim.tv_nsec};
    next.birthtime = next.ctime; // Existing Linux guest-stat contract.
    next.directory = S_ISDIR(info.st_mode); next.regular = S_ISREG(info.st_mode);
    output = next;
    return true;
}
std::int64_t File::read(void* data, std::size_t size) { if (!valid()) { errno=EBADF; return -1; } return ::read(impl_->fd,data,size); }
std::int64_t File::read_at(void* data, std::size_t size, std::int64_t offset) { if (!valid()) { errno=EBADF; return -1; } return ::pread(impl_->fd,data,size,offset); }
std::int64_t File::write(const void* data, std::size_t size) { if (!valid()) { errno=EBADF; return -1; } return ::write(impl_->fd,data,size); }
std::int64_t File::write_at(const void* data, std::size_t size, std::int64_t offset) { if (!valid()) { errno=EBADF; return -1; } return ::pwrite(impl_->fd,data,size,offset); }
std::int64_t File::seek(std::int64_t offset, int origin) { if (!valid()) { errno=EBADF; return -1; } return ::lseek(impl_->fd,offset,origin); }
int File::sync() { if (!valid()) { errno=EBADF; return -1; } return ::fsync(impl_->fd); }
int File::truncate(std::int64_t size) { if (!valid()) { errno=EBADF; return -1; } return ::ftruncate(impl_->fd,size); }
int File::close() {
    if (!valid()) { errno=EBADF; return -1; }
    const auto fd = std::exchange(impl_->fd,-1);
    return ::close(fd);
}
}

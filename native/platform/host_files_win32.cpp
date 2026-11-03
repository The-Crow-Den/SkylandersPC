// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_files.hpp"
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <winternl.h>
#include <algorithm>
#include <array>
#include <cerrno>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
// MinGW's user-mode winternl.h omits this exported native operation. Signature
// follows Microsoft's NtWriteFile ABI; the import is resolved by ntdll.
extern "C" NTSYSAPI NTSTATUS NTAPI NtWriteFile(HANDLE,HANDLE,PIO_APC_ROUTINE,PVOID,
    PIO_STATUS_BLOCK,PVOID,ULONG,PLARGE_INTEGER,PULONG);

namespace SkyHost {
namespace {
constexpr ULONG no_reparse = OBJ_DONT_REPARSE;
constexpr ULONG open_reparse = FILE_OPEN_REPARSE_POINT;
constexpr ULONG synchronous = FILE_SYNCHRONOUS_IO_NONALERT;
constexpr ULONG directory_file = FILE_DIRECTORY_FILE;
constexpr ULONG disposition_open = FILE_OPEN, disposition_create = FILE_CREATE, disposition_open_if = FILE_OPEN_IF;
int failure(DWORD code) {
    switch (code) {
    case ERROR_FILE_NOT_FOUND: case ERROR_PATH_NOT_FOUND: errno=ENOENT; break;
    case ERROR_ACCESS_DENIED: case ERROR_SHARING_VIOLATION: case ERROR_LOCK_VIOLATION: errno=EACCES; break;
    case ERROR_INVALID_HANDLE: errno=EBADF; break;
    case ERROR_NOT_ENOUGH_MEMORY: case ERROR_OUTOFMEMORY: errno=ENOMEM; break;
    case ERROR_TOO_MANY_OPEN_FILES: errno=EMFILE; break;
    case ERROR_FILE_EXISTS: case ERROR_ALREADY_EXISTS: errno=EEXIST; break;
    case ERROR_DISK_FULL: case ERROR_HANDLE_DISK_FULL: errno=ENOSPC; break;
    case ERROR_WRITE_PROTECT: errno=EROFS; break;
    case ERROR_DIRECTORY: errno=ENOTDIR; break;
    case ERROR_CANT_ACCESS_FILE: case ERROR_STOPPED_ON_SYMLINK: case ERROR_REPARSE_TAG_INVALID:
    case ERROR_REPARSE_TAG_MISMATCH: case ERROR_CANT_RESOLVE_FILENAME: errno=ELOOP; break;
    case ERROR_FILENAME_EXCED_RANGE: case ERROR_BUFFER_OVERFLOW: errno=ENAMETOOLONG; break;
    case ERROR_OPERATION_ABORTED: errno=EINTR; break;
    case ERROR_NOACCESS: errno=EFAULT; break;
    case ERROR_INVALID_PARAMETER: case ERROR_INVALID_NAME: case ERROR_NEGATIVE_SEEK: errno=EINVAL; break;
    case ERROR_READ_FAULT: case ERROR_WRITE_FAULT: case ERROR_IO_DEVICE: case ERROR_CRC: case ERROR_GEN_FAILURE: errno=EIO; break;
    case ERROR_NOT_SUPPORTED: case ERROR_INVALID_FUNCTION: errno=ENOTSUP; break;
    default: throw std::runtime_error("unmapped Windows file error " + std::to_string(code));
    }
    return -1;
}
int status_failure(NTSTATUS status) {
    // These statuses otherwise have host-specific/generic Win32 translations.
    switch (static_cast<std::uint32_t>(status)) {
    case 0xc000050b: case 0xc0000280: case 0x8000002d: errno=ELOOP; return -1; // reparse encountered/not handled/stopped.
    case 0xc00000ba: errno=EISDIR; return -1;
    default: return failure(RtlNtStatusToDosError(status));
    }
}
FileTime timestamp(LONGLONG ticks) {
    auto seconds = ticks / 10000000;
    auto fraction = ticks % 10000000;
    if (fraction < 0) { --seconds; fraction += 10000000; }
    return {seconds - 11644473600LL,fraction * 100};
}
bool information(HANDLE handle, FileInfo& output) {
    FILE_BASIC_INFO basic{};
    FILE_STANDARD_INFO standard{};
    FILE_STORAGE_INFO storage{};
    BY_HANDLE_FILE_INFORMATION identity{};
    if (!GetFileInformationByHandleEx(handle,FileBasicInfo,&basic,sizeof(basic)) ||
        !GetFileInformationByHandleEx(handle,FileStandardInfo,&standard,sizeof(standard)) ||
        !GetFileInformationByHandleEx(handle,FileStorageInfo,&storage,sizeof(storage)) ||
        !GetFileInformationByHandle(handle,&identity)) { failure(GetLastError()); return false; }
    FileInfo next{};
    next.device = identity.dwVolumeSerialNumber;
    next.inode = identity.nFileIndexLow; // Guest ABI, like POSIX, exposes low 32 bits.
    next.links = standard.NumberOfLinks;
    next.directory = standard.Directory != FALSE;
    next.regular = !next.directory;
    // These are compatibility mode bits, not a claim to expose Windows ACLs.
    // The kernel still checks actual access rights on every requested open.
    next.mode = static_cast<std::uint16_t>((next.directory ? 0040000 : 0100000) | 0444 |
        ((basic.FileAttributes & FILE_ATTRIBUTE_READONLY) ? 0 : 0222) | (next.directory ? 0111 : 0));
    next.size = standard.EndOfFile.QuadPart;
    next.blocks = standard.AllocationSize.QuadPart / 512;
    if (!storage.PhysicalBytesPerSectorForPerformance) { errno=ENOTSUP; return false; }
    next.block_size = storage.PhysicalBytesPerSectorForPerformance;
    next.atime = timestamp(basic.LastAccessTime.QuadPart);
    next.mtime = timestamp(basic.LastWriteTime.QuadPart);
    next.ctime = timestamp(basic.ChangeTime.QuadPart);
    next.birthtime = timestamp(basic.CreationTime.QuadPart);
    output = next;
    return true;
}
bool component_name(std::string_view name, std::wstring& output) {
    if (name.empty() || name == "." || name == ".." || name.find_first_of("/\\:") != name.npos || name.find('\0') != name.npos) {
        errno=EACCES; return false;
    }
    if (name.size() > 32767) { errno=ENAMETOOLONG; return false; }
    const auto size = MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,name.data(),static_cast<int>(name.size()),nullptr,0);
    if (!size) { errno=EINVAL; return false; }
    output.resize(static_cast<std::size_t>(size));
    if (MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,name.data(),static_cast<int>(name.size()),output.data(),size) != size) {
        errno=EINVAL; return false;
    }
    return true;
}
}
struct File::Impl {
    HANDLE handle = nullptr;
    bool directory = false, append = false;
    FileAccess access = FileAccess::Read;
    mutable std::mutex mutex;
    ~Impl() { const auto saved=errno; if (handle) CloseHandle(handle); errno=saved; }
    static std::unique_ptr<Impl> open(HANDLE parent, std::wstring_view name, const FileOpen& options,
                                      bool single_link, bool insensitive, bool directory_creation = false, bool metadata_only = false) {
        if (name.empty() || name.size() > 32767) { errno=ENAMETOOLONG; return {}; }
        if (options.directory && options.create && !directory_creation) { errno=EINVAL; return {}; }
        ACCESS_MASK desired = SYNCHRONIZE | FILE_READ_ATTRIBUTES;
        if (!metadata_only) switch (options.access) {
        case FileAccess::Read: desired |= FILE_READ_DATA; break;
        case FileAccess::Write: desired |= FILE_WRITE_DATA | FILE_APPEND_DATA; break;
        case FileAccess::ReadWrite: desired |= FILE_READ_DATA | FILE_WRITE_DATA | FILE_APPEND_DATA; break;
        default: errno=EINVAL; return {};
        }
        if (options.directory) desired |= FILE_TRAVERSE;
        UNICODE_STRING text{};
        text.Length = static_cast<USHORT>(name.size() * sizeof(wchar_t));
        text.MaximumLength = text.Length;
        text.Buffer = const_cast<PWSTR>(name.data());
        OBJECT_ATTRIBUTES attributes{};
        attributes.Length = sizeof(attributes);
        attributes.RootDirectory = parent;
        attributes.ObjectName = &text;
        attributes.Attributes = no_reparse | (insensitive ? OBJ_CASE_INSENSITIVE : 0);
        auto next = std::make_unique<Impl>();
        IO_STATUS_BLOCK io{};
        const auto disposition = options.create ? (options.exclusive ? disposition_create : disposition_open_if) : disposition_open;
        const auto status = NtCreateFile(&next->handle,desired,&attributes,&io,nullptr,FILE_ATTRIBUTE_NORMAL,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,disposition,
            synchronous | open_reparse | (options.directory ? directory_file : 0),nullptr,0);
        if (status < 0) { next->handle = nullptr; status_failure(status); return {}; }
        FILE_ATTRIBUTE_TAG_INFO tag{};
        if (!GetFileInformationByHandleEx(next->handle,FileAttributeTagInfo,&tag,sizeof(tag))) { failure(GetLastError()); return {}; }
        if (tag.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) { errno=ELOOP; return {}; }
        if (GetFileType(next->handle) != FILE_TYPE_DISK) { errno=ENOTSUP; return {}; }
        FileInfo info{};
        if (!information(next->handle,info)) return {};
        if (single_link && !info.directory && (!info.regular || info.links != 1)) { errno=EACCES; return {}; }
        next->directory = info.directory;
        next->access = options.access;
        next->append = options.append;
        if (options.truncate) {
            if (next->directory) { errno=EISDIR; return {}; }
            LARGE_INTEGER zero{};
            if (!SetFilePointerEx(next->handle,zero,nullptr,FILE_BEGIN) || !SetEndOfFile(next->handle)) { failure(GetLastError()); return {}; }
        }
        return next;
    }
    std::int64_t transfer(bool writing, void* data, std::size_t size, bool positioned, std::int64_t offset) {
        std::lock_guard lock(mutex);
        if (!handle) { errno=EBADF; return -1; }
        if (directory) { errno=EISDIR; return -1; }
        if ((writing && access == FileAccess::Read) || (!writing && access == FileAccess::Write)) { errno=EBADF; return -1; }
        if (size > std::numeric_limits<DWORD>::max() || (positioned && offset < 0)) { errno=EINVAL; return -1; }
        LARGE_INTEGER zero{}, saved{}, target{};
        if (positioned) {
            target.QuadPart = offset;
            if (!SetFilePointerEx(handle,zero,&saved,FILE_CURRENT) || !SetFilePointerEx(handle,target,nullptr,FILE_BEGIN))
                return failure(GetLastError());
        }
        DWORD done = 0, error = ERROR_SUCCESS;
        NTSTATUS native_status = 0;
        if (writing && append) {
            IO_STATUS_BLOCK io{};
            LARGE_INTEGER end{}; end.QuadPart = -1; // FILE_WRITE_TO_END_OF_FILE, atomic kernel append.
            native_status = NtWriteFile(handle,nullptr,nullptr,nullptr,&io,data,static_cast<ULONG>(size),&end,nullptr);
            if (native_status == 0x103) { // STATUS_PENDING.
                const auto wait = WaitForSingleObject(handle,INFINITE);
                if (wait != WAIT_OBJECT_0) {
                    error = wait == WAIT_FAILED ? GetLastError() : ERROR_GEN_FAILURE;
                    if (!error) error = ERROR_GEN_FAILURE;
                } else native_status = io.Status;
            }
            if (native_status >= 0 && !error) {
                if (io.Information > size) throw std::runtime_error("Windows append returned an invalid byte count");
                done = static_cast<DWORD>(io.Information);
            }
        } else if (!(writing ? WriteFile(handle,data,static_cast<DWORD>(size),&done,nullptr)
                             : ReadFile(handle,data,static_cast<DWORD>(size),&done,nullptr))) error = GetLastError();
        // Serialize positioned operations and restore position before exposing
        // any error; no concurrent caller sees the temporary seek.
        if (positioned && !SetFilePointerEx(handle,saved,nullptr,FILE_BEGIN)) return failure(GetLastError());
        if (!writing && error == ERROR_HANDLE_EOF) { error = ERROR_SUCCESS; done = 0; }
        if (error) return failure(error);
        if (native_status < 0) return status_failure(native_status);
        return done;
    }
};
File::File() = default;
File::~File() = default;
File::File(File&&) noexcept = default;
File& File::operator=(File&&) noexcept = default;
bool File::valid() const noexcept { if (!impl_) return false; std::lock_guard lock(impl_->mutex); return impl_->handle != nullptr; }
bool File::open_directory(const std::filesystem::path& input, bool allow_root_links, bool create) {
    if (allow_root_links && create) { errno=EINVAL; return false; }
    (void)allow_root_links; // Windows never follows a reparse point in a root.
    if (input.empty()) { errno=ENOENT; return false; }
    const auto path = std::filesystem::absolute(input);
    const auto drive = path.root_name().native();
    if (drive.size() != 2 || drive[1] != L':' || !((drive[0] >= L'A' && drive[0] <= L'Z') || (drive[0] >= L'a' && drive[0] <= L'z'))) {
        errno=ENOTSUP; return false; // UNC/device roots require a separate, verified anchor policy.
    }
    std::array<wchar_t,4096> device{};
    if (!QueryDosDeviceW(drive.c_str(),device.data(),static_cast<DWORD>(device.size()))) { failure(GetLastError()); return false; }
    const auto terminator = std::find(device.begin(),device.end(),L'\0');
    if (terminator == device.end()) { errno=ENAMETOOLONG; return false; }
    const std::wstring target(device.begin(),terminator);
    constexpr std::wstring_view prefix = L"\\Device\\";
    if (!target.starts_with(prefix) || target.size() == prefix.size() || target.find(L'\\',prefix.size()) != target.npos) {
        errno=ENOTSUP; return false; // Reject SUBST paths/redirectors hiding unwalked components.
    }
    FileOpen options;
    options.directory = true;
    auto current = Impl::open(nullptr,target + L"\\",options,false,true);
    if (!current) return false;
    options.create = create;
    for (const auto& part : path.relative_path()) {
        const auto& name = part.native();
        if (name.empty() || name == L".") continue;
        if (name == L".." || name.find_first_of(L"/\\:\0",0,4) != name.npos) { errno=EACCES; return false; }
        current = Impl::open(current->handle,name,options,false,true,create);
        if (!current) return false;
    }
    impl_ = std::move(current);
    return true;
}
bool File::duplicate_directory(File& output) const {
    if (&output == this) { errno=EINVAL; return false; }
    if (!impl_) { errno=EBADF; return false; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return false; }
    if (!impl_->directory) { errno=ENOTDIR; return false; }
    auto next = std::make_unique<Impl>();
    if (!DuplicateHandle(GetCurrentProcess(),impl_->handle,GetCurrentProcess(),&next->handle,0,FALSE,DUPLICATE_SAME_ACCESS)) {
        failure(GetLastError()); return false;
    }
    next->directory = true;
    output.impl_ = std::move(next);
    return true;
}
bool File::ensure_directory(std::string_view name, File& output) const {
    if (&output == this) { errno=EINVAL; return false; }
    std::wstring wide;
    if (!component_name(name,wide)) return false;
    if (!impl_) { errno=EBADF; return false; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return false; }
    if (!impl_->directory) { errno=ENOTDIR; return false; }
    FileOpen options;
    options.directory = options.create = true;
    auto next = Impl::open(impl_->handle,wide,options,false,false,true);
    if (!next) return false;
    output.impl_ = std::move(next);
    return true;
}
bool File::child_info(std::string_view name, FileInfo& output, bool& exists) const {
    std::wstring wide;
    if (!component_name(name,wide)) return false;
    if (!impl_) { errno=EBADF; return false; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return false; }
    if (!impl_->directory) { errno=ENOTDIR; return false; }
    // Query rights only: inspecting an entry must not require data access.
    auto child = Impl::open(impl_->handle,wide,{},false,false,false,true);
    if (!child) {
        if (errno != ENOENT) return false;
        exists = false;
        return true;
    }
    if (!information(child->handle,output)) return false;
    exists = true;
    return true;
}
bool File::open_child(std::string_view name, const FileOpen& options, bool single_link, File& output) const {
    if (&output == this) { errno=EINVAL; return false; }
    std::wstring wide;
    if (!component_name(name,wide)) return false;
    if (!impl_) { errno=EBADF; return false; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return false; }
    if (!impl_->directory) { errno=ENOTDIR; return false; }
    auto next = Impl::open(impl_->handle,wide,options,single_link,false);
    if (!next) return false;
    output.impl_ = std::move(next);
    return true;
}
bool File::stat(FileInfo& output) const {
    if (!impl_) { errno=EBADF; return false; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return false; }
    return information(impl_->handle,output);
}
std::int64_t File::read(void* data, std::size_t size) { if (!impl_) { errno=EBADF; return -1; } return impl_->transfer(false,data,size,false,0); }
std::int64_t File::read_at(void* data, std::size_t size, std::int64_t offset) { if (!impl_) { errno=EBADF; return -1; } return impl_->transfer(false,data,size,true,offset); }
std::int64_t File::write(const void* data, std::size_t size) { if (!impl_) { errno=EBADF; return -1; } return impl_->transfer(true,const_cast<void*>(data),size,false,0); }
std::int64_t File::write_at(const void* data, std::size_t size, std::int64_t offset) { if (!impl_) { errno=EBADF; return -1; } return impl_->transfer(true,const_cast<void*>(data),size,true,offset); }
std::int64_t File::seek(std::int64_t offset, int origin) {
    if (!impl_) { errno=EBADF; return -1; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return -1; }
    if (origin < 0 || origin > 2) { errno=EINVAL; return -1; }
    LARGE_INTEGER target{}, result{}; target.QuadPart=offset;
    if (!SetFilePointerEx(impl_->handle,target,&result,static_cast<DWORD>(origin))) return failure(GetLastError());
    return result.QuadPart;
}
int File::sync() {
    if (!impl_) { errno=EBADF; return -1; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return -1; }
    return FlushFileBuffers(impl_->handle) ? 0 : failure(GetLastError());
}
int File::truncate(std::int64_t size) {
    if (!impl_) { errno=EBADF; return -1; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return -1; }
    if (size < 0 || impl_->access == FileAccess::Read) { errno=EINVAL; return -1; }
    LARGE_INTEGER zero{}, saved{}, target{}; target.QuadPart=size;
    if (!SetFilePointerEx(impl_->handle,zero,&saved,FILE_CURRENT) || !SetFilePointerEx(impl_->handle,target,nullptr,FILE_BEGIN))
        return failure(GetLastError());
    const auto status = SetEndOfFile(impl_->handle);
    const auto error = status ? ERROR_SUCCESS : GetLastError();
    if (!SetFilePointerEx(impl_->handle,saved,nullptr,FILE_BEGIN)) return failure(GetLastError());
    return error ? failure(error) : 0;
}
int File::close() {
    if (!impl_) { errno=EBADF; return -1; }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->handle) { errno=EBADF; return -1; }
    const auto handle=std::exchange(impl_->handle,nullptr);
    return CloseHandle(handle) ? 0 : failure(GetLastError());
}
}

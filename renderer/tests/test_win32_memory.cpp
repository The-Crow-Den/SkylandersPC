// SPDX-License-Identifier: GPL-2.0-or-later
// Real placeholder/section operations. No GPU, guest image or mocked Win32 API.
#include <windows.h>
#include <sys/mman.h>
#include <array>
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <iostream>
#include <limits>
#include <source_location>
#include <stdexcept>
namespace {
void require(bool value, const std::source_location site = std::source_location::current()) {
    if (!value) throw std::runtime_error(std::string("renderer memory assertion at ") +
        site.file_name() + ":" + std::to_string(site.line()) + " errno=" + std::to_string(errno) +
        " native=" + std::to_string(GetLastError()));
}
MEMORY_BASIC_INFORMATION query(const void* address) {
    MEMORY_BASIC_INFORMATION info{};
    require(VirtualQuery(address,&info,sizeof(info)) == sizeof(info));
    return info;
}
}
int main() {
    try {
        SYSTEM_INFO system{}; GetSystemInfo(&system);
        const auto page = size_t(system.dwPageSize), granule = size_t(system.dwAllocationGranularity);
        require(page == 4096 && granule == 65536); // x86-64 Windows contract used by this port.
        constexpr uintptr_t begin = 0x3000000000ULL;
        constexpr size_t arena_size = 2*1024*1024;
        require(sky_reserve_arena(begin+1,begin+arena_size) < 0 && errno == EINVAL);
        require(sky_reserve_arena(begin,begin+arena_size) == 0);
        require(sky_reserve_arena(begin,begin+arena_size) == 0);
        require(sky_reserve_arena(begin,begin+2*arena_size) < 0 && errno == EBUSY);
        auto* base = reinterpret_cast<unsigned char*>(begin);
        require(mprotect(base,page,PROT_READ|PROT_WRITE) < 0 && errno == ENOMEM);
        require(sky_section_create(0) < 0 && errno == EINVAL);
        const auto fd = sky_section_create(4*granule);
        require(fd >= SKY_SECTION_FD_BASE);
        auto* first = static_cast<unsigned char*>(mmap(nullptr,4*granule,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0));
        require(first != MAP_FAILED);
        auto* second = static_cast<unsigned char*>(mmap(nullptr,4*granule,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0));
        require(second != MAP_FAILED && first != second);
        first[0] = 0x55; first[4*page] = 0x66;
        require(second[0] == 0x55 && second[4*page] == 0x66);
        // MEM_REPLACE_PLACEHOLDER permits page-aligned addresses and offsets,
        // including PS4 16 KiB pages. Every returned address must be exact.
        auto* guest = base+4*page;
        require(mmap(guest,4*page,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_FIXED,fd,static_cast<off_t>(4*page)) == guest);
        require(guest[0] == 0x66);
        guest[0] = 0x77; require(first[4*page] == 0x77);
        require(mmap(guest,4*page,PROT_READ,MAP_SHARED|MAP_FIXED_NOREPLACE,fd,0) == MAP_FAILED && errno == EEXIST);
        require(mmap(base+1,page,PROT_READ,MAP_SHARED|MAP_FIXED,fd,0) == MAP_FAILED && errno == EINVAL);
        require(mmap(nullptr,page,PROT_READ,MAP_SHARED,fd,static_cast<off_t>(page)) == MAP_FAILED && errno == EINVAL);
        require(mmap(base+arena_size-page,2*page,PROT_READ,MAP_SHARED|MAP_FIXED,fd,0) == MAP_FAILED && errno == EINVAL);
        require(mmap(base,granule,PROT_READ,MAP_SHARED|MAP_FIXED,fd,static_cast<off_t>(4*granule)) == MAP_FAILED && errno == EINVAL);
        require(guest[0] == 0x77);
        require(mmap(base,page,PROT_READ,MAP_PRIVATE|MAP_FIXED,fd,0) == MAP_FAILED && errno == ENOTSUP);
        require(mmap(base,page,PROT_READ|0x100,MAP_SHARED|MAP_FIXED,fd,0) == MAP_FAILED);
        require(mmap(base,page,PROT_READ,MAP_SHARED|MAP_FIXED,-2,0) == MAP_FAILED);
        require(mmap(base,std::numeric_limits<size_t>::max(),PROT_READ,MAP_SHARED|MAP_FIXED,fd,0) == MAP_FAILED);
        auto* reserved = base+2*granule;
        require(mmap(reserved,granule,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0) == reserved);
        require(mmap(reserved,granule,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0) == MAP_FAILED && errno == EEXIST);
        require(mprotect(reserved,granule,PROT_READ|PROT_WRITE) == 0);
        require(reserved[0] == 0 && reserved[granule-1] == 0);
        reserved[0] = 0x33; reserved[granule-1] = 0x44;
        require(mprotect(reserved,page,PROT_READ) == 0);
        require(query(reserved).Protect == PAGE_READONLY);
        require(munmap(reserved+page,page) == 0);
        require(reserved[0] == 0x33 && reserved[granule-1] == 0x44);
        require(query(reserved).Protect == PAGE_READONLY);
        require(query(reserved+page).State == MEM_RESERVE);
        require(mprotect(reserved+page,page,PROT_READ|PROT_WRITE) < 0 && errno == ENOMEM);
        require(mprotect(reserved,2*page,PROT_READ|PROT_WRITE) < 0 && errno == ENOMEM);
        require(query(reserved).Protect == PAGE_READONLY);
        // Carving and remapping the middle keeps both aliases and page
        // protections of the original view's surviving left/right ranges.
        auto* wide = base+4*granule;
        require(mmap(wide,granule,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_FIXED,fd,0) == wide);
        wide[0] = 0x91; wide[granule-1] = 0x92;
        require(mprotect(wide,page,PROT_READ) == 0);
        const auto other = sky_section_create(granule);
        require(other >= SKY_SECTION_FD_BASE);
        require(mmap(wide+page,page,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_FIXED,other,static_cast<off_t>(page)) == wide+page);
        require(wide[0] == 0x91 && wide[granule-1] == 0x92 && wide[page] == 0);
        require(query(wide).Protect == PAGE_READONLY);
        require(query(wide+granule-page).Protect == PAGE_READWRITE);
        require(fallocate(fd,0,0,1) < 0 && errno == ENOTSUP && first[0] == 0x91);
        require(fallocate(fd,FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE,-1,1) < 0 && errno == EINVAL);
        require(fallocate(fd,FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE,static_cast<off_t>(4*granule),1) < 0 && errno == EINVAL);
        require(fallocate(fd,FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE,static_cast<off_t>(4*page),1) == 0);
        require(guest[0] == 0 && first[0] == 0x91);
        require(madvise(first,page,MADV_DONTNEED) < 0 && errno == ENOTSUP && first[0] == 0x91);
        auto* private_bytes = static_cast<unsigned char*>(mmap(nullptr,3*page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
        require(private_bytes != MAP_FAILED);
        require(mmap(private_bytes+page,page,PROT_READ,MAP_SHARED|MAP_FIXED,fd,0) == MAP_FAILED && errno == EINVAL);
        private_bytes[0] = 0x31; private_bytes[3*page-1] = 0x32;
        require(munmap(private_bytes,page) < 0 && errno == ENOTSUP && private_bytes[3*page-1] == 0x32);
        require(madvise(private_bytes,3*page,999) < 0 && errno == ENOTSUP && private_bytes[0] == 0x31);
        require(mprotect(private_bytes,page,PROT_READ) == 0);
        require(madvise(private_bytes,3*page,MADV_DONTNEED) == 0);
        require(private_bytes[0] == 0 && private_bytes[3*page-1] == 0);
        require(query(private_bytes).Protect == PAGE_READONLY);
        require(munmap(private_bytes,3*page) == 0);
        auto* lazy = mmap(nullptr,2*page,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_NORESERVE,-1,0);
        require(lazy != MAP_FAILED && query(lazy).State == MEM_RESERVE);
        require(mprotect(lazy,page,PROT_READ|PROT_WRITE) == 0);
        require(*static_cast<unsigned char*>(lazy) == 0);
        require(munmap(lazy,2*page) == 0);
        auto* code = static_cast<unsigned char*>(mmap(nullptr,page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
        require(code != MAP_FAILED);
        constexpr std::array<unsigned char,6> returns_42{0xb8,42,0,0,0,0xc3};
        std::copy(returns_42.begin(),returns_42.end(),code);
        require(mprotect(code,page,PROT_READ|PROT_EXEC) == 0 && query(code).Protect == PAGE_EXECUTE_READ);
        require(reinterpret_cast<int(*)()>(code)() == 42);
        require(munmap(code,page) == 0);
        require(sky_section_close(fd) < 0 && errno == EBUSY);
        require(munmap(base,arena_size) == 0);
        require(sky_section_close(fd) == 0 && sky_section_close(other) == 0);
        require(first[0] == 0x91 && second[0] == 0x91); // Views survive fd closure.
        require(munmap(first,4*granule) == 0 && munmap(second,4*granule) == 0);
        require(sky_section_close(fd) < 0 && errno == EBADF);
        void* a = nullptr; void* b = nullptr;
        require(sky_win32_shared_views(granule,&a,&b) && a != b);
        *static_cast<unsigned char*>(a) = 0xab;
        require(*static_cast<unsigned char*>(b) == 0xab);
        require(munmap(a,granule) == 0 && *static_cast<unsigned char*>(b) == 0xab && munmap(b,granule) == 0);
        std::cout << "Windows renderer placeholder memory tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}

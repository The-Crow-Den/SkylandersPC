// SPDX-License-Identifier: GPL-2.0-or-later
// renderer Windows: mmap, munmap, mprotect and fallocate (sys/mman.h, renderer_posix_c.h) with the
// Linux semantics the runtime's guest memory relies on (src/runtime_memory.c).
//
// - A section fd (sky_section_create) plays the memfd's part: a pagefile-backed section; mmap of
//   it maps a view, fallocate(PUNCH_HOLE) zeroes a range of it.
// - The guest's address range is one placeholder reservation (sky_reserve_arena). A MAP_FIXED
//   mapping inside it replaces exactly its range, as on Linux: whatever was there (views,
//   reservations) is cut out first, placeholders are coalesced and split, and the parts of views
//   outside the range are mapped again with the page protections they had. An anonymous
//   PROT_NONE mapping there (a reservation) stays a placeholder; munmap leaves one.
// - Outside the arena: VirtualAlloc, or a view anywhere. Partial ordinary
//   unmaps are refused, never expanded to free neighboring bytes. Placeholder
//   replacements use the documented page-alignment exception; ordinary fixed
//   views still require allocation-granularity addresses and offsets.
#include <windows.h>

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <limits>
#include <set>
#include <mutex>
#include <unordered_map>
#include <vector>

#include <sys/mman.h>

namespace {

DWORD PageProtection(int prot) {
    if (prot & PROT_EXEC) {
        return (prot & PROT_WRITE) ? PAGE_EXECUTE_READWRITE
               : (prot & PROT_READ) ? PAGE_EXECUTE_READ
                                    : PAGE_EXECUTE;
    }
    if (prot & PROT_WRITE) return PAGE_READWRITE;
    if (prot & PROT_READ) return PAGE_READONLY;
    return PAGE_NOACCESS;
}

[[noreturn]] void Fail(const char* what, uintptr_t address, uint64_t size) {
    std::fprintf(stderr, "STOP: %s failed at %#llx (+%#llx): Windows error %lu\n", what,
                 (unsigned long long)address, (unsigned long long)size, GetLastError());
    std::fflush(stderr);
    std::exit(21);
}

// Sections (fds from sky_section_create).
constexpr int SectionFdBase = SKY_SECTION_FD_BASE;
struct Section {
    HANDLE handle = nullptr;
    uint64_t size = 0;
    unsigned char* whole = nullptr; ///< a view of all of it (zeroing)
    bool owned = false; ///< backing for one private arena mapping, not a caller-owned fd
};
std::unordered_map<int, Section> sections;
int next_section = SectionFdBase;

// The arena: [arena_begin, arena_end) as pieces, each a placeholder or a view.
struct Piece {
    uintptr_t end;
    bool view;
    int fd;          ///< the view's section
    uint64_t offset; ///< the view's offset in it
    bool occupied = false; ///< distinguish a guest PROT_NONE reservation from free arena space
};
std::map<uintptr_t, Piece> pieces; ///< by start
uintptr_t arena_begin = 0, arena_end = 0;
struct OutsidePiece { size_t size; bool view; };
std::map<uintptr_t, OutsidePiece> outside;
std::recursive_mutex memory_mutex;
size_t PageSize() {
    static const auto size = [] { SYSTEM_INFO info{}; GetSystemInfo(&info); return size_t(info.dwPageSize); }();
    return size;
}
size_t Granularity() {
    static const auto size = [] { SYSTEM_INFO info{}; GetSystemInfo(&info); return size_t(info.dwAllocationGranularity); }();
    return size;
}
bool Range(uintptr_t start, size_t size) {
    return size && size % PageSize() == 0 && start % PageSize() == 0 &&
        size <= std::numeric_limits<uintptr_t>::max() - start;
}
bool ValidProtection(int prot) { return !(prot & ~(PROT_READ | PROT_WRITE | PROT_EXEC)); }
bool IntersectsArena(uintptr_t start, uintptr_t end) {
    return arena_begin && start < arena_end && end > arena_begin;
}
bool Occupied(uintptr_t start, uintptr_t end) {
    auto it = pieces.upper_bound(start);
    if (it == pieces.begin()) return false;
    --it;
    for (; it != pieces.end() && it->first < end; ++it)
        if (!it->second.occupied) return false;
    return true;
}
bool OwnPrivate(uintptr_t start, uintptr_t end) {
    auto it = outside.upper_bound(start);
    if (it == outside.begin()) return false;
    --it;
    return !it->second.view && end <= it->first + it->second.size;
}
void ReapPrivateSections() {
    std::set<int> used;
    for (const auto& [start,piece] : pieces) { (void)start; if (piece.view) used.insert(piece.fd); }
    for (auto it = sections.begin(); it != sections.end();) {
        if (!it->second.owned || used.count(it->first)) { ++it; continue; }
        if (!UnmapViewOfFile(it->second.whole) || !CloseHandle(it->second.handle)) {
            std::fputs("STOP: cannot release private renderer section\n",stderr);
            std::exit(21);
        }
        it = sections.erase(it);
    }
}

bool InArena(uintptr_t a, uintptr_t b) {
    return arena_begin && a >= arena_begin && b <= arena_end;
}

void MapView(uintptr_t start, uintptr_t end, int fd, uint64_t offset, DWORD protect) {
    const Section& section = sections.at(fd);
    // A view cannot start without access; protections change after.
    const DWORD initial = protect == PAGE_NOACCESS ? PAGE_READWRITE : protect;
    void* view = MapViewOfFile3(section.handle, GetCurrentProcess(), reinterpret_cast<void*>(start), offset,
                        end - start, MEM_REPLACE_PLACEHOLDER, initial, nullptr, 0);
    if (!view || reinterpret_cast<uintptr_t>(view) != start) {
        if (view) UnmapViewOfFile2(GetCurrentProcess(),view,0);
        std::fprintf(stderr, "Memory: view of section %d offset %#llx (of %#llx) at %#llx failed\n", fd,
                     (unsigned long long)offset, (unsigned long long)section.size,
                     (unsigned long long)start);
        Fail("MapViewOfFile3", start, end - start);
    }
    DWORD old = 0;
    if (initial != protect &&
        !VirtualProtect(reinterpret_cast<void*>(start), end - start, protect, &old)) {
        Fail("VirtualProtect", start, end - start);
    }
    if ((protect == PAGE_EXECUTE || protect == PAGE_EXECUTE_READ || protect == PAGE_EXECUTE_READWRITE) &&
        !FlushInstructionCache(GetCurrentProcess(),reinterpret_cast<void*>(start),end-start)) {
        Fail("FlushInstructionCache",start,end-start);
    }
}

struct ProtectionRun {
    uintptr_t start, end;
    DWORD protect;
};

void SaveProtections(uintptr_t start, uintptr_t end, std::vector<ProtectionRun>& runs) {
    for (uintptr_t at = start; at < end;) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<void*>(at), &info, sizeof(info))) {
            Fail("VirtualQuery", at, 0);
        }
        const uintptr_t next =
            std::min<uintptr_t>(reinterpret_cast<uintptr_t>(info.BaseAddress) + info.RegionSize, end);
        runs.push_back({at, next, info.Protect});
        at = next;
    }
}

/// Leaves [a, b) one placeholder piece (what was mapped there is gone; views around it stay).
std::map<uintptr_t, Piece>::iterator Carve(uintptr_t a, uintptr_t b) {
    auto first = pieces.upper_bound(a);
    --first; // the piece holding a
    auto last = pieces.lower_bound(b); // first piece starting at or after b
    // Already exactly one placeholder?
    if (std::next(first) == last && !first->second.view && first->first == a &&
        first->second.end == b) {
        return first;
    }
    const uintptr_t lo = first->first;
    const uintptr_t hi = std::prev(last)->second.end;
    const Piece left = first->second, right = std::prev(last)->second;
    const uintptr_t right_start = std::prev(last)->first;
    const bool keep_left = left.view && lo < a;
    const bool keep_right = right.view && b < hi;
    std::vector<ProtectionRun> runs;
    if (keep_left) SaveProtections(lo, a, runs);
    if (keep_right) SaveProtections(b, hi, runs);
    size_t count = 0;
    for (auto it = first; it != last; ++it, ++count) {
        if (it->second.view &&
            !UnmapViewOfFile2(GetCurrentProcess(), reinterpret_cast<void*>(it->first),
                              MEM_PRESERVE_PLACEHOLDER)) {
            Fail("UnmapViewOfFile2", it->first, it->second.end - it->first);
        }
    }
    if (count > 1 && !VirtualFree(reinterpret_cast<void*>(lo), hi - lo,
                                  MEM_RELEASE | MEM_COALESCE_PLACEHOLDERS)) {
        Fail("coalescing placeholders", lo, hi - lo);
    }
    pieces.erase(first, last);
    if (lo < a) {
        if (!VirtualFree(reinterpret_cast<void*>(lo), a - lo, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER)) {
            Fail("splitting a placeholder", lo, a - lo);
        }
        pieces[lo] = Piece{a, false, -1, 0, left.occupied};
        if (keep_left) {
            pieces[lo] = Piece{a, true, left.fd, left.offset, true};
            MapView(lo, a, left.fd, left.offset, PAGE_READWRITE);
        }
    }
    if (b < hi) {
        if (!VirtualFree(reinterpret_cast<void*>(a), b - a, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER)) {
            Fail("splitting a placeholder", a, b - a);
        }
        pieces[b] = Piece{hi, false, -1, 0, right.occupied};
        if (keep_right) {
            const uint64_t offset = right.offset + (b - right_start);
            pieces[b] = Piece{hi, true, right.fd, offset, true};
            MapView(b, hi, right.fd, offset, PAGE_READWRITE);
        }
    }
    for (const ProtectionRun& run : runs) {
        DWORD old = 0;
        if (run.protect != PAGE_READWRITE &&
            !VirtualProtect(reinterpret_cast<void*>(run.start), run.end - run.start, run.protect, &old)) {
            Fail("restoring page protections", run.start, run.end - run.start);
        }
    }
    return pieces.emplace(a, Piece{b, false, -1, 0}).first;
}

} // namespace

extern "C" {

int sky_section_create(unsigned long long size) {
    std::scoped_lock lock{memory_mutex};
    if (!size || size % PageSize()) { errno=EINVAL; return -1; }
    if (next_section == std::numeric_limits<int>::max()) { errno=EMFILE; return -1; }
    Section section;
    section.size = size;
    section.handle = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_EXECUTE_READWRITE | SEC_COMMIT,
                                        DWORD(size >> 32), DWORD(size), nullptr);
    if (!section.handle) {
        std::fprintf(stderr,
                     "Runtime: cannot create %llu MiB of guest memory (Windows error %lu): is the "
                     "page file large enough?\n",
                     (unsigned long long)(size >> 20), GetLastError());
        errno = ENOMEM;
        return -1;
    }
    section.whole = static_cast<unsigned char*>(MapViewOfFile3(
        section.handle, GetCurrentProcess(), nullptr, 0, size, 0, PAGE_READWRITE, nullptr, 0));
    if (!section.whole) {
        CloseHandle(section.handle);
        errno = ENOMEM;
        return -1;
    }
    const int fd = next_section++;
    sections.emplace(fd, section);
    return fd;
}

int sky_reserve_arena(unsigned long long begin, unsigned long long end) {
    std::scoped_lock lock{memory_mutex};
    if (!begin || begin % Granularity() || end <= begin || end % PageSize()) { errno=EINVAL; return -1; }
    if (arena_begin) {
        if (arena_begin == begin && arena_end == end) return 0;
        errno=EBUSY; return -1;
    }
    void* allocation = VirtualAlloc2(nullptr, reinterpret_cast<void*>(begin), end - begin,
                       MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS, nullptr, 0);
    if (!allocation || reinterpret_cast<uintptr_t>(allocation) != begin) {
        if (allocation) VirtualFree(allocation,0,MEM_RELEASE);
        errno=ENOMEM;
        std::fprintf(stderr, "STOP: cannot reserve the guest address range %#llx-%#llx (Windows "
                             "error %lu)\n",
                     (unsigned long long)begin, (unsigned long long)end, GetLastError());
        return -1;
    }
    arena_begin = begin;
    arena_end = end;
    pieces.emplace(begin, Piece{end, false, -1, 0});
    return 0;
}

int sky_section_close(int fd) {
    std::scoped_lock lock{memory_mutex};
    const auto it = sections.find(fd);
    if (it == sections.end()) { errno=EBADF; return -1; }
    for (const auto& [start,piece] : pieces) {
        (void)start;
        if (piece.view && piece.fd == fd) { errno=EBUSY; return -1; }
    }
    if (it->second.whole && !UnmapViewOfFile(it->second.whole)) { errno=EIO; return -1; }
    it->second.whole = nullptr;
    if (!CloseHandle(it->second.handle)) { errno=EIO; return -1; }
    sections.erase(it);
    return 0;
}

int fallocate(int fd, int mode, off_t offset, off_t length) {
    std::scoped_lock lock{memory_mutex};
    if (mode != (FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE)) { errno=ENOTSUP; return -1; }
    const auto it = sections.find(fd);
    if (it == sections.end()) { errno=EBADF; return -1; }
    if (offset < 0 || length <= 0 || uint64_t(offset) > it->second.size ||
        uint64_t(length) > it->second.size - uint64_t(offset)) { errno=EINVAL; return -1; }
    std::memset(it->second.whole + offset, 0, size_t(length));
    return 0;
}

void* mmap(void* address, size_t size, int prot, int flags, int fd, off_t offset) {
    std::scoped_lock lock{memory_mutex};
    const auto start = reinterpret_cast<uintptr_t>(address);
    const bool fixed = (flags & (MAP_FIXED | MAP_FIXED_NOREPLACE)) != 0;
    const bool section = fd >= SKY_SECTION_FD_BASE && sections.count(fd);
    constexpr int supported = MAP_SHARED | MAP_PRIVATE | MAP_FIXED | MAP_FIXED_NOREPLACE | MAP_ANONYMOUS | MAP_NORESERVE;
    if ((flags & ~supported) || !ValidProtection(prot)) { errno=ENOTSUP; return MAP_FAILED; }
    if (!size || size % PageSize() || offset < 0 ||
        (fixed && (!start || !Range(start,size))) ||
        ((flags & MAP_FIXED) && (flags & MAP_FIXED_NOREPLACE))) { errno=EINVAL; return MAP_FAILED; }
    const auto kind = flags & (MAP_SHARED | MAP_PRIVATE);
    if (kind != MAP_SHARED && kind != MAP_PRIVATE) { errno=EINVAL; return MAP_FAILED; }
    if (fd != -1 && !section) { errno=ENODEV; return MAP_FAILED; }
    if (section) {
        if (kind != MAP_SHARED || (flags & MAP_ANONYMOUS)) { errno=ENOTSUP; return MAP_FAILED; }
        if (uint64_t(offset) > sections.at(fd).size || size > sections.at(fd).size-uint64_t(offset)) {
            errno=EINVAL; return MAP_FAILED;
        }
    } else {
        if (!(flags & MAP_ANONYMOUS) || offset) { errno=EINVAL; return MAP_FAILED; }
        if (kind != MAP_PRIVATE) { errno=ENOTSUP; return MAP_FAILED; }
    }
    if (fixed && IntersectsArena(start,start+size) && !InArena(start,start+size)) { errno=EINVAL; return MAP_FAILED; }
    if (fixed && InArena(start,start+size)) {
        if (uint64_t(offset) % PageSize()) { errno=EINVAL; return MAP_FAILED; }
    } else if ((fixed && start % Granularity()) || (section && uint64_t(offset) % Granularity())) {
        errno=EINVAL; return MAP_FAILED;
    }
    if (fixed && InArena(start, start + size)) {
        if ((flags & MAP_FIXED_NOREPLACE)) {
            auto it = pieces.upper_bound(start);
            --it;
            for (; it != pieces.end() && it->first < start+size; ++it) {
                if (it->second.occupied) { errno=EEXIST; return MAP_FAILED; }
            }
        }
        // Allocate private backing before replacing anything already mapped.
        int own = -1;
        if (!section && prot != PROT_NONE) {
            own = sky_section_create(size);
            if (own < 0) return MAP_FAILED;
            sections.at(own).owned = true;
        }
        auto piece = Carve(start, start + size);
        if (section) {
            piece->second = Piece{start + size, true, fd, uint64_t(offset), true};
            MapView(start, start + size, fd, uint64_t(offset), PageProtection(prot));
        } else if (prot != PROT_NONE) {
            // Private anonymous memory in the arena: a view of a section of its own.
            piece->second = Piece{start + size, true, own, 0, true};
            MapView(start, start + size, own, 0, PageProtection(prot));
        }
        piece->second.occupied = true;
        ReapPrivateSections();
        return address;
    }
    if (section) {
        void* view = MapViewOfFile3(sections.at(fd).handle, GetCurrentProcess(), fixed ? address : nullptr,
                                    uint64_t(offset), size, 0, PageProtection(prot | PROT_READ | PROT_WRITE),
                                    nullptr, 0);
        if (!view || (fixed && view != address)) {
            if (view) UnmapViewOfFile(view);
            errno = ENOMEM;
            return MAP_FAILED;
        }
        DWORD old = 0;
        if (prot != (PROT_READ | PROT_WRITE) && !VirtualProtect(view,size,PageProtection(prot),&old)) {
            UnmapViewOfFile(view); errno=EACCES; return MAP_FAILED;
        }
        if ((prot & PROT_EXEC) && !FlushInstructionCache(GetCurrentProcess(),view,size)) {
            UnmapViewOfFile(view); errno=EIO; return MAP_FAILED;
        }
        outside.emplace(reinterpret_cast<uintptr_t>(view),OutsidePiece{size,true});
        return view;
    }
    void* p = VirtualAlloc(address, size, prot == PROT_NONE && (flags & MAP_NORESERVE)
                                              ? MEM_RESERVE
                                              : MEM_RESERVE | MEM_COMMIT,
                           PageProtection(prot));
    if (!p || (fixed && p != address)) {
        if (p) VirtualFree(p, 0, MEM_RELEASE);
        errno = fixed ? EEXIST : ENOMEM;
        return MAP_FAILED;
    }
    if ((prot & PROT_EXEC) && !FlushInstructionCache(GetCurrentProcess(),p,size)) {
        VirtualFree(p,0,MEM_RELEASE); errno=EIO; return MAP_FAILED;
    }
    outside.emplace(reinterpret_cast<uintptr_t>(p),OutsidePiece{size,false});
    return p;
}

int munmap(void* address, size_t size) {
    std::scoped_lock lock{memory_mutex};
    const auto start = reinterpret_cast<uintptr_t>(address);
    if (!Range(start,size)) { errno=EINVAL; return -1; }
    if (InArena(start,start+size)) {
        auto piece = Carve(start,start+size);
        piece->second.occupied = false;
        ReapPrivateSections();
        return 0;
    }
    // Windows cannot release a partial ordinary allocation/view. Refuse it
    // rather than silently freeing neighboring bytes as the old shim did.
    const auto it = outside.find(start);
    if (it == outside.end() || it->second.size != size) { errno=ENOTSUP; return -1; }
    const bool ok = it->second.view ? UnmapViewOfFile(address) != 0 : VirtualFree(address,0,MEM_RELEASE) != 0;
    if (!ok) { errno=EIO; return -1; }
    outside.erase(it);
    return 0;
}

int mprotect(void* address, size_t size, int prot) {
    std::scoped_lock lock{memory_mutex};
    const auto start = reinterpret_cast<uintptr_t>(address), end = start+size;
    if (!Range(start,size) || !ValidProtection(prot)) { errno=EINVAL; return -1; }
    // Validate holes before changing protections. Free arena placeholders are
    // implementation reservations, not guest mappings.
    for (auto at = start; at < end;) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<void*>(at),&info,sizeof(info))) { errno=ENOMEM; return -1; }
        const auto next = std::min(reinterpret_cast<uintptr_t>(info.BaseAddress)+info.RegionSize,end);
        const bool arena = InArena(at,next);
        if (arena && !Occupied(at,next)) { errno=ENOMEM; return -1; }
        if (info.State != MEM_COMMIT && !(info.State == MEM_RESERVE && (arena || OwnPrivate(at,next)))) {
            errno=ENOMEM; return -1;
        }
        at = next;
    }
    for (auto at = start; at < end;) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<void*>(at),&info,sizeof(info))) { errno=ENOMEM; return -1; }
        auto next = std::min(reinterpret_cast<uintptr_t>(info.BaseAddress)+info.RegionSize,end);
        if (info.State == MEM_RESERVE && prot != PROT_NONE) {
            if (InArena(at,next)) {
                // Materialize a guest's anonymous PROT_NONE reservation in the
                // exact placeholder range. Backing is real, initially zero.
                if (mmap(reinterpret_cast<void*>(at),next-at,prot,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0)==MAP_FAILED) return -1;
            } else {
                auto* committed = VirtualAlloc(reinterpret_cast<void*>(at),next-at,MEM_COMMIT,PageProtection(prot));
                if (committed != reinterpret_cast<void*>(at)) { errno=ENOMEM; return -1; }
            }
        } else if (info.State == MEM_COMMIT) {
            DWORD old = 0;
            if (!VirtualProtect(reinterpret_cast<void*>(at),next-at,PageProtection(prot),&old)) { errno=EACCES; return -1; }
        }
        at = next;
    }
    if ((prot & PROT_EXEC) && !FlushInstructionCache(GetCurrentProcess(),address,size)) { errno=EIO; return -1; }
    return 0;
}

int madvise(void* address, size_t size, int advice) {
    std::scoped_lock lock{memory_mutex};
    const auto start = reinterpret_cast<uintptr_t>(address), end = start+size;
    if (!Range(start,size)) { errno=EINVAL; return -1; }
    if (advice != MADV_DONTNEED) { errno=ENOTSUP; return -1; }
    std::vector<ProtectionRun> runs;
    for (auto at = start; at < end;) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<void*>(at),&info,sizeof(info))) { errno=ENOMEM; return -1; }
        if (info.State != MEM_COMMIT || info.Type != MEM_PRIVATE || (info.Protect & PAGE_GUARD)) {
            errno=ENOTSUP; return -1;
        }
        const auto next = std::min(reinterpret_cast<uintptr_t>(info.BaseAddress)+info.RegionSize,end);
        runs.push_back({at,next,info.Protect});
        at = next;
    }
    // MEM_RESET does not guarantee zeroes. Decommit/recommit does, while
    // retaining the original reservation, address and access protection.
    for (const auto& run : runs) {
        auto* at = reinterpret_cast<void*>(run.start);
        if (!VirtualFree(at,run.end-run.start,MEM_DECOMMIT)) { errno=EIO; return -1; }
        if (VirtualAlloc(at,run.end-run.start,MEM_COMMIT,run.protect) != at) { errno=ENOMEM; return -1; }
        if ((run.protect == PAGE_EXECUTE || run.protect == PAGE_EXECUTE_READ || run.protect == PAGE_EXECUTE_READWRITE) &&
            !FlushInstructionCache(GetCurrentProcess(),at,run.end-run.start)) { errno=EIO; return -1; }
    }
    return 0;
}

int sky_win32_shared_views(size_t size, void** first, void** second) {
    std::scoped_lock lock{memory_mutex};
    if (!size || size % PageSize() || !first || !second || first == second) { errno=EINVAL; return 0; }
    const HANDLE section = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE,
                                              DWORD(static_cast<unsigned long long>(size) >> 32),
                                              DWORD(size), nullptr);
    if (!section) {
        return 0;
    }
    *first = MapViewOfFile(section, FILE_MAP_ALL_ACCESS, 0, 0, size);
    *second = MapViewOfFile(section, FILE_MAP_ALL_ACCESS, 0, 0, size);
    CloseHandle(section); // the views keep it
    if (!*first || !*second) {
        if (*first) UnmapViewOfFile(*first);
        if (*second) UnmapViewOfFile(*second);
        *first = *second = MAP_FAILED;
        return 0;
    }
    outside.emplace(reinterpret_cast<uintptr_t>(*first),OutsidePiece{size,true});
    outside.emplace(reinterpret_cast<uintptr_t>(*second),OutsidePiece{size,true});
    return 1;
}

} // extern "C"

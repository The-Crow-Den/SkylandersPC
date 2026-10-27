// SPDX-License-Identifier: GPL-3.0-or-later
// Original SKYPS401 pack loader. Never executes guest code.
#include <algorithm>
#include <array>
#include <bit>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <sys/mman.h>
#include <unistd.h>

#include "hle/pure_libc.hpp"
#include "diagnostic.hpp"
#include <cstdlib>

namespace {
using u64 = std::uint64_t;
constexpr u64 kImportFlag = u64{1} << 63;
constexpr u64 kMaxFile = 512 * 1024 * 1024;
constexpr u64 kMaxImage = 512 * 1024 * 1024;
constexpr u64 kMaxRecords = 1000000;

[[noreturn]] void fail(const std::string& message) { throw std::runtime_error(message); }

u64 add(u64 a, u64 b) {
    if (b > std::numeric_limits<u64>::max() - a) fail("integer range overflow");
    return a + b;
}

u64 mul(u64 a, u64 b) {
    if (a != 0 && b > std::numeric_limits<u64>::max() / a) fail("table size overflow");
    return a * b;
}

std::size_t index(u64 value) {
    if (value > std::numeric_limits<std::size_t>::max()) fail("host size range exceeded");
    return static_cast<std::size_t>(value);
}

std::string quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
        else out << c;
    }
    out << '"';
    return out.str();
}

bool utf8(const std::string& text) {
    for (std::size_t i = 0; i < text.size();) {
        const auto c = static_cast<unsigned char>(text[i++]);
        if (c < 0x80) continue;
        unsigned more = 0;
        std::uint32_t code = 0, minimum = 0;
        if (c >= 0xC2 && c <= 0xDF) { more = 1; code = c & 0x1Fu; minimum = 0x80; }
        else if (c >= 0xE0 && c <= 0xEF) { more = 2; code = c & 0x0Fu; minimum = 0x800; }
        else if (c >= 0xF0 && c <= 0xF4) { more = 3; code = c & 0x07u; minimum = 0x10000; }
        else return false;
        if (more > text.size() - i) return false;
        while (more--) {
            const auto next = static_cast<unsigned char>(text[i++]);
            if ((next & 0xC0u) != 0x80u) return false;
            code = (code << 6) | (next & 0x3Fu);
        }
        if (code < minimum || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF)) return false;
    }
    return true;
}

struct Segment { u64 va, memory_size, file_size, flags, payload; };
struct Relocation { u64 target, type, symbol; std::int64_t addend; };

class Pack {
public:
    std::vector<unsigned char> bytes;
    u64 entry{}, base{}, size{}, tables_end{};
    std::vector<Segment> segments;
    std::vector<Relocation> relocations;
    std::vector<std::string> imports;

    void range(u64 offset, u64 length) const {
        if (offset > bytes.size() || length > bytes.size() - offset) fail("pack range outside file");
    }

    u64 integer(u64 offset) const {
        range(offset, 8);
        u64 value = 0;
        for (unsigned i = 0; i < 8; ++i) value |= u64{bytes[index(offset) + i]} << (8 * i);
        return value;
    }

    bool contains(u64 address, u64 length, bool executable = false) const {
        if (length == 0) return false;
        for (const auto& segment : segments) {
            if (address >= segment.va && address - segment.va < segment.memory_size &&
                length <= segment.memory_size - (address - segment.va) &&
                (!executable || (segment.flags & 1))) return true;
        }
        return false;
    }

    explicit Pack(const std::string& path) {
        std::ifstream stream(path, std::ios::binary | std::ios::ate);
        if (!stream) fail("cannot open pack");
        const auto length = stream.tellg();
        if (length < 0 || static_cast<u64>(length) > kMaxFile) fail("pack exceeds inspection size limit");
        bytes.resize(static_cast<std::size_t>(length));
        stream.seekg(0);
        if (!bytes.empty() && !stream.read(reinterpret_cast<char*>(bytes.data()), length)) fail("cannot read pack");
        range(0, 56);
        constexpr std::array<unsigned char, 8> magic{'S','K','Y','P','S','4','0','1'};
        if (!std::equal(magic.begin(), magic.end(), bytes.begin())) fail("unsupported pack magic");
        entry = integer(8); base = integer(16); size = integer(24);
        const auto segment_count = integer(32), relocation_count = integer(40), import_count = integer(48);
        if (segment_count == 0 || segment_count > 4096 || relocation_count > kMaxRecords ||
            import_count > kMaxRecords) fail("invalid pack record counts");
        if (size == 0 || size > kMaxImage) fail("invalid guest image size");
        const auto image_end = add(base, size);
        const auto relocation_start = add(56, mul(segment_count, 40));
        const auto import_start = add(relocation_start, mul(relocation_count, 32));
        tables_end = add(import_start, mul(import_count, 128));
        range(0, tables_end);
        std::vector<std::pair<u64, u64>> memory_ranges, payload_ranges;
        for (u64 i = 0; i < segment_count; ++i) {
            const auto pos = add(56, mul(i, 40));
            Segment segment{integer(pos), integer(pos + 8), integer(pos + 16), integer(pos + 24), integer(pos + 32)};
            if (segment.memory_size == 0 || segment.file_size > segment.memory_size || segment.flags > 7 ||
                segment.va < base || add(segment.va, segment.memory_size) > image_end) fail("invalid segment bounds/flags");
            if (segment.file_size) {
                if (segment.payload < tables_end) fail("payload overlaps pack tables");
                range(segment.payload, segment.file_size);
                payload_ranges.emplace_back(segment.payload, add(segment.payload, segment.file_size));
            }
            memory_ranges.emplace_back(segment.va, add(segment.va, segment.memory_size));
            segments.push_back(segment);
        }
        const auto nonoverlapping = [](auto ranges, const char* message) {
            std::sort(ranges.begin(), ranges.end());
            for (std::size_t i = 1; i < ranges.size(); ++i) if (ranges[i].first < ranges[i-1].second) fail(message);
        };
        nonoverlapping(memory_ranges, "overlapping segment memory ranges");
        nonoverlapping(payload_ranges, "overlapping segment payload ranges");
        if (!contains(entry, 1, true)) fail("guest entry is outside executable segments");
        for (u64 i = 0; i < import_count; ++i) {
            const auto pos = add(import_start, mul(i, 128));
            std::string text;
            u64 j = 0;
            for (; j < 128 && bytes[index(pos + j)] != 0; ++j) text.push_back(static_cast<char>(bytes[index(pos + j)]));
            if (j == 0 || j == 128 || !utf8(text)) fail("invalid import UTF-8/name terminator");
            for (; j < 128; ++j) if (bytes[index(pos + j)] != 0) fail("import padding is not zero");
            imports.push_back(std::move(text));
        }
        std::vector<std::pair<u64, u64>> targets;
        for (u64 i = 0; i < relocation_count; ++i) {
            const auto pos = add(relocation_start, mul(i, 32));
            Relocation relocation{integer(pos), integer(pos + 8), integer(pos + 16),
                                  std::bit_cast<std::int64_t>(integer(pos + 24))};
            const bool imported = (relocation.type & kImportFlag) != 0;
            const auto type = relocation.type & ~kImportFlag;
            if (type != 1 && type != 6 && type != 7 && type != 8 && type != 16) fail("unsupported x86-64 relocation type");
            if (!contains(relocation.target, 8)) fail("relocation target outside segment memory");
            if (imported) {
                if (type == 8 || type == 16 || relocation.symbol >= imports.size()) fail("invalid imported relocation index/type");
            } else if (type == 16) {
                if (relocation.symbol < 1 || relocation.symbol > 16 || relocation.addend != 0)
                    fail("invalid local DTPMOD64 module ID/addend");
            } else if (type == 8) {
                if (relocation.symbol != 0) fail("relative relocation must have zero symbol");
            } else if (!contains(relocation.symbol, 1)) fail("defined relocation symbol outside guest image segments");
            if ((type == 6 || type == 7) && relocation.addend != 0) fail("GLOB_DAT/JUMP_SLOT require zero addend");
            targets.emplace_back(relocation.target, add(relocation.target, 8));
            relocations.push_back(relocation);
        }
        nonoverlapping(targets, "overlapping relocation targets");
    }
};

class Arena {
    void* memory_ = MAP_FAILED;
    std::size_t length_{};
    std::vector<u64> import_addresses_;
    bool diagnostic_ = false;
public:
    Arena() = default;
    Arena(const Arena&) = delete;
    Arena& operator=(const Arena&) = delete;
    ~Arena() { if (memory_ != MAP_FAILED) munmap(memory_, length_); }

    bool resolved(u64 id) const { return !diagnostic_ && id < import_addresses_.size() && import_addresses_[index(id)] != 0; }

    void load(const Pack& pack, SkyDiagnostic* diagnostic = nullptr) {
        diagnostic_ = diagnostic != nullptr;
        const auto raw_page = sysconf(_SC_PAGESIZE);
        if (raw_page <= 0) fail("cannot determine page size");
        const auto page = static_cast<u64>(raw_page);
        if (pack.base % page) fail("guest image base must be page aligned for load");
        const auto rounded = add(pack.size, page - 1) / page * page;
        length_ = index(rounded);
#if defined(__linux__) && defined(MAP_FIXED_NOREPLACE)
        if (pack.base > std::numeric_limits<std::uintptr_t>::max()) fail("guest base exceeds host pointer range");
        auto* requested = reinterpret_cast<void*>(static_cast<std::uintptr_t>(pack.base));
        memory_ = mmap(requested, length_, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
        if (memory_ == MAP_FAILED) fail(std::string("mmap failed: ") + std::strerror(errno));
        if (memory_ != requested) fail("kernel did not honor no-replace guest mapping");
#else
        fail("fixed guest loading requires Linux MAP_FIXED_NOREPLACE; inspect mode remains available");
#endif
        auto* memory = static_cast<unsigned char*>(memory_);
        for (std::size_t i = 0; i < pack.imports.size(); ++i) {
            import_addresses_.push_back(diagnostic ? diagnostic->address(i) :
                static_cast<u64>(reinterpret_cast<std::uintptr_t>(resolve_pure_libc(pack.imports[i]))));
        }
        for (const auto& segment : pack.segments) {
            if (segment.file_size) std::memcpy(memory + index(segment.va - pack.base),
                                             pack.bytes.data() + index(segment.payload), index(segment.file_size));
        }
        // Wide signed arithmetic permits host address < guest base without
        // unsigned-wrap relocations. Unresolved slots retain their original bytes.
        const __int128 slide = static_cast<__int128>(reinterpret_cast<std::uintptr_t>(memory_)) - pack.base;
        for (const auto& relocation : pack.relocations) {
            const bool imported = (relocation.type & kImportFlag) != 0;
            if (imported && !diagnostic_ && !resolved(relocation.symbol)) continue;
            const auto type = relocation.type & ~kImportFlag;
            __int128 value = slide + relocation.addend;
            if (imported) value = static_cast<__int128>(import_addresses_[index(relocation.symbol)]) + relocation.addend;
            else if (type == 16) value = relocation.symbol;
            else if (type != 8) value += relocation.symbol;
            if (value < 0 || value > std::numeric_limits<u64>::max()) fail("relocation value outside 64-bit address range");
            const auto target = index(relocation.target - pack.base);
            for (unsigned i = 0; i < 8; ++i) memory[target + i] = static_cast<unsigned char>(static_cast<u64>(value) >> (i * 8));
        }
        const bool unresolved = std::any_of(pack.relocations.begin(), pack.relocations.end(),
                                            [this](const auto& r) { return (r.type & kImportFlag) && !resolved(r.symbol); });
        std::vector<int> permissions(index(rounded / page), PROT_NONE);
        for (const auto& segment : pack.segments) {
            const int flags = ((segment.flags & 4) ? PROT_READ : 0) | ((segment.flags & 2) ? PROT_WRITE : 0) |
                              ((segment.flags & 1) && (!unresolved || diagnostic_) ? PROT_EXEC : 0);
            const auto begin = (segment.va - pack.base) / page;
            const auto end = add(segment.va - pack.base, segment.memory_size - 1) / page;
            for (u64 p = begin; p <= end; ++p) permissions[index(p)] |= flags;
        }
        for (std::size_t begin = 0; begin < permissions.size();) {
            std::size_t end = begin + 1;
            while (end < permissions.size() && permissions[end] == permissions[begin]) ++end;
            if (mprotect(memory + begin * index(page), (end - begin) * index(page), permissions[begin]) != 0)
                fail(std::string("mprotect failed: ") + std::strerror(errno));
            begin = end;
        }
    }
};

void summary(const Pack& pack, bool loaded, const Arena& arena) {
    std::set<u64> unresolved, resolved;
    u64 unresolved_relocations = 0, resolved_relocations = 0, internal = 0;
    for (const auto& relocation : pack.relocations) {
        if (relocation.type & kImportFlag) {
            if (arena.resolved(relocation.symbol)) { ++resolved_relocations; resolved.insert(relocation.symbol); }
            else { ++unresolved_relocations; unresolved.insert(relocation.symbol); }
        }
        else ++internal;
    }
    std::cout << "{\n  \"format\": \"SKYPS401\",\n  \"status\": " << quote(loaded ? "loaded; entry not called" : "inspected; not mapped")
              << ",\n  \"mapping_mode\": " << quote(loaded ? "fixed-noreplace" : "none")
              << ",\n  \"base_slide\": " << (loaded ? "0" : "null")
              << ",\n  \"guest_entry\": " << pack.entry << ",\n  \"image_base\": " << pack.base
              << ",\n  \"image_size\": " << pack.size << ",\n  \"segments\": " << pack.segments.size()
              << ",\n  \"internal_relocations\": " << internal << ",\n  \"internal_relocations_applied\": " << (loaded ? internal : 0)
              << ",\n  \"import_count\": " << pack.imports.size() << ",\n  \"unresolved_import_relocations\": " << unresolved_relocations
              << ",\n  \"resolved_import_relocations\": " << resolved_relocations
              << ",\n  \"import_resolution_attempted\": " << (loaded ? "true" : "false")
              << ",\n  \"executable_permissions_enabled\": " << (loaded && unresolved_relocations == 0 ? "true" : "false")
              << ",\n  \"guest_executed\": false,\n  \"unresolved_imports\": [";
    bool first = true;
    for (u64 id : unresolved) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << "\n    {\"index\":" << id << ",\"name\":" << quote(pack.imports[index(id)]) << '}';
    }
    std::cout << "\n  ],\n  \"resolved_imports\": [";
    first = true;
    for (u64 id : resolved) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << "\n    {\"index\":" << id << ",\"name\":" << quote(pack.imports[index(id)]) << '}';
    }
    std::cout << "\n  ]\n}\n";
}

SkyBootPlan read_boot_plan(const std::string& path, const Pack& pack) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream || stream.tellg() < 24 || stream.tellg() > 24 + 16 * 48)
        fail("invalid boot plan size");
    std::vector<unsigned char> bytes(static_cast<std::size_t>(stream.tellg()));
    stream.seekg(0);
    if (!stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size())))
        fail("cannot read boot plan");
    if (std::memcmp(bytes.data(), "SKYBOOT1", 8)) fail("invalid boot plan magic");
    const auto number = [&](std::size_t offset) {
        u64 value = 0;
        std::memcpy(&value, bytes.data() + offset, 8);
        return value;
    };
    SkyBootPlan plan;
    plan.process_param = number(8);
    const auto count = number(16);
    if (count == 0 || count > 16 || bytes.size() != 24 + count * 48)
        fail("invalid boot module count");
    if (plan.process_param && !pack.contains(plan.process_param, 56)) fail("process parameter outside image");
    for (std::size_t i = 0; i < count; ++i) {
        const auto offset = 24 + i * 48;
        SkyBootModule module{number(offset), number(offset + 8), number(offset + 16),
                             number(offset + 24), number(offset + 32), number(offset + 40)};
        if (module.id != i + 1 || (module.init && !pack.contains(module.init, 1, true)))
            fail("invalid boot module identity/initializer");
        if (!module.tls_align || module.tls_align > 4096 || (module.tls_align & (module.tls_align - 1)) ||
            module.tls_memsz > 2 * 1024 * 1024 || module.tls_filesz > module.tls_memsz ||
            (module.tls_memsz && !pack.contains(module.tls_address, module.tls_memsz)) ||
            (!module.tls_memsz && module.tls_address)) fail("invalid boot TLS template");
        plan.modules.push_back(module);
    }
    return plan;
}
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "usage: skylanders-native-host [--inspect|--load] PACK\n       skylanders-native-host --trace-start PACK IMPORT_TYPES\nOnly --trace-start attempts guest entry, stopping at imports/faults.\n";
            return 0;
        }
        bool load = false;
        bool trace = false;
        std::string path;
        if ((argc >= 4 && argc <= 6) && std::string(argv[1]) == "--trace-start") {
            trace = true;
            path = argv[2];
        } else if (argc == 2 && std::string(argv[1]) != "--load" && std::string(argv[1]) != "--inspect") path = argv[1];
        else if (argc == 3 && (std::string(argv[1]) == "--load" || std::string(argv[1]) == "--inspect")) {
            load = std::string(argv[1]) == "--load";
            path = argv[2];
        } else {
            std::cerr << "usage: skylanders-native-host [--inspect|--load] PACK\nGuest entry is never called.\n";
            return 2;
        }
        Pack pack(path);
        Arena arena;
        if (trace) {
            std::setvbuf(stdout, nullptr, _IONBF, 0);
            std::ifstream stream(argv[3], std::ios::binary | std::ios::ate);
            if (!stream || stream.tellg() < 0 || static_cast<u64>(stream.tellg()) != pack.imports.size())
                fail("import types must contain one byte per import");
            std::vector<unsigned char> types(pack.imports.size());
            stream.seekg(0);
            if (!types.empty() && !stream.read(reinterpret_cast<char*>(types.data()), static_cast<std::streamsize>(types.size())))
                fail("cannot read import types");
            SkyDiagnostic diagnostic(pack.imports, types);
            const auto boot = argc >= 5 ? read_boot_plan(argv[4], pack) : SkyBootPlan{};
            arena.load(pack, &diagnostic);
            diagnostic.enter(pack.entry, boot, argc == 6 ? argv[5] : "");
        }
        if (load) arena.load(pack);
        summary(pack, load, arena);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}

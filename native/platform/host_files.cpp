// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_files.hpp"
#include "host_random.hpp"
#include <array>
#include <cerrno>
#include <cstdio>
#include <string>
namespace SkyHost {
bool File::write_atomic(std::string_view name, const void* data, std::size_t size, bool durable) const {
    if (!data && size) { errno=EINVAL; return false; }
    File parent;
    if (!duplicate_directory(parent)) return false;
    auto acceptable = [&] {
        FileInfo info{};
        bool exists = false;
        if (!parent.child_info(name,info,exists)) return false;
        if (exists && (!info.regular || info.links != 1)) { errno=EACCES; return false; }
        return true;
    };
    if (!acceptable()) return false;
    File temporary;
    std::string source;
    for (unsigned attempt = 0; attempt < 16; ++attempt) {
        std::array<std::uint8_t,16> bytes{};
        if (!random_bytes(bytes)) { errno=EIO; return false; }
        source = ".pending-";
        constexpr char hex[] = "0123456789abcdef";
        for (const auto byte : bytes) { source += hex[byte >> 4]; source += hex[byte & 15]; }
        if (parent.create_temporary(source,temporary)) break;
        if (errno != EEXIST) return false;
    }
    if (!temporary.valid()) { errno=EEXIST; return false; }
    bool published = false;
    auto finish = [&](bool ok) {
        const auto saved = errno;
        if (!published && !parent.discard_temporary(temporary,source)) return false;
        errno = saved;
        return ok;
    };
    try {
        std::size_t done = 0;
        while (done < size) {
            const auto count = temporary.write(static_cast<const unsigned char*>(data)+done,size-done);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) { if (!count) errno=EIO; return finish(false); }
            done += static_cast<std::size_t>(count);
        }
        if (durable) {
            int result;
            do { result = temporary.sync(); } while (result < 0 && errno == EINTR);
            if (result) return finish(false);
        }
        if (!acceptable()) return finish(false);
        const bool ok = parent.publish_temporary(temporary,source,name,published,durable);
        return finish(ok);
    } catch (...) {
        if (!published) {
            try {
                if (!parent.discard_temporary(temporary,source))
                    std::fprintf(stderr,"failed to remove unpublished metadata sibling: errno=%d\n",errno);
            } catch (...) {
                std::fputs("exception while removing unpublished metadata sibling\n",stderr);
            }
        }
        throw;
    }
}
}

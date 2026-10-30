// SPDX-License-Identifier: GPL-2.0-or-later
// The texture cache: uploads of images the guest (or the GPU, through buffers) changed.
#include <cstring>
#include "textures/texture_cache.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <unordered_map>
#include <utility>

#include <xxhash.h>

#include "renderer_toggles.h"
#include "buffers/buffer_cache.h"
#include "render/runtime.h"
#include "render/scheduler.h"

namespace VideoCore {

namespace {

bool EnvFlag(const char* name) {
    const char* env = std::getenv(name);
    return env && env[0] == '1';
}

/// SKY_RENDERER_IMAGE_SYNC_LOG: the images refreshed most per 5 s (any reason), with their flags.
void NoteRefresh(const Image& image) {
    static const bool log = std::getenv("SKY_RENDERER_IMAGE_SYNC_LOG") != nullptr;
    if (!log) {
        return;
    }
    // Render-target-sized images: every refresh, with the GPU frame (flicker hunting).
    if (image.info.size.width >= 640 && image.info.size.height >= 360) {
        static std::mutex big_mutex;
        static std::unordered_map<VAddr, u64> last_frame;
        static u32 big = 0;
        const u64 frame = SkyStats::gpu_frames.load(std::memory_order_relaxed);
        std::scoped_lock big_lock{big_mutex};
        const u64 last = std::exchange(last_frame[image.info.guest_address], frame);
        if (last + 1 < frame && big++ < 3000) {
            std::printf("Image sync: big refresh %#llx %ux%u fmt %u tile %u flags %#x frame %llu\n",
                        (unsigned long long)image.info.guest_address, image.info.size.width,
                        image.info.size.height, u32(image.info.pixel_format),
                        u32(image.info.tile_mode), u32(image.flags),
                        (unsigned long long)SkyStats::gpu_frames.load(std::memory_order_relaxed));
        }
    }
    if (True(image.flags & ImageFlagBits::GpuDirty)) {
        static std::atomic<u32> printed{0};
        if (printed.fetch_add(1) < 100) {
            std::printf("Image sync: refresh of %#llx (%ux%u) from memory the GPU wrote, flags "
                        "%#x\n",
                        (unsigned long long)image.info.guest_address, image.info.size.width,
                        image.info.size.height, u32(image.flags));
        }
    }
    struct Refreshes {
        u64 count = 0, bytes = 0;
        u32 width = 0, height = 0, format = 0, tiling = 0, flags = 0;
    };
    static std::mutex mutex;
    static std::unordered_map<VAddr, Refreshes> refreshes;
    static auto window_start = std::chrono::steady_clock::now();
    std::scoped_lock lk{mutex};
    auto& r = refreshes[image.info.guest_address];
    r = {r.count + 1, r.bytes + image.info.guest_size, image.info.size.width,
         image.info.size.height, u32(image.info.pixel_format), u32(image.info.tile_mode),
         r.flags | u32(image.flags)};
    const auto now = std::chrono::steady_clock::now();
    if (now - window_start < std::chrono::seconds(5)) {
        return;
    }
    std::vector<std::pair<VAddr, Refreshes>> top(refreshes.begin(), refreshes.end());
    std::ranges::sort(top, std::greater{}, [](const auto& e) { return e.second.bytes; });
    std::string text;
    for (size_t i = 0; i < std::min<size_t>(top.size(), 5); ++i) {
        const auto& [address, e] = top[i];
        text += fmt::format(" {:#x} {}x{} fmt {} tile {}: {}x {:.0f} MB flags {:#x};", address,
                            e.width, e.height, e.format, e.tiling, e.count, e.bytes / 1e6, e.flags);
    }
    std::printf("Image refreshes (5 s, %zu images):%s\n", refreshes.size(), text.c_str());
    refreshes.clear();
    window_start = now;
}

/// SKY_RENDERER_UPLOAD_DUMP_DIR (diagnostics, movie planes): the guest bytes of the first 240
/// refreshes of images at least 1900 texels wide, as read for the upload, named
/// uNNNN_<addr>_<w>x<h>_fmt<f>_tile<t>_pitch<p>_frame<gpu frame>.raw.
void DumpUpload(const Image& image) {
    static const char* dir = std::getenv("SKY_RENDERER_UPLOAD_DUMP_DIR");
    if (!dir || image.info.size.width < 1900) {
        return;
    }
    static std::atomic<u32> count{0};
    const u32 n = count.fetch_add(1);
    if (n >= 240) {
        return;
    }
    const auto& info = image.info;
    char path[512];
    std::snprintf(path, sizeof(path), "%s/u%04u_%llx_%ux%u_fmt%u_tile%u_pitch%u_frame%llu.raw", dir, n,
                  (unsigned long long)info.guest_address, info.size.width, info.size.height,
                  u32(info.pixel_format), u32(info.tile_mode), info.pitch,
                  (unsigned long long)SkyStats::gpu_frames.load(std::memory_order_relaxed));
    if (FILE* f = std::fopen(path, "wb")) {
        std::fwrite(std::bit_cast<const void*>(info.guest_address), 1, info.guest_size, f);
        std::fclose(f);
    }
}

} // namespace

void TextureCache::RefreshImage(Image& image) {
    WatchImage(image, "refresh entered");
    if (False(image.flags & ImageFlagBits::Dirty) || image.info.num_samples > 1) {
        return;
    }
    SkyStats::Timer timer{SkyStats::t_refresh};
    const ImageInfo& info = image.info;

    // Maybe written (a page under it was, not it): compared by its first 8x8 texels.
    if (True(image.flags & ImageFlagBits::MaybeCpuDirty) &&
        False(image.flags & ImageFlagBits::CpuDirty)) {
        const u32 w = std::min(info.size.width, 8u);
        const u32 h = std::min(info.size.height, 8u);
        const u32 bytes = (info.props.is_block ? (w + 3) / 4 : w) *
                          (info.props.is_block ? (h + 3) / 4 : h) * (info.num_bits / 8);
        const u64 hash = XXH3_64bits(std::bit_cast<const u8*>(info.guest_address), bytes);
        if (image.hash == hash) {
            image.flags &= ~ImageFlagBits::MaybeCpuDirty;
            return;
        }
        image.hash = hash;
    }

    const u32 layers = info.resources.layers;
    const u32 levels = info.resources.levels;
    NoteRefresh(image);
    DumpUpload(image);
    SkyStats::image_upload_bytes.fetch_add(info.guest_size, std::memory_order_relaxed);

    // A GPU-written image is reuploaded only where the guest's copy changed (by level hashes):
    // not over what the GPU rendered with a stale copy.
    // Every upload of such an image keeps the hashes, the first one too (a new image is
    // GpuDirty): else the first refresh after the GPU wrote it (a CPU write elsewhere in its
    // page) found no hash and uploaded unchanged memory over the GPU's data. The character
    // creator's exposure (1x1, written by a compute shader) went to 0: no character (#178).
    const bool gpu_modified = True(image.flags & ImageFlagBits::GpuModified);
    const bool gpu_written = gpu_modified && False(image.flags & ImageFlagBits::GpuDirty);
    boost::container::small_vector<vk::BufferImageCopy, 14> copies;
    for (u32 level = 0; level < levels; ++level) {
        const auto& layout = info.mips_layout[level];
        if (gpu_modified) {
            const u64 hash = XXH3_64bits(
                std::bit_cast<const u8*>(info.guest_address) + layout.offset, layout.size);
            if (gpu_written && image.mip_hashes[level] == hash) {
                continue;
            }
            image.mip_hashes[level] = hash;
        }
        const u32 width = std::max(info.size.width >> level, 1u);
        const u32 height = std::max(info.size.height >> level, 1u);
        const u32 depth = info.props.is_volume ? std::max(info.size.depth >> level, 1u) : 1u;
        copies.push_back({
            .bufferOffset = layout.offset,
            .bufferRowLength = layout.pitch,
            .bufferImageHeight = layout.height,
            .imageSubresource{
                .aspectMask = image.aspect_mask & ~vk::ImageAspectFlagBits::eStencil,
                .mipLevel = level,
                .baseArrayLayer = 0,
                .layerCount = layers,
            },
            .imageOffset = {0, 0, 0},
            .imageExtent = {layout.pitch ? std::min(layout.pitch, width) : width,
                            layout.height ? std::min(layout.height, height) : height, depth},
        });
    }
    WatchImage(image, copies.empty() ? "refresh: nothing to copy" : "refresh: uploading");
    if (copies.empty()) {
        image.flags &= ~ImageFlagBits::Dirty;
        return;
    }

    scheduler.EndRendering();
    const auto [source, source_offset] =
        buffer_cache.ObtainBufferForImage(info.guest_address, info.guest_size);
    const auto [linear, linear_offset] = detiler.DetileImage(source, source_offset, info);
    for (auto& copy : copies) {
        copy.bufferOffset += linear_offset;
    }
    runtime.UploadImage(&image, linear, copies);
}

} // namespace VideoCore

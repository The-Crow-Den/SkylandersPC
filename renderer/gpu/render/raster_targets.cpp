// SPDX-License-Identifier: GPL-2.0-or-later
// renderer render: Rasterizer, render targets: special passes (fast clear elimination, resolve, depth
// copies), target lookup, the render pass (BeginRendering) and the UI placement.

#include "render/raster_internal.h"
#include <set>
#include <tuple>
#include <cstdlib>
#include <cstdio>

namespace Vulkan {

namespace {
// Optional bounded inventory of actual bound attachments, not presentation size.
void TraceTargetSize(const VideoCore::Image& image, bool depth) {
    static const bool enabled = [] { const auto* p = std::getenv("SKY_RENDERER_TARGET_SIZE_TRACE"); return p && p[0] == '1'; }();
    if (!enabled) return;
    static std::set<std::tuple<u32,u32,u32,bool>> seen;
    const auto& info = image.info;
    const auto key = std::make_tuple(info.size.width, info.size.height, info.num_samples, depth);
    if (seen.size() < 128 && seen.insert(key).second)
        std::printf("Bound render target: %ux%u samples=%u depth=%u\n", info.size.width, info.size.height, info.num_samples, depth);
}

/// What a draw is: a draw, nothing, or a pass the color/depth control registers ask for.
enum class DrawPass {
    Draw,
    Skip,               ///< FMask decompression (nothing to do), or no primitive type
    EliminateFastClear, ///< CB_COLOR_CONTROL.MODE: writes the fast clear color
    Resolve,            ///< MRT0 resolved into MRT1
    DepthStencilCopy,   ///< no color, forced dirty/valid depth or stencil to another surface
};

struct DrawPassInfo {
    DrawPass pass;
    bool depth_copy = false;
    bool stencil_copy = false;
};

DrawPassInfo DrawPassOf(const Gcn::Regs& regs) {
    using Mode = Gcn::ColorControl::OperationMode;
    switch (regs.color_control.mode) {
    case Mode::EliminateFastClear:
        return {DrawPass::EliminateFastClear};
    case Mode::FmaskDecompress:
        return {DrawPass::Skip};
    case Mode::Resolve:
        return {DrawPass::Resolve};
    default:
        break;
    }
    if (regs.primitive_type == Gcn::PrimitiveType::None) {
        return {DrawPass::Skip};
    }
    // Games copy one depth/stencil surface to another with color off and the forced dirty and
    // valid bits, without a pixel shader: the copy is done here.
    const auto& db = regs.depth_buffer;
    const auto& force = regs.depth_render_override;
    const bool depth_copy = force.force_z_dirty && force.force_z_valid && db.DepthValid() &&
                            db.DepthWriteValid() && db.DepthAddress() != db.DepthWriteAddress();
    const bool stencil_copy = force.force_stencil_dirty && force.force_stencil_valid &&
                              db.StencilValid() && db.StencilWriteValid() &&
                              db.StencilAddress() != db.StencilWriteAddress();
    if (regs.color_control.mode == Mode::Disable && (depth_copy || stencil_copy)) {
        return {DrawPass::DepthStencilCopy, depth_copy, stencil_copy};
    }
    return {DrawPass::Draw};
}

} // namespace

bool Rasterizer::FilterDrawPasses() const {
    return DrawPassOf(Regs()).pass == DrawPass::Draw;
}

bool Rasterizer::FilterDraw() {
    const auto info = DrawPassOf(Regs());
    switch (info.pass) {
    case DrawPass::Draw:
        return true;
    case DrawPass::Skip:
        break;
    case DrawPass::EliminateFastClear:
        EliminateFastClear();
        break;
    case DrawPass::Resolve:
        Resolve();
        break;
    case DrawPass::DepthStencilCopy:
        DepthStencilCopy(info.depth_copy, info.stencil_copy);
        break;
    }
    return false;
}

template <typename... Parts>
VideoCore::ImageId Rasterizer::FindTargetMemoized(VideoCore::TextureCache::ImageDesc& desc,
                                                  LastTarget& last, auto&& make_desc,
                                                  const Parts&... parts) {
    static_assert((sizeof(Parts) + ...) <= 256, "target memo key too large");
    std::array<u8, 256> key{};
    u32 key_size = 0;
    const auto append = [&](const auto& part) {
        std::memcpy(key.data() + key_size, &part, sizeof(part));
        key_size += sizeof(part);
    };
    (append(parts), ...);
    const u64 generation = texture_cache.RegistryGeneration();
    const bool memo_enabled = !SkyToggle::Disabled(SkyToggle::TextureBindingMemo);
    if (memo_enabled && last.generation == generation && last.key_size == key_size &&
        std::memcmp(last.key.data(), key.data(), key_size) == 0) {
        texture_cache.MarkFound(last.image_id);
        return last.image_id;
    }
    const auto remember = [&](VideoCore::ImageId image_id) {
        last.key = key;
        last.key_size = key_size;
        last.generation = generation;
        last.image_id = image_id;
    };
    u64 hash = 0xCBF29CE484222325ull;
    for (u32 i = 0; i < key_size; i += 8) {
        u64 word;
        std::memcpy(&word, key.data() + i, 8);
        hash = (hash ^ word) * 0x100000001B3ull;
        hash ^= hash >> 29;
    }
    auto& memo = target_memo[hash % target_memo.size()];
    if (memo.generation == generation && memo.key_size == key_size &&
        std::memcmp(memo.key.data(), key.data(), key_size) == 0 && memo_enabled) {
        desc = memo.desc;
        texture_cache.MarkFound(memo.image_id);
        remember(memo.image_id);
        return memo.image_id;
    }
    make_desc();
    const VideoCore::ImageId image_id = texture_cache.FindImage(desc);
    if (generation == texture_cache.RegistryGeneration()) {
        memo.key = key;
        memo.key_size = key_size;
        memo.generation = generation;
        memo.image_id = image_id;
        memo.desc = desc;
        remember(image_id);
    } else {
        last.generation = ~0ULL;
    }
    return image_id;
}

void Rasterizer::PrepareRenderState(const GraphicsPipeline* pipeline) {
    SKY_RENDERER_SECTION(PrepareRenderState);
    // Prefetch render targets to handle overlaps with bound textures (e.g. mipgen)
    const auto& key = pipeline->GetGraphicsKey();
    const auto& regs = Regs();
    if (regs.color_control.degamma_enable) {
        LOG_WARNING(Render_Vulkan, "Color buffers require gamma correction");
    }

    const bool skip_cb_binding =
        regs.color_control.mode == Gcn::ColorControl::OperationMode::Disable;
    for (s32 cb = 0; cb < std::bit_width(key.mrt_mask); ++cb) {
        auto& [image_id, desc] = cb_descs[cb];
        const auto& col_buf = regs.color_buffers[cb];
        const u32 target_mask = regs.color_target_mask.GetMask(cb);
        if (skip_cb_binding || !col_buf || !target_mask || (key.mrt_mask & (1 << cb)) == 0) {
            image_id = {};
            continue;
        }
        const auto& hint = CbExtent(cb);
        const u32 tag = 1;
        image_id = bound_images.emplace_back(FindTargetMemoized(
            desc, last_targets[cb], [&] { std::construct_at(&desc, col_buf, hint); }, tag,
            col_buf, hint));
        auto& image = texture_cache.GetImage(image_id);
        image.binding.is_target = 1u;
        TraceTargetSize(image, false);
    }

    if ((regs.depth_control.depth_enable && regs.depth_buffer.DepthValid()) ||
        (regs.depth_control.stencil_enable && regs.depth_buffer.StencilValid())) {
        const auto htile_address = regs.depth_htile_data_base.GetAddress();
        const auto& hint = DbExtent();
        auto& [image_id, desc] = db_desc;
        const u32 tag = 2;
        image_id = bound_images.emplace_back(FindTargetMemoized(
            desc, last_targets[Gcn::NUM_COLOR_BUFFERS],
            [&] {
                std::construct_at(&desc, regs.depth_buffer, regs.depth_view, regs.depth_control,
                                  htile_address, hint);
            },
            tag, regs.depth_buffer, regs.depth_view, regs.depth_control, htile_address, hint));
        auto& image = texture_cache.GetImage(image_id);
        image.binding.is_target = 1u;
        TraceTargetSize(image, true);
    } else {
        db_desc.first = {};
    }
}

void Rasterizer::EliminateFastClear() {
    // The fast clear color is written where the CMASK says the target is still cleared.
    const auto& col_buf = Regs().color_buffers[0];
    if (!col_buf || !col_buf.info.fast_clear) {
        return;
    }
    VideoCore::TextureCache::ImageDesc desc(col_buf, CbExtent(0));
    const auto image_id = texture_cache.FindImage(desc);
    texture_cache.FindRenderTarget(image_id, desc);
    const VAddr cmask = col_buf.CmaskAddress();
    if (!texture_cache.IsMetaCleared(cmask, col_buf.view.slice_start)) {
        return;
    }
    for (u32 slice = col_buf.view.slice_start; slice <= col_buf.view.slice_max; ++slice) {
        texture_cache.TouchMeta(cmask, slice, false);
    }
    const VAddr target = col_buf.Address();
    ScopeMarker("EliminateFastClear:MRT={:#x}:M={:#x}", fmt::make_format_args(target, cmask), [&] {
                    runtime.ClearImage(&texture_cache.GetImage(image_id), desc.view_info.range,
                                       GcnToVk::ColorBufferClearValue(col_buf));
                });
}

Rasterizer::BeginSignature Rasterizer::MakeBeginSignature(const GraphicsPipeline* pipeline) const {
    const auto& key = pipeline->GetGraphicsKey();
    const auto& regs = Regs();
    BeginSignature sig;
    const u32 num_color = std::bit_width(key.mrt_mask);
    for (u32 cb = 0; cb < num_color && cb < Gcn::NUM_COLOR_BUFFERS; ++cb) {
        sig.ids[cb] = cb_descs[cb].first;
        if (cb_descs[cb].first) {
            sig.views[cb] = cb_descs[cb].second.view_info;
        }
        sig.color_samples[cb] = key.color_samples[cb];
    }
    sig.ids[Gcn::NUM_COLOR_BUFFERS] = db_desc.first;
    if (db_desc.first) {
        sig.views[Gcn::NUM_COLOR_BUFFERS] = db_desc.second.view_info;
    }
    sig.mrt_mask = key.mrt_mask;
    sig.num_samples = key.num_samples;
    sig.generation = texture_cache.RegistryGeneration();
    std::memcpy(&sig.depth_control, &regs.depth_control, sizeof(u32));
    sig.depth_valid = regs.depth_buffer.DepthValid();
    sig.stencil_valid = regs.depth_buffer.StencilValid();
    return sig;
}

RenderState Rasterizer::BeginRendering(const GraphicsPipeline* pipeline) {
    SKY_RENDERER_SECTION(BeginRendering);
    // renderer: RenderStateMemo (see BeginMemo).
    const bool memo_on = !SkyToggle::Disabled(SkyToggle::RenderStateMemo) && !FrameCapture::Active();
    if (SkyStats::enabled && ((begin_memo_hits + begin_memo_misses) & 0x3FFFF) == 0x3FFFF) {
        std::printf("Render state memo: %llu hits, %llu misses; texture sets: %llu hits, %llu "
                    "misses\n",
                    static_cast<unsigned long long>(begin_memo_hits),
                    static_cast<unsigned long long>(begin_memo_misses),
                    static_cast<unsigned long long>(texture_set_hits),
                    static_cast<unsigned long long>(texture_set_misses));
        std::printf("  texture set misses: other key %llu, generation %llu, image check %llu, "
                    "other %llu\n",
                    (unsigned long long)texture_set_why[0], (unsigned long long)texture_set_why[1],
                    (unsigned long long)texture_set_why[2], (unsigned long long)texture_set_why[3]);
        texture_set_why = {};
        begin_memo_hits = begin_memo_misses = texture_set_hits = texture_set_misses = 0;
    }
    BeginSignature signature;
    if (memo_on) {
        signature = MakeBeginSignature(pipeline);
        const auto& regs = Regs();
        bool usable = begin_memo.valid && scheduler.IsRenderingWith(begin_memo.state) &&
                      !regs.depth_render_control.depth_clear_enable &&
                      !regs.depth_render_control.stencil_clear_enable &&
                      signature == begin_memo.signature;
        for (const auto id : signature.ids) {
            if (usable && id) {
                const auto& image = texture_cache.GetImage(id);
                usable = !image.binding.is_bound && !image.binding.needs_rebind;
            }
        }
        if (usable) {
            ++begin_memo_hits;
            attachment_feedback_loop = false;
            return begin_memo.state;
        }
        ++begin_memo_misses;
    }
    begin_memo.valid = false;
    RenderState state = BeginRenderingFull(pipeline);
    if (memo_on && !attachment_feedback_loop) {
        // (is_clear of the depth attachment shares its bytes with has_depth.)
        bool clears = state.depth_stencil_attachment.depth_clear ||
                      state.depth_stencil_attachment.stencil_clear;
        for (u32 i = 0; i < state.num_color_attachments; ++i) {
            clears |= state.color_attachments[i].is_clear != 0;
        }
        if (!clears) {
            begin_memo = {true, signature, state};
        }
    }
    return state;
}

void Rasterizer::BindColorAttachments(RenderState& state, const GraphicsPipelineKey& key) {
    const auto& regs = Regs();
    state.num_color_attachments = std::bit_width(key.mrt_mask);
    for (u32 cb = 0; cb < state.num_color_attachments; ++cb) {
        auto& [image_id, desc] = cb_descs[cb];
        auto& attachment = state.color_attachments[cb];
        if (!image_id) {
            attachment = {};
            continue;
        }
        auto* image = &texture_cache.GetImage(image_id);
        if (image->binding.needs_rebind) {
            last_targets[cb].generation = ~0ULL; // FindImage may rewrite the description
            image_id = bound_images.emplace_back(texture_cache.FindImage(desc));
            image = &texture_cache.GetImage(image_id);
        }
        texture_cache.UpdateImage(image_id);
        runtime.SetBackingSamples(image, key.color_samples[cb]);
        const auto& view = texture_cache.FindRenderTarget(image_id, desc);
        const u32 slice = view.info.range.base.layer;
        const u32 mip = view.info.range.base.level;
        const auto& col_buf = regs.color_buffers[cb];
        const bool is_clear = texture_cache.IsMetaCleared(col_buf.CmaskAddress(), slice);
        texture_cache.TouchMeta(col_buf.CmaskAddress(), slice, false);

        constexpr auto ColorAccess =
            vk::AccessFlagBits2::eColorAttachmentWrite | vk::AccessFlagBits2::eColorAttachmentRead;
        if (image->binding.is_bound) {
            // Also sampled by this draw: a feedback loop.
            ASSERT_MSG(!image->binding.force_general,
                       "Having image both as storage and render target is unsupported");
            runtime.FlushBarriers();
            needs_barrier |= runtime.Transit(
                image,
                instance.IsAttachmentFeedbackLoopLayoutSupported()
                    ? vk::ImageLayout::eAttachmentFeedbackLoopOptimalEXT
                    : vk::ImageLayout::eGeneral,
                vk::PipelineStageFlagBits2::eColorAttachmentOutput, ColorAccess);
            attachment_feedback_loop = true;
        } else {
            needs_barrier |= runtime.Transit(image, vk::ImageLayout::eColorAttachmentOptimal,
                                             vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                                             ColorAccess, desc.view_info.range);
        }
        state.width = std::min<u32>(state.width, std::max(image->info.size.width >> mip, 1u));
        state.height = std::min<u32>(state.height, std::max(image->info.size.height >> mip, 1u));
        state.num_layers = std::min<u32>(state.num_layers, view.info.range.extent.layers);

        const auto clear_value =
            is_clear ? GcnToVk::ColorBufferClearValue(col_buf) : vk::ClearValue{};
        attachment.image_view = *view.image_view;
        attachment.image_layout = image->backing->state.layout;
        attachment.clear_value = clear_value.color.uint32;
        attachment.is_clear = is_clear;
        image->usage.render_target = 1u;
    }
    for (u32 cb = state.num_color_attachments; cb < state.color_attachments.size(); ++cb) {
        state.color_attachments[cb] = {};
    }
}

void Rasterizer::BindDepthAttachment(RenderState& state) {
    auto& attachment = state.depth_stencil_attachment;
    const auto image_id = db_desc.first;
    if (!image_id) {
        attachment = {};
        return;
    }
    const auto& regs = Regs();
    const auto& desc = db_desc.second;
    const auto htile_address = regs.depth_htile_data_base.GetAddress();
    const auto& view = texture_cache.FindDepthTarget(image_id, desc);
    auto& image = texture_cache.GetImage(image_id);
    const u32 slice = view.info.range.base.layer;
    const bool is_depth_clear =
        (regs.depth_render_control.depth_clear_enable && regs.depth_control.depth_enable &&
         regs.depth_control.depth_write_enable) ||
        texture_cache.IsMetaCleared(htile_address, slice);
    const bool is_stencil_clear = regs.depth_render_control.stencil_clear_enable;
    texture_cache.TouchMeta(htile_address, slice, false);
    ASSERT(desc.view_info.range.extent.levels == 1 && !image.binding.needs_rebind);

    // Read-only depth layouts unless it is also written as storage; stencil writes can be on
    // while depth writes are off.
    const bool has_stencil = image.info.props.has_stencil;
    const bool storage = desc.view_info.is_storage;
    const bool stencil_write = has_stencil && regs.depth_control.stencil_enable && !storage;
    const auto layout = storage ? (has_stencil ? vk::ImageLayout::eDepthStencilAttachmentOptimal
                                               : vk::ImageLayout::eDepthAttachmentOptimal)
                        : stencil_write ? vk::ImageLayout::eDepthReadOnlyStencilAttachmentOptimal
                        : has_stencil   ? vk::ImageLayout::eDepthStencilReadOnlyOptimal
                                        : vk::ImageLayout::eDepthReadOnlyOptimal;
    needs_barrier |= runtime.Transit(&image, layout,
                                     vk::PipelineStageFlagBits2::eEarlyFragmentTests |
                                         vk::PipelineStageFlagBits2::eLateFragmentTests,
                                     vk::AccessFlagBits2::eDepthStencilAttachmentWrite |
                                         vk::AccessFlagBits2::eDepthStencilAttachmentRead,
                                     desc.view_info.range);
    state.width = std::min<u32>(state.width, image.info.size.width);
    state.height = std::min<u32>(state.height, image.info.size.height);
    state.num_layers = std::min<u32>(state.num_layers, view.info.range.extent.layers);

    attachment.image_view = *view.image_view;
    attachment.image_layout = image.backing->state.layout;
    attachment.clear_value = {};
    attachment.is_clear = 0;
    if (regs.depth_buffer.DepthValid()) {
        attachment.clear_value[0] = is_depth_clear ? std::bit_cast<u32>(regs.depth_clear) : 0u;
        attachment.has_depth = true;
        attachment.depth_clear = is_depth_clear;
    }
    if (regs.depth_buffer.StencilValid()) {
        attachment.clear_value[1] = is_stencil_clear ? regs.stencil_clear : 0u;
        attachment.has_stencil = true;
        attachment.stencil_clear = is_stencil_clear;
    }
    image.usage.depth_target = true;
}

RenderState Rasterizer::BeginRenderingFull(const GraphicsPipeline* pipeline) {
    attachment_feedback_loop = false;
    const auto& key = pipeline->GetGraphicsKey();

    RenderState state;
    state.width = instance.GetMaxFramebufferWidth();
    state.height = instance.GetMaxFramebufferHeight();
    state.num_layers = std::numeric_limits<u16>::max();
    BindColorAttachments(state, key);
    BindDepthAttachment(state);
    if (state.num_layers == std::numeric_limits<u16>::max()) {
        state.num_layers = 1;
    }
    if (FrameCapture::Active()) {
        std::array<const VideoCore::ImageInfo*, Gcn::NUM_COLOR_BUFFERS> colors{};
        for (u32 cb = 0; cb < state.num_color_attachments; ++cb) {
            if (cb_descs[cb].first) {
                colors[cb] = &texture_cache.GetImage(cb_descs[cb].first).info;
            }
        }
        const auto* depth = db_desc.first ? &texture_cache.GetImage(db_desc.first).info : nullptr;
        FrameCapture::BeginPass(colors.data(), state.num_color_attachments, depth);
    }
    return state;
}

void Rasterizer::Resolve() {
    const auto& regs = Regs();
    VideoCore::TextureCache::ImageDesc src_desc{regs.color_buffers[0], CbExtent(0)};
    VideoCore::TextureCache::ImageDesc dst_desc{regs.color_buffers[1], CbExtent(1)};
    auto& src = texture_cache.GetImage(texture_cache.FindImage(src_desc, true));
    auto& dst = texture_cache.GetImage(texture_cache.FindImage(dst_desc, true));
    const VAddr src_address = regs.color_buffers[0].Address();
    const VAddr dst_address = regs.color_buffers[1].Address();
    ScopeMarker("Resolve:MRT0={:#x}:MRT1={:#x}", fmt::make_format_args(src_address, dst_address),
                [&] {
                    runtime.ResolveImage(&src, &dst, src_desc.view_info.range,
                                         dst_desc.view_info.range);
                });
}

void Rasterizer::DepthStencilCopy(bool is_depth, bool is_stencil) {
    // From the depth/stencil surface read to the one written (DB_*_READ_BASE vs WRITE_BASE).
    const auto& regs = Regs();
    const auto& db = regs.depth_buffer;
    const auto desc = [&](bool write) {
        return VideoCore::TextureCache::ImageDesc(db, regs.depth_view, regs.depth_control,
                                                  regs.depth_htile_data_base.GetAddress(),
                                                  DbExtent(), write);
    };
    auto read_desc = desc(false);
    auto write_desc = desc(true);
    auto& read_image = texture_cache.GetImage(texture_cache.FindImage(read_desc));
    auto& write_image = texture_cache.GetImage(texture_cache.FindImage(write_desc));
    VideoCore::SubresourceRange range;
    range.base.layer = regs.depth_view.slice_start;
    range.extent.layers = regs.depth_view.NumSlices() - range.base.layer;
    const VAddr depth_read = db.DepthAddress(), stencil_read = db.StencilAddress();
    const VAddr depth_write = db.DepthWriteAddress(), stencil_write = db.StencilWriteAddress();
    ScopeMarker("DepthStencilCopy:DR={:#x}:SR={:#x}:DW={:#x}:SW={:#x}",
                fmt::make_format_args(depth_read, stencil_read, depth_write, stencil_write),
                [&] { runtime.CopyDepthStencil(&read_image, &write_image, range); });
}

} // namespace Vulkan

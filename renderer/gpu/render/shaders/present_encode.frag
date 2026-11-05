// SPDX-License-Identifier: GPL-2.0-or-later
// renderer: the last pass before the swapchain. SDR: linear color encoded with the sRGB curve,
// its exponent shifted by the user's gamma (1: the standard curve); sRGB-encoded sources read
// through a UNORM view are decoded first. HDR: passed through. With anti_alias set, edges of
// the source are smoothed first (a luma edge search with a blend along the edge, FXAA-style).
#version 450

layout(location = 0) in vec2 uv;
layout(location = 0) out vec4 color;

layout(binding = 0) uniform sampler2D source;

layout(push_constant) uniform Settings {
    float gamma;
    bool hdr;
    bool srgb_input;
    bool anti_alias;
} settings;

// The sRGB curve's constants: linear below the knee, a power above it.
const float Knee = 0.0031308;
const float Scale = 1.055;
const float Offset = 0.055;
const float Slope = 12.92;

vec3 Encode(vec3 linear) {
    const float exponent = 1.0 / (3.4 - settings.gamma);
    const vec3 curve = Scale * pow(linear, vec3(exponent)) - Offset;
    return mix(curve, Slope * linear / settings.gamma, lessThan(linear, vec3(Knee)));
}

// The inverse of Encode at gamma 1.
vec3 Decode(vec3 encoded) {
    const vec3 curve = pow(max(encoded + Offset, 0.0) / Scale, vec3(2.4));
    return mix(curve, encoded / Slope, lessThan(encoded, vec3(Slope * Knee)));
}

float Luma(vec3 rgb) {
    return dot(rgb, vec3(0.299, 0.587, 0.114));
}

// Contrast below which a pixel is left alone: absolute, and relative to its brightest neighbour.
const float EdgeMin = 1.0 / 24.0;
const float EdgeRelative = 1.0 / 8.0;
// How far (in source pixels) the blend may reach along an edge.
const float SpanMax = 8.0;
const float ReduceMin = 1.0 / 128.0;
const float ReduceLuma = 1.0 / 8.0;

// Source pixels whose neighbourhood has a hard luma edge are replaced by samples taken along
// the edge's direction, in source texels (the frame may be scaled to the window afterwards).
vec4 AntiAliased() {
    const vec2 texel = 1.0 / vec2(textureSize(source, 0));
    const vec4 centre = texture(source, uv);
    const float m = Luma(centre.rgb);
    const float nw = Luma(texture(source, uv + vec2(-1.0, -1.0) * texel).rgb);
    const float ne = Luma(texture(source, uv + vec2(1.0, -1.0) * texel).rgb);
    const float sw = Luma(texture(source, uv + vec2(-1.0, 1.0) * texel).rgb);
    const float se = Luma(texture(source, uv + vec2(1.0, 1.0) * texel).rgb);
    const float low = min(m, min(min(nw, ne), min(sw, se)));
    const float high = max(m, max(max(nw, ne), max(sw, se)));
    if (high - low < max(EdgeMin, high * EdgeRelative)) {
        return centre;
    }
    // Perpendicular to the luma gradient: the direction the edge runs.
    vec2 direction = vec2(-((nw + ne) - (sw + se)), (nw + sw) - (ne + se));
    const float reduce = max((nw + ne + sw + se) * 0.25 * ReduceLuma, ReduceMin);
    const float scale = 1.0 / (min(abs(direction.x), abs(direction.y)) + reduce);
    direction = clamp(direction * scale, vec2(-SpanMax), vec2(SpanMax)) * texel;
    const vec4 near = 0.5 * (texture(source, uv + direction * (1.0 / 3.0 - 0.5)) +
                             texture(source, uv + direction * (2.0 / 3.0 - 0.5)));
    const vec4 far = 0.5 * near + 0.25 * (texture(source, uv - direction * 0.5) +
                                          texture(source, uv + direction * 0.5));
    // The wide blend crossed another edge: keep the narrow one.
    const float far_luma = Luma(far.rgb);
    return far_luma < low || far_luma > high ? near : far;
}

void main() {
    vec4 texel = settings.anti_alias ? AntiAliased() : texture(source, uv);
    if (settings.hdr) {
        color = texel;
        return;
    }
    if (settings.srgb_input) {
        texel.rgb = Decode(texel.rgb);
    }
    color = vec4(Encode(texel.rgb), texel.a);
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// ITU-T G.726 ADPCM at 32 kbit/s (4-bit codes, 8 kHz mono), the format the
// Xbox 360 portal's speaker takes. Written from the algorithm in the standard,
// with the structure of Sun Microsystems' public-domain g72x reference. The
// state carries over between calls, so one codec sees one stream in order.
#include <array>
#include <cstdint>
#include <functional>
#include <span>
#include <vector>

namespace PortalDevice {
class G726 {
public:
    G726() { reset(); }
    void reset();
    std::uint8_t encode(std::int16_t sample);  // 16-bit linear in, 4-bit code out
    std::int16_t decode(std::uint8_t code);    // 4-bit code in, 16-bit linear out
private:
    int step_size() const;
    int predictor_zero() const;
    int predictor_pole() const;
    void update(int y, int wi, int fi, int dq, int sr, int dqsez);
    std::int32_t yl_, yu_, dms_, dml_, ap_;
    std::array<std::int32_t, 2> a_;
    std::array<std::int32_t, 6> b_;
    std::array<std::int32_t, 2> pk_;
    std::array<std::int16_t, 6> dq_;
    std::array<std::int16_t, 2> sr_;
    bool td_;
};

// Turns the PS4 game's speaker packets (16-bit little-endian PCM, 8 kHz) into
// Xbox 360 portal frames: 0B 17, then 30 bytes of 60 codes, low nibble first.
class SpeakerEncoder {
public:
    using Frame = std::array<std::uint8_t, 32>;
    void add(std::span<const std::uint8_t> pcm, const std::function<bool(const Frame&)>& send, bool& ok);
    void reset() { codec_.reset(); pending_.clear(); }
private:
    G726 codec_;
    std::vector<std::int16_t> pending_;
};
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "g726.hpp"
#include <cstdlib>

namespace PortalDevice {
namespace {
constexpr std::int16_t power2[15]{1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80, 0x100, 0x200, 0x400, 0x800, 0x1000, 0x2000, 0x4000};
// 32 kbit/s tables (G.726 table 1 and the scale-factor/speed-control maps).
constexpr std::int16_t quantizer[7]{-124, 80, 178, 246, 300, 349, 400};
constexpr std::int16_t dqln[16]{-2048, 4, 135, 213, 273, 323, 373, 425, 425, 373, 323, 273, 213, 135, 4, -2048};
constexpr std::int16_t wi_table[16]{-12, 18, 41, 64, 112, 198, 355, 1122, 1122, 355, 198, 112, 64, 41, 18, -12};
constexpr std::int16_t fi_table[16]{0, 0, 0, 0x200, 0x200, 0x200, 0x600, 0xE00, 0xE00, 0x600, 0x200, 0x200, 0x200, 0, 0, 0};

int quan(int value, const std::int16_t* table, int size) {
    int i = 0;
    while (i < size && value >= table[i]) ++i;
    return i;
}

// Multiplies a predictor coefficient by a value in the reference's floating-point form.
int fmult(int an, int srn) {
    const int magnitude = an > 0 ? an : ((-an) & 0x1FFF);
    const int exponent = quan(magnitude, power2, 15) - 6;
    const int mantissa = magnitude == 0 ? 32 : exponent >= 0 ? magnitude >> exponent : magnitude << -exponent;
    const int product_exponent = exponent + ((srn >> 6) & 0xF) - 13;
    const int product_mantissa = (mantissa * (srn & 077) + 0x30) >> 4;
    const int result = product_exponent >= 0 ? (product_mantissa << product_exponent) & 0x7FFF : product_mantissa >> -product_exponent;
    return ((an ^ srn) < 0) ? -result : result;
}

int quantize(int d, int y) {
    const int magnitude = std::abs(d);
    const int exponent = quan(magnitude >> 1, power2, 15);
    const int mantissa = ((magnitude << 7) >> exponent) & 0x7F;
    const int log_difference = (exponent << 7) + mantissa - (y >> 2);
    const int i = quan(log_difference, quantizer, 7);
    if (d < 0) return 15 - i;
    return i == 0 ? 15 : i;
}

int reconstruct(bool negative, int log_magnitude, int y) {
    const int dql = log_magnitude + (y >> 2);
    if (dql < 0) return negative ? -0x8000 : 0;
    const int exponent = (dql >> 7) & 15;
    const int mantissa = 128 + (dql & 127);
    const int dq = (mantissa << 7) >> (14 - exponent);
    return negative ? dq - 0x8000 : dq;
}

std::int16_t to_float(int value) {  // the reference's 11-bit floating-point form
    if (value == 0) return 0x20;
    const int magnitude = value > 0 ? value : -value;
    const int exponent = quan(magnitude, power2, 15);
    const int result = (exponent << 6) + ((magnitude << 6) >> exponent);
    return static_cast<std::int16_t>(value > 0 ? result : result - 0x400);
}
}

void G726::reset() {
    yl_ = 34816; yu_ = 544; dms_ = dml_ = ap_ = 0;
    a_.fill(0); b_.fill(0); pk_.fill(0); dq_.fill(32); sr_.fill(32); td_ = false;
}

int G726::step_size() const {
    if (ap_ >= 256) return yu_;
    int y = yl_ >> 6;
    const int difference = yu_ - y, weight = ap_ >> 2;
    if (difference > 0) y += (difference * weight) >> 6;
    else if (difference < 0) y += (difference * weight + 0x3F) >> 6;
    return y;
}

int G726::predictor_zero() const {
    int sum = 0;
    for (int i = 0; i < 6; ++i) sum += fmult(b_[i] >> 2, dq_[i]);
    return sum;
}

int G726::predictor_pole() const { return fmult(a_[1] >> 2, sr_[1]) + fmult(a_[0] >> 2, sr_[0]); }

void G726::update(int y, int wi, int fi, int dq, int sr, int dqsez) {
    const int pk0 = dqsez < 0;
    const int magnitude = dq & 0x7FFF;
    const int ylint = yl_ >> 15, ylfrac = (yl_ >> 10) & 0x1F;
    const int thr1 = (32 + ylfrac) << ylint;
    const int thr2 = ylint > 9 ? 31 << 10 : thr1;
    const int dqthr = (thr2 + (thr2 >> 1)) >> 1;
    const bool transition = td_ && magnitude > dqthr;

    yu_ = y + ((wi - y) >> 5);
    if (yu_ < 544) yu_ = 544; else if (yu_ > 5120) yu_ = 5120;
    yl_ += yu_ + ((-yl_) >> 6);

    int a2p = 0;
    if (transition) {
        a_.fill(0); b_.fill(0);
    } else {
        const int pks1 = pk0 ^ pk_[0];
        a2p = a_[1] - (a_[1] >> 7);
        if (dqsez != 0) {
            const int fa1 = pks1 ? a_[0] : -a_[0];
            if (fa1 < -8191) a2p -= 0x100; else if (fa1 > 8191) a2p += 0xFF; else a2p += fa1 >> 5;
            if (pk0 ^ pk_[1]) {
                if (a2p <= -12160) a2p = -12288; else if (a2p >= 12416) a2p = 12288; else a2p -= 0x80;
            } else if (a2p <= -12416) a2p = -12288; else if (a2p >= 12160) a2p = 12288; else a2p += 0x80;
        }
        a_[1] = a2p;
        a_[0] -= a_[0] >> 8;
        if (dqsez != 0) a_[0] += pks1 ? -192 : 192;
        const int a1ul = 15360 - a2p;
        if (a_[0] < -a1ul) a_[0] = -a1ul; else if (a_[0] > a1ul) a_[0] = a1ul;
        for (int i = 0; i < 6; ++i) {
            b_[i] -= b_[i] >> 8;
            if (magnitude) b_[i] += ((dq ^ dq_[i]) >= 0) ? 128 : -128;
        }
    }
    for (int i = 5; i > 0; --i) dq_[i] = dq_[i - 1];
    dq_[0] = magnitude == 0 ? static_cast<std::int16_t>(dq >= 0 ? 0x20 : -0x3E0) : to_float(dq >= 0 ? magnitude : -magnitude);
    sr_[1] = sr_[0];
    sr_[0] = sr <= -32768 ? static_cast<std::int16_t>(-0x3E0) : to_float(sr);
    pk_[1] = pk_[0]; pk_[0] = pk0;
    td_ = !transition && a2p < -11776;
    dms_ += (fi - dms_) >> 5;
    dml_ += ((fi << 2) - dml_) >> 7;
    if (transition) ap_ = 256;
    else if (y < 1536 || td_ || std::abs((dms_ << 2) - dml_) >= (dml_ >> 3)) ap_ += (0x200 - ap_) >> 4;
    else ap_ += (-ap_) >> 4;
}

std::uint8_t G726::encode(std::int16_t sample) {
    const int sl = sample >> 2;  // 14-bit linear
    const int sezi = predictor_zero();
    const int sez = sezi >> 1, se = (sezi + predictor_pole()) >> 1;
    const int y = step_size();
    const int i = quantize(sl - se, y);
    const int dq = reconstruct(i & 8, dqln[i], y);
    const int sr = dq < 0 ? se - (dq & 0x3FFF) : se + dq;
    update(y, wi_table[i] << 5, fi_table[i], dq, sr, sr + sez - se);
    return static_cast<std::uint8_t>(i);
}

std::int16_t G726::decode(std::uint8_t code) {
    const int i = code & 0x0F;
    const int sezi = predictor_zero();
    const int sez = sezi >> 1, se = (sezi + predictor_pole()) >> 1;
    const int y = step_size();
    const int dq = reconstruct(i & 8, dqln[i], y);
    const int sr = dq < 0 ? se - (dq & 0x3FFF) : se + dq;
    update(y, wi_table[i] << 5, fi_table[i], dq, sr, sr - se + sez);
    const int out = sr << 2;
    return static_cast<std::int16_t>(out > 32767 ? 32767 : out < -32768 ? -32768 : out);
}

void SpeakerEncoder::add(std::span<const std::uint8_t> pcm, const std::function<bool(const Frame&)>& send, bool& ok) {
    for (std::size_t i = 0; i + 1 < pcm.size(); i += 2)
        pending_.push_back(static_cast<std::int16_t>(pcm[i] | (pcm[i + 1] << 8)));
    std::size_t used = 0;
    for (; pending_.size() - used >= 60; used += 60) {
        Frame frame{0x0b, 0x17};
        for (std::size_t k = 0; k < 30; ++k) {
            const auto low = codec_.encode(pending_[used + 2 * k]), high = codec_.encode(pending_[used + 2 * k + 1]);
            frame[2 + k] = static_cast<std::uint8_t>(low | (high << 4));
        }
        if (!send(frame)) ok = false;
    }
    pending_.erase(pending_.begin(), pending_.begin() + static_cast<std::ptrdiff_t>(used));
}
}

// SPDX-License-Identifier: GPL-3.0-or-later
// G.726 32 kbit/s: a tone survives encode/decode, and speaker frames are packed as the portal expects.
#include "../portal_device/g726.hpp"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

using PortalDevice::G726; using PortalDevice::SpeakerEncoder;
static void check(bool ok, const char* what) { if (!ok) { std::fprintf(stderr, "FAIL: %s\n", what); std::exit(1); } }

int main() {
    // 1 s of a 440 Hz tone with a 1 kHz overtone, 8 kHz.
    std::vector<std::int16_t> tone(8000);
    for (std::size_t i = 0; i < tone.size(); ++i)
        tone[i] = static_cast<std::int16_t>(9000 * std::sin(2 * M_PI * 440 * i / 8000.0) + 3000 * std::sin(2 * M_PI * 1000 * i / 8000.0));
    G726 encoder, decoder;
    double signal = 0, noise = 0;
    for (std::size_t i = 0; i < tone.size(); ++i) {
        const auto code = encoder.encode(tone[i]);
        check(code < 16, "4-bit code");
        const double out = decoder.decode(code);
        if (i >= 400) { signal += double(tone[i]) * tone[i]; noise += (out - tone[i]) * (out - tone[i]); }  // after convergence
    }
    const double snr = 10 * std::log10(signal / noise);
    std::printf("G.726 round trip SNR %.1f dB\n", snr);
    check(snr > 20, "round-trip quality");

    // Silence stays quiet.
    G726 quiet_in, quiet_out; int loudest = 0;
    for (int i = 0; i < 800; ++i) loudest = std::max(loudest, std::abs(int(quiet_out.decode(quiet_in.encode(0)))));
    check(loudest < 64, "silence");

    // Packing: 32-sample game packets become 60-code frames, low nibble first.
    std::vector<std::uint8_t> pcm;
    for (int i = 0; i < 32 * 4; ++i) { pcm.push_back(std::uint8_t(tone[i])); pcm.push_back(std::uint8_t(std::uint16_t(tone[i]) >> 8)); }
    SpeakerEncoder speaker; std::vector<SpeakerEncoder::Frame> frames; bool ok = true;
    for (int p = 0; p < 4; ++p)
        speaker.add(std::span(pcm).subspan(p * 64, 64), [&](const SpeakerEncoder::Frame& f) { frames.push_back(f); return true; }, ok);
    check(ok && frames.size() == 2, "128 samples make two frames, 8 wait");
    G726 reference;
    for (const auto& frame : frames) {
        check(frame[0] == 0x0b && frame[1] == 0x17, "speaker header");
        for (int k = 0; k < 30; ++k) check(frame[2 + k] == (reference.encode(tone[(&frame - frames.data()) * 60 + 2 * k]) |
                                                           (reference.encode(tone[(&frame - frames.data()) * 60 + 2 * k + 1]) << 4)), "low nibble first");
    }
    std::puts("g726 ok");
}

// SPDX-License-Identifier: GPL-3.0-or-later
// The virtual portal (figure files placed through portal_library) behind the
// same transport interface as real portals. Its identity is the HID portal
// that the Cemu portal core implements; it has no USB descriptors of its own.
#include "transport.hpp"
#include "runtime/cemu_portal.hpp"
#include <algorithm>
#include <chrono>
#include <thread>

namespace PortalDevice {
namespace {
class VirtualTransport final : public Transport {
public:
    VirtualTransport() : Transport(make()) {}
    bool write_report(std::span<const std::uint8_t> report) override { return trapteam::cemu_portal_command(report); }
    int read_report(std::span<std::uint8_t> output, int timeout_ms) override {
        const auto reply = trapteam::cemu_portal_read();
        if (reply[0] == 0) { std::this_thread::sleep_for(std::chrono::milliseconds(std::min(timeout_ms, 10))); return 0; }
        const auto count = std::min(output.size(), report_size);
        std::copy_n(reply.begin(), count, output.begin());
        return static_cast<int>(count);
    }
    // Speaker PCM reaches the PC through VirtualPortal::bind_audio, not here.
    bool write_audio(std::span<const std::uint8_t>) override { return false; }
private:
    static Info make() {
        Info info;
        info.id = "virtual"; info.name = "Virtual portal (Traptanium)"; info.family = Family::virtual_portal;
        info.vendor = 0x1430; info.product = 0x0150;
        info.caps = {true, true, true}; info.identified = true;
        return info;
    }
};
}
std::unique_ptr<Transport> open_virtual() { return std::make_unique<VirtualTransport>(); }
}

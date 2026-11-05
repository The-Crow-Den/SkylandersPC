// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// One protocol, one transport per portal family. A transport moves 32-byte
// reports and 64-byte speaker packets; it never invents replies.
#include "protocol.hpp"
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <vector>

namespace PortalDevice {
enum class Family { hid, xbox360, xbox_one, virtual_portal };
const char* family_name(Family family);

struct Info {
    std::string id;        // "hid:/dev/hidraw5", "xbox:3-2", "virtual"
    std::string name;      // Model name once identified, else the USB product string.
    Family family = Family::hid;
    std::uint16_t vendor = 0, product = 0;
    // Raw USB descriptors as the device reported them: the 18-byte device
    // descriptor followed by every configuration descriptor. Empty for virtual.
    std::vector<std::uint8_t> usb_descriptors;
    std::vector<std::uint8_t> report_descriptor;
    Capabilities caps;
    bool identified = false;  // A reset reply matched a known firmware id.
};

class Transport {
public:
    explicit Transport(Info info) : info_(std::move(info)) {}
    virtual ~Transport() = default;
    const Info& info() const { return info_; }
    virtual bool write_report(std::span<const std::uint8_t> report) = 0;
    // Bytes read, 0 on timeout, negative on a device error (unplugged).
    virtual int read_report(std::span<std::uint8_t> output, int timeout_ms) = 0;
    virtual bool write_audio(std::span<const std::uint8_t> pcm) = 0;
protected:
    friend bool identify(Transport&, int);
    Info info_;
};

std::vector<Info> enumerate();
std::unique_ptr<Transport> open(const std::string& id);
// Sends R and reads until the reply arrives, filling name/caps from the model.
bool identify(Transport& transport, int timeout_ms = 500);

std::unique_ptr<Transport> open_hid(const Info& info);
std::unique_ptr<Transport> open_xbox(const Info& info);
std::unique_ptr<Transport> open_virtual();
}

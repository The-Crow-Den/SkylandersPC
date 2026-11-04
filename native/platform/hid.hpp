// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Raw HID access: hidraw on Linux, the Windows HID API on Windows.
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <vector>

namespace Platform::Hid {
struct DeviceInfo {
    std::string path;
    std::uint16_t vendor = 0, product = 0;
    std::string product_name;
    std::vector<std::uint8_t> usb_descriptors, report_descriptor;
};
std::vector<DeviceInfo> enumerate(std::uint16_t vendor);

class Device {
public:
    virtual ~Device() = default;
    // Report id 0 is implied; the bytes are the report payload.
    virtual bool write(std::span<const std::uint8_t> report) = 0;
    virtual int read(std::span<std::uint8_t> output, int timeout_ms) = 0;
};
std::unique_ptr<Device> open(const std::string& path);
}

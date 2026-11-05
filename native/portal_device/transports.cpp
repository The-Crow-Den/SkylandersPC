// SPDX-License-Identifier: GPL-3.0-or-later
#include "transport.hpp"
#include "../platform/hid.hpp"
#include <chrono>
#include <cstdio>
#include <libusb.h>

namespace PortalDevice {
namespace {
// Vendor 0x1430 (Activision). USB ids are from public notes and have not been
// confirmed on the user's hardware yet: 0x0150 is the HID portal shared by
// PS3/PS4/Wii/Wii U; 0x1f17 is reported for the Xbox 360 wired portal. The Xbox
// One portal speaks GIP and its product id is unknown.
constexpr std::uint16_t activision = 0x1430, hid_portal = 0x0150, xbox360_portal = 0x1f17;

class HidTransport final : public Transport {
public:
    HidTransport(Info info, std::unique_ptr<Platform::Hid::Device> device) : Transport(std::move(info)), device_(std::move(device)) {}
    bool write_report(std::span<const std::uint8_t> report) override { return device_->write(report); }
    int read_report(std::span<std::uint8_t> output, int timeout_ms) override { return device_->read(output, timeout_ms); }
    bool write_audio(std::span<const std::uint8_t> pcm) override { return device_->write(pcm); }
private:
    std::unique_ptr<Platform::Hid::Device> device_;
};

// Xbox 360 portals wrap each report in a two-byte header on vendor interrupt
// endpoints. The header values are unconfirmed: frames that do not match are
// passed through unchanged and logged once so a hardware transcript can settle it.
constexpr std::uint8_t xbox_in[]{0x0b, 0x14}, xbox_out[]{0x0b, 0x17};
class XboxTransport final : public Transport {
public:
    XboxTransport(Info info, libusb_context* context, libusb_device_handle* handle, std::uint8_t in, std::uint8_t out)
        : Transport(std::move(info)), context_(context), handle_(handle), in_(in), out_(out) {}
    ~XboxTransport() override { libusb_release_interface(handle_, 0); libusb_close(handle_); libusb_exit(context_); }
    bool write_report(std::span<const std::uint8_t> report) override {
        std::vector<std::uint8_t> frame(xbox_out, xbox_out + 2); frame.insert(frame.end(), report.begin(), report.end());
        int sent = 0;
        return libusb_interrupt_transfer(handle_, out_, frame.data(), static_cast<int>(frame.size()), &sent, 100) == 0;
    }
    int read_report(std::span<std::uint8_t> output, int timeout_ms) override {
        std::uint8_t frame[64]; int got = 0;
        const int status = libusb_interrupt_transfer(handle_, in_, frame, sizeof(frame), &got, static_cast<unsigned>(timeout_ms));
        if (status == LIBUSB_ERROR_TIMEOUT) return 0;
        if (status) return -1;
        std::size_t skip = 0;
        if (got >= 2 && frame[0] == xbox_in[0] && frame[1] == xbox_in[1]) skip = 2;
        else if (!warned_) { warned_ = true; std::fprintf(stderr, "Portal (Xbox): unrecognised frame header %02x %02x\n", frame[0], frame[1]); }
        const auto count = std::min<std::size_t>(output.size(), got - skip);
        std::copy_n(frame + skip, count, output.begin());
        return static_cast<int>(count);
    }
    bool write_audio(std::span<const std::uint8_t>) override { return false; }  // Not mapped for Xbox portals yet.
private:
    libusb_context* context_;
    libusb_device_handle* handle_;
    std::uint8_t in_, out_;
    bool warned_ = false;
};

void enumerate_xbox(std::vector<Info>& result) {
    libusb_context* context = nullptr;
    if (libusb_init(&context)) return;
    libusb_device** list = nullptr;
    const auto count = libusb_get_device_list(context, &list);
    for (ssize_t i = 0; i < count; ++i) {
        libusb_device_descriptor d{};
        if (libusb_get_device_descriptor(list[i], &d) || d.idVendor != activision || d.idProduct == hid_portal) continue;
        libusb_config_descriptor* config = nullptr;
        if (libusb_get_active_config_descriptor(list[i], &config)) continue;
        // HID-class interfaces are already listed through hidraw.
        const auto& alt = config->interface[0].altsetting[0];
        const bool vendor_class = alt.bInterfaceClass == 0xff;
        // Xbox 360 controllers use subclass 0x5d; GIP (Xbox One) uses subclass 0x47.
        Family family = d.idProduct == xbox360_portal || alt.bInterfaceSubClass == 0x5d ? Family::xbox360 : Family::xbox_one;
        libusb_free_config_descriptor(config);
        if (!vendor_class) continue;
        Info info;
        info.id = "xbox:" + std::to_string(libusb_get_bus_number(list[i])) + "-" + std::to_string(libusb_get_device_address(list[i]));
        info.family = family; info.vendor = d.idVendor; info.product = d.idProduct;
        info.name = family == Family::xbox360 ? "Xbox 360 portal" : "Xbox One portal";
        result.push_back(std::move(info));
    }
    libusb_free_device_list(list, 1);
    libusb_exit(context);
}
}

const char* family_name(Family family) {
    switch (family) {
    case Family::hid: return "hid";
    case Family::xbox360: return "xbox360";
    case Family::xbox_one: return "xbox-one";
    case Family::virtual_portal: return "virtual";
    }
    return "unknown";
}

std::vector<Info> enumerate() {
    std::vector<Info> result;
    for (auto& device : Platform::Hid::enumerate(activision)) {
        if (device.product != hid_portal) continue;
        Info info;
        info.id = "hid:" + device.path; info.family = Family::hid;
        info.vendor = device.vendor; info.product = device.product;
        info.name = device.product_name.empty() ? "HID portal" : device.product_name;
        info.usb_descriptors = std::move(device.usb_descriptors);
        info.report_descriptor = std::move(device.report_descriptor);
        result.push_back(std::move(info));
    }
    enumerate_xbox(result);
    return result;
}

std::unique_ptr<Transport> open_hid(const Info& info) {
    auto device = Platform::Hid::open(info.id.substr(4));
    if (!device) return nullptr;
    return std::make_unique<HidTransport>(info, std::move(device));
}

std::unique_ptr<Transport> open_xbox(const Info& info) {
    if (info.family == Family::xbox_one) {
        std::fprintf(stderr, "Portal: Xbox One portals need a GIP handshake that has not been recorded yet\n");
        return nullptr;
    }
    libusb_context* context = nullptr;
    if (libusb_init(&context)) return nullptr;
    libusb_device** list = nullptr; libusb_device_handle* handle = nullptr;
    std::uint8_t in = 0, out = 0;
    const auto count = libusb_get_device_list(context, &list);
    for (ssize_t i = 0; i < count && !handle; ++i) {
        const auto id = "xbox:" + std::to_string(libusb_get_bus_number(list[i])) + "-" + std::to_string(libusb_get_device_address(list[i]));
        if (id != info.id) continue;
        libusb_config_descriptor* config = nullptr;
        if (libusb_get_active_config_descriptor(list[i], &config)) break;
        const auto& alt = config->interface[0].altsetting[0];
        for (unsigned e = 0; e < alt.bNumEndpoints; ++e) {
            const auto& endpoint = alt.endpoint[e];
            if ((endpoint.bmAttributes & 3) != LIBUSB_TRANSFER_TYPE_INTERRUPT) continue;
            (endpoint.bEndpointAddress & 0x80 ? in : out) = endpoint.bEndpointAddress;
        }
        libusb_free_config_descriptor(config);
        if (in && out && !libusb_open(list[i], &handle)) {
            libusb_set_auto_detach_kernel_driver(handle, 1);  // xpad may have claimed it.
            if (libusb_claim_interface(handle, 0)) { libusb_close(handle); handle = nullptr; }
        }
    }
    libusb_free_device_list(list, 1);
    if (!handle) { libusb_exit(context); return nullptr; }
    return std::make_unique<XboxTransport>(info, context, handle, in, out);
}

std::unique_ptr<Transport> open(const std::string& id) {
    if (id == "virtual") return open_virtual();
    for (const auto& info : enumerate()) {
        if (id != "auto" && info.id != id) continue;
        if (info.family == Family::hid) return open_hid(info);
        if (id != "auto") return open_xbox(info);
    }
    return nullptr;
}

bool identify(Transport& transport, int timeout_ms) {
    if (!transport.write_report(reset())) return false;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    Report reply{};
    while (std::chrono::steady_clock::now() < deadline) {
        const int count = transport.read_report(reply, 50);
        if (count < 0) return false;
        if (count < 3 || reply[0] != 'R') continue;  // Status reports keep streaming.
        const auto model = PortalDevice::identify(reply);
        transport.info_.identified = model.known;
        if (model.known) { transport.info_.name = model.name; transport.info_.caps = model.caps; }
        return true;
    }
    return false;
}
}

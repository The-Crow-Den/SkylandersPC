// SPDX-License-Identifier: GPL-3.0-or-later
#include "hid.hpp"
#include <cerrno>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>

namespace Platform::Hid {
namespace {
namespace fs = std::filesystem;
std::vector<std::uint8_t> bytes(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(input), {}};
}
class Hidraw final : public Device {
public:
    explicit Hidraw(int fd) : fd_(fd) {}
    ~Hidraw() override { ::close(fd_); }
    bool write(std::span<const std::uint8_t> report) override {
        std::vector<std::uint8_t> buffer(report.size() + 1);
        std::copy(report.begin(), report.end(), buffer.begin() + 1);
        const auto written = ::write(fd_, buffer.data(), buffer.size());
        return written == static_cast<ssize_t>(buffer.size());
    }
    int read(std::span<std::uint8_t> output, int timeout_ms) override {
        pollfd waiting{fd_, POLLIN, 0};
        const int ready = ::poll(&waiting, 1, timeout_ms);
        if (ready < 0) return errno == EINTR ? 0 : -1;
        if (!ready) return 0;
        if (waiting.revents & (POLLERR | POLLHUP | POLLNVAL)) return -1;
        const auto count = ::read(fd_, output.data(), output.size());
        return count < 0 ? (errno == EAGAIN ? 0 : -1) : static_cast<int>(count);
    }
private:
    int fd_;
};
}
std::vector<DeviceInfo> enumerate(std::uint16_t vendor) {
    std::vector<DeviceInfo> result;
    std::error_code ec;
    for (const auto& entry : fs::directory_iterator("/sys/class/hidraw", ec)) {
        const auto hid = fs::canonical(entry.path() / "device", ec);
        if (ec) continue;
        std::ifstream uevent(hid / "uevent");
        DeviceInfo info; std::string line; unsigned bus = 0, v = 0, p = 0;
        while (std::getline(uevent, line)) {
            if (line.rfind("HID_ID=", 0) == 0) std::sscanf(line.c_str() + 7, "%x:%x:%x", &bus, &v, &p);
            else if (line.rfind("HID_NAME=", 0) == 0) info.product_name = line.substr(9);
        }
        if (bus != 3 || v != vendor) continue;  // USB-attached portals only.
        info.path = "/dev/" + entry.path().filename().string();
        info.vendor = static_cast<std::uint16_t>(v); info.product = static_cast<std::uint16_t>(p);
        info.report_descriptor = bytes(hid / "report_descriptor");
        // hid -> USB interface -> USB device, which holds the raw descriptors.
        info.usb_descriptors = bytes(hid.parent_path().parent_path() / "descriptors");
        result.push_back(std::move(info));
    }
    return result;
}
std::unique_ptr<Device> open(const std::string& path) {
    const int fd = ::open(path.c_str(), O_RDWR | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) return nullptr;
    return std::make_unique<Hidraw>(fd);
}
}

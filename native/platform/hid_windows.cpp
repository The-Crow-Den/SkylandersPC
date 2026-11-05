// SPDX-License-Identifier: GPL-3.0-or-later
// Windows HID API backend. Built only on Windows; not yet tested on hardware.
#include "hid.hpp"
#include <windows.h>
#include <hidsdi.h>
#include <setupapi.h>

namespace Platform::Hid {
namespace {
class WinHid final : public Device {
public:
    explicit WinHid(HANDLE handle) : handle_(handle) { event_ = CreateEventW(nullptr, TRUE, FALSE, nullptr); }
    ~WinHid() override { CancelIo(handle_); CloseHandle(event_); CloseHandle(handle_); }
    bool write(std::span<const std::uint8_t> report) override {
        std::vector<std::uint8_t> buffer(report.size() + 1);
        std::copy(report.begin(), report.end(), buffer.begin() + 1);
        OVERLAPPED overlapped{}; overlapped.hEvent = event_; ResetEvent(event_);
        DWORD written = 0;
        if (!WriteFile(handle_, buffer.data(), static_cast<DWORD>(buffer.size()), nullptr, &overlapped) &&
            GetLastError() != ERROR_IO_PENDING) return false;
        return GetOverlappedResult(handle_, &overlapped, &written, TRUE) && written == buffer.size();
    }
    int read(std::span<std::uint8_t> output, int timeout_ms) override {
        std::vector<std::uint8_t> buffer(output.size() + 1);
        OVERLAPPED overlapped{}; overlapped.hEvent = event_; ResetEvent(event_);
        DWORD count = 0;
        if (!ReadFile(handle_, buffer.data(), static_cast<DWORD>(buffer.size()), nullptr, &overlapped) &&
            GetLastError() != ERROR_IO_PENDING) return -1;
        if (WaitForSingleObject(event_, static_cast<DWORD>(timeout_ms)) != WAIT_OBJECT_0) {
            CancelIo(handle_); GetOverlappedResult(handle_, &overlapped, &count, TRUE); return 0;
        }
        if (!GetOverlappedResult(handle_, &overlapped, &count, FALSE) || !count) return -1;
        std::copy(buffer.begin() + 1, buffer.begin() + count, output.begin());  // Drop the report id.
        return static_cast<int>(count - 1);
    }
private:
    HANDLE handle_, event_;
};
}
std::vector<DeviceInfo> enumerate(std::uint16_t vendor) {
    std::vector<DeviceInfo> result;
    GUID guid; HidD_GetHidGuid(&guid);
    const auto set = SetupDiGetClassDevsW(&guid, nullptr, nullptr, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (set == INVALID_HANDLE_VALUE) return result;
    SP_DEVICE_INTERFACE_DATA data{sizeof(data)};
    for (DWORD i = 0; SetupDiEnumDeviceInterfaces(set, nullptr, &guid, i, &data); ++i) {
        DWORD size = 0; SetupDiGetDeviceInterfaceDetailA(set, &data, nullptr, 0, &size, nullptr);
        std::vector<char> storage(size);
        auto* detail = reinterpret_cast<SP_DEVICE_INTERFACE_DETAIL_DATA_A*>(storage.data());
        detail->cbSize = sizeof(*detail);
        if (!SetupDiGetDeviceInterfaceDetailA(set, &data, detail, size, nullptr, nullptr)) continue;
        const HANDLE handle = CreateFileA(detail->DevicePath, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
        if (handle == INVALID_HANDLE_VALUE) continue;
        HIDD_ATTRIBUTES attributes{sizeof(attributes)};
        if (HidD_GetAttributes(handle, &attributes) && attributes.VendorID == vendor) {
            DeviceInfo info; info.path = detail->DevicePath;
            info.vendor = attributes.VendorID; info.product = attributes.ProductID;
            wchar_t name[128]{};
            if (HidD_GetProductString(handle, name, sizeof(name)))
                for (const wchar_t* c = name; *c; ++c) info.product_name.push_back(*c < 128 ? static_cast<char>(*c) : '?');
            // Windows does not expose raw USB descriptors through the HID API.
            result.push_back(std::move(info));
        }
        CloseHandle(handle);
    }
    SetupDiDestroyDeviceInfoList(set);
    return result;
}
std::unique_ptr<Device> open(const std::string& path) {
    const HANDLE handle = CreateFileA(path.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
    if (handle == INVALID_HANDLE_VALUE) return nullptr;
    return std::make_unique<WinHid>(handle);
}
}

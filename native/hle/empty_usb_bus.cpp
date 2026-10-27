// SPDX-License-Identifier: GPL-3.0-or-later
#include "empty_usb_bus.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <stdexcept>
#include <thread>

namespace {
using U = std::uint64_t;
constexpr std::array<std::string_view, 7> names{
    "TOhg7P6kTH4#libSceUsbd#libSceUsbd", "Fq6+0Fm55xU#libSceUsbd#libSceUsbd",
    "8qB9Ar4P5nc#libSceUsbd#libSceUsbd", "EQ6SCLMqzkM#libSceUsbd#libSceUsbd",
    "vrQXYRo1Gwk#libSceUsbd#libSceUsbd", "MlW6deWfPp0#libSceUsbd#libSceUsbd",
    "EkqGLxWC-S0#libSceUsbd#libSceUsbd"};
}
EmptyUsbBus::~EmptyUsbBus() { for (auto* list : lists_) delete[] list; }
bool EmptyUsbBus::supports(std::string_view identity) noexcept {
    return std::find(names.begin(), names.end(), identity) != names.end();
}
U EmptyUsbBus::call(std::string_view identity, const U* a) {
    const auto operation = std::find(names.begin(), names.end(), identity) - names.begin();
    if (operation == static_cast<std::ptrdiff_t>(names.size())) throw std::runtime_error("unsupported empty USB bus import");
    std::unique_lock lock(lock_);
    if (operation == 0) { initialized_ = true; return 0; }
    if (operation == 1) {
        for (auto* list : lists_) delete[] list;
        lists_.clear(); initialized_ = false; return 0;
    }
    if (operation == 3) {
        auto** list = reinterpret_cast<void**>(a[0]);
        if (list && !lists_.erase(list)) throw std::runtime_error("unknown USB device-list ownership");
        delete[] list; return 0;
    }
    if (!initialized_) return static_cast<U>(-99ll); // libusb-compatible OTHER.
    if (operation == 2) {
        if (!a[0]) return static_cast<U>(-2ll);
        auto** list = new void*[1]{};
        try { lists_.insert(list); } catch (...) { delete[] list; throw; }
        *reinterpret_cast<void***>(a[0]) = list;
        return 0;
    }
    if (operation == 4) return 0; // No matching VID/PID exists on an empty bus.
    if (operation == 5) return static_cast<U>(-4ll); // NO_DEVICE.
    lock.unlock();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    return 0; // Empty event queue reached its polling timeout.
}

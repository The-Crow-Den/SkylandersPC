// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// libSceUsbd backed by a portal that is really attached. The game sees that
// device's own descriptors; reports pass through the portal transport.
#include "../portal_device/transport.hpp"
#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <string_view>

namespace RealPortalBus {
// SKY_PORTAL_DEVICE names the device ("auto", "hid:/dev/hidraw5", ...) and the
// virtual portal is off.
bool enabled();
bool supports(std::string_view identity);
unsigned stack_arguments(std::string_view identity);
std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);

// Tests: replace the device opener and the private backup folder.
void configure(std::function<std::unique_ptr<PortalDevice::Transport>()> opener,
               std::filesystem::path backup_folder, bool allow_figure_writes);
}

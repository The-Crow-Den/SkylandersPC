// SPDX-License-Identifier: MPL-2.0
#pragma once
#include <array>
#include <cstdint>
#include <span>
#include <filesystem>
#include <string>

namespace trapteam {
// Safety boundary around Cemu's actual SkylanderUSB implementation, not a
// replacement portal protocol. Figure loading is explicit and optional.
bool cemu_portal_command(std::span<const std::uint8_t> bytes);
std::array<std::uint8_t,64> cemu_portal_read();
bool cemu_portal_descriptor(unsigned type,unsigned index,unsigned language,std::span<std::uint8_t> output);
bool cemu_portal_self_test();
struct PortalFigure {std::filesystem::path working_copy;unsigned slot=0;};
// Always imports to a private writable copy; never opens the source for writes.
bool cemu_portal_load_figure(const std::filesystem::path& source,PortalFigure* figure,std::string* error);
bool cemu_portal_remove_figure(unsigned slot);
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "renderer_adapter.hpp"
#include "skyrender.h"
#include <cstdlib>
#include <string>

extern "C" void skyrender_pc_menu_toggle() __attribute__((weak));
namespace SkyGnm {
std::uint32_t sceGnmDrawInitDefaultHardwareState(std::uint32_t*, std::uint32_t);
}

namespace {
std::string option_name(const char* name) { return std::string("SKY_RENDERER_") + name; }
}

namespace Renderer {
void register_kernel() { skyrender_register_kernel(); }
bool init(const WindowConfig& config) {
    const SkyRenderConfig native{config.title, config.serial, config.user_directory,
        config.sdk_version, config.psf_attributes, config.width, config.height};
    return skyrender_init(&native) == 0;
}
std::uintptr_t resolve(const char* scoped_nid) { return skyrender_resolve(scoped_nid); }
bool handle_fault(void* context, void* address) { return skyrender_handle_fault(context, address) != 0; }
bool overlay_captures_input() { return skyrender_overlay_captures_input() != 0; }
bool has_menu_toggle() { return skyrender_pc_menu_toggle != nullptr; }
void toggle_menu() { if (skyrender_pc_menu_toggle) skyrender_pc_menu_toggle(); }
void add_event_filter(EventFilter filter) { skyrender_add_event_filter(filter); }
std::uint32_t draw_init_default_hardware_state(std::uint32_t* command_buffer, std::uint32_t size) {
    return SkyGnm::sceGnmDrawInitDefaultHardwareState(command_buffer, size);
}

// The library takes over deprecated BB_<name> spellings when it loads, before
// the host sets anything here.
void set_option(const char* name, const char* value, bool overwrite) {
    setenv(option_name(name).c_str(), value, overwrite ? 1 : 0);
}
const char* option(const char* name) { return std::getenv(option_name(name).c_str()); }
}

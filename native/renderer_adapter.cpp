// SPDX-License-Identifier: GPL-3.0-or-later
#include "renderer_adapter.hpp"
#include "bbgpu.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <unistd.h>

// Until the renderer itself is renamed, its C API is bbgpu_* and it reads its
// options as BB_<name>. Nothing outside this file uses those names.
extern "C" void bbgpu_pc_menu_toggle() __attribute__((weak));
namespace BbGnm {
std::uint32_t sceGnmDrawInitDefaultHardwareState(std::uint32_t*, std::uint32_t);
}

namespace {
constexpr char option_prefix[] = "SKY_RENDERER_";
constexpr char renderer_prefix[] = "BB_";
std::string option_name(const char* name) { return std::string(option_prefix) + name; }
std::string renderer_name(const char* name) { return std::string(renderer_prefix) + name; }
// A value set under the renderer's own spelling (BB_<name>) is accepted for
// one transition, with a note naming the replacement.
void adopt_legacy(const char* name) {
    const auto ours = option_name(name);
    if (std::getenv(ours.c_str())) return;
    const auto* legacy = std::getenv(renderer_name(name).c_str());
    if (!legacy) return;
    std::fprintf(stderr, "Renderer: %s%s is deprecated; use %s\n", renderer_prefix, name, ours.c_str());
    setenv(ours.c_str(), legacy, 1);
}
}

namespace Renderer {
void register_kernel() { bbgpu_register_kernel(); }
bool init(const WindowConfig& config) {
    const BbGpuConfig native{config.title, config.serial, config.user_directory,
        config.sdk_version, config.psf_attributes, config.width, config.height};
    return bbgpu_init(&native) == 0;
}
std::uintptr_t resolve(const char* scoped_nid) { return bbgpu_resolve(scoped_nid); }
bool handle_fault(void* context, void* address) { return bbgpu_handle_fault(context, address) != 0; }
bool overlay_captures_input() { return bbgpu_overlay_captures_input() != 0; }
bool has_menu_toggle() { return bbgpu_pc_menu_toggle != nullptr; }
void toggle_menu() { if (bbgpu_pc_menu_toggle) bbgpu_pc_menu_toggle(); }
void add_event_filter(EventFilter filter) { bbgpu_add_event_filter(filter); }
std::uint32_t draw_init_default_hardware_state(std::uint32_t* command_buffer, std::uint32_t size) {
    return BbGnm::sceGnmDrawInitDefaultHardwareState(command_buffer, size);
}

void set_option(const char* name, const char* value, bool overwrite) {
    if (!overwrite) adopt_legacy(name);
    setenv(option_name(name).c_str(), value, overwrite ? 1 : 0);
}
const char* option(const char* name) {
    adopt_legacy(name);
    return std::getenv(option_name(name).c_str());
}
// setenv may move environ, so each pass collects names before changing it.
static std::vector<std::string> names_with_prefix(const char* prefix) {
    std::vector<std::string> names;
    const auto length = std::strlen(prefix);
    for (char** entry = environ; *entry; ++entry)
        if (!std::strncmp(*entry, prefix, length) && std::strchr(*entry, '='))
            names.emplace_back(*entry + length, std::strchr(*entry, '='));
    return names;
}
void export_options() {
    for (const auto& name : names_with_prefix(renderer_prefix)) adopt_legacy(name.c_str());
    for (const auto& name : names_with_prefix(option_prefix))
        setenv(renderer_name(name.c_str()).c_str(), std::getenv(option_name(name.c_str()).c_str()), 1);
}
}

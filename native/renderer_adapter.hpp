// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>

// The host's view of the optional renderer component. renderer_adapter.cpp is
// the one place that names the renderer library's current C API and option
// variables; everything else uses these neutral names.
namespace Renderer {
struct WindowConfig {
    const char* title;
    const char* serial;          // CUSA id, names the pipeline cache
    const char* user_directory;  // settings, pipeline cache and logs
    std::uint32_t sdk_version;
    std::uint32_t psf_attributes;
    std::int32_t width, height;
};
// The renderer's settings file inside the user directory.
inline constexpr const char* settings_file = "bbport.ini";

void register_kernel();
bool init(const WindowConfig& config);
std::uintptr_t resolve(const char* scoped_nid);
bool handle_fault(void* context, void* address);
bool overlay_captures_input();
bool has_menu_toggle();
void toggle_menu();
using EventFilter = int (*)(const void* sdl_event, void* sdl_window);
void add_event_filter(EventFilter filter);
std::uint32_t draw_init_default_hardware_state(std::uint32_t* command_buffer, std::uint32_t size);

// Renderer options are SKY_RENDERER_<name> environment variables. set_option
// sets one; without overwrite an existing value (or its deprecated renderer
// spelling) wins. export_options hands all of them to the renderer and must
// run before the renderer reads its environment.
void set_option(const char* name, const char* value, bool overwrite);
const char* option(const char* name);
void export_options();
}

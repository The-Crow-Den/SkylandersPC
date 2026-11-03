// SPDX-License-Identifier: GPL-3.0-or-later
#include "renderer_adapter.hpp"
#include "guest_abi.hpp"
#include "platform/host_compat.hpp"
#include <stdexcept>
#include "skyrender.h"
#include "platform/host_fault.hpp"
#include <algorithm>
#include <cstdlib>
#include <string>

extern "C" void skyrender_pc_menu_toggle() __attribute__((weak));
namespace SkyGnm {
SKY_SYSV_ABI std::uint32_t sceGnmDrawInitDefaultHardwareState(std::uint32_t*, std::uint32_t);
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
bool handle_fault(SkyHost::Fault& fault) {
    if (fault.kind != SkyHost::FaultKind::access) return false;
    SkyRenderAccessFault state{};
    switch (fault.access) {
    case SkyHost::FaultAccess::unknown: state.access = 0; break;
    case SkyHost::FaultAccess::read: state.access = 1; break;
    case SkyHost::FaultAccess::write: state.access = 2; break;
    case SkyHost::FaultAccess::execute: state.access = 3; break;
    default: return false;
    }
    std::copy(fault.cpu.gpr.begin(), fault.cpu.gpr.end(), state.gpr);
    state.pc = fault.cpu.pc;
    state.flags = fault.cpu.flags;
    state.address = fault.address;
    if (!skyrender_handle_access_fault(&state)) return false;
    std::copy_n(state.gpr, fault.cpu.gpr.size(), fault.cpu.gpr.begin());
    fault.cpu.pc = state.pc;
    fault.cpu.flags = state.flags;
    return true;
}
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
    if(SkyHost::set_environment(option_name(name).c_str(),value,overwrite)!=0)throw std::runtime_error("cannot set renderer option "+option_name(name));
}
const char* option(const char* name) { return std::getenv(option_name(name).c_str()); }
}

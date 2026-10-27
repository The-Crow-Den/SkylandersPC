// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string_view>
#include <string>
class KeyboardPad;

// Optional, privately built GPL bbport GPU/memory component. Unknown APIs stop.
namespace SkyGpu {
bool captures_input();
bool enabled() noexcept;
void configure(const std::string& serial, std::uint32_t sdk, std::uint32_t attributes);
void bind_keyboard(KeyboardPad* pad);
void bind_portal(void (*load)(const char*), void (*remove)(), void (*trap)(const char*), void (*remove_trap)());
bool handle_fault(int signal, void* info, void* context);
void prepare_cpu_write(std::uint64_t address, std::uint64_t size);
void note_cpu_write(std::uint64_t address, std::uint64_t size);
bool supports(std::string_view identity) noexcept;
unsigned stack_arguments(std::string_view identity) noexcept;
std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
std::uint64_t memory_call(std::string_view identity, const std::uint64_t* arguments);
}

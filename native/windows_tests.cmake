# SPDX-License-Identifier: GPL-3.0-or-later
# Windows (MinGW, MSYS2 CLANG64): the host pieces that already have a Windows
# platform layer, and their synthetic tests. The executable itself and the tests
# that enter guest code wait for the Win64 entry bridge (docs/windows-port.md).
include(CTest)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)

add_library(sky-host-portable STATIC ${SKY_HOST_PLATFORM_SOURCES} hle/pure_libc.cpp hle/kernel_sync.cpp
  hle/kernel_memory.cpp hle/offline_network.cpp hle/keyboard_pad.cpp frame_profile.cpp game_hooks.cpp
  trap_team_hooks.cpp)
target_compile_features(sky-host-portable PUBLIC cxx_std_20)
target_compile_options(sky-host-portable PRIVATE -Wall -Wextra -Wconversion -Wshadow)
target_link_libraries(sky-host-portable PUBLIC Threads::Threads OpenSSL::Crypto ws2_32)

if(BUILD_TESTING)
  function(sky_windows_test name source)
    add_executable(${name} ${source})
    target_link_libraries(${name} PRIVATE sky-host-portable)
    add_test(NAME native-${name} COMMAND ${name})
  endfunction()
  sky_windows_test(trap-frame-policy tests/test_trap_frame_policy.cpp)
  sky_windows_test(level-event-protocol tests/test_level_event_protocol.cpp)
  sky_windows_test(pc-settings tests/test_pc_settings.cpp)
  sky_windows_test(trap-probe tests/test_trap_probe.cpp)
  sky_windows_test(trap-metadata tests/test_trap_metadata.cpp)
  sky_windows_test(pure-libc hle/test_pure_libc.cpp)
  sky_windows_test(kernel-sync hle/test_kernel_sync.cpp)
  sky_windows_test(kernel-memory hle/test_kernel_memory.cpp)
  sky_windows_test(local-trophies hle/test_local_trophies.cpp)
  sky_windows_test(offline-network hle/test_offline_network.cpp)
  sky_windows_test(keyboard-pad hle/test_keyboard_pad.cpp)
  sky_windows_test(game-hooks tests/test_game_hooks.cpp)
  sky_windows_test(frame-profile tests/test_frame_profile.cpp)
endif()

cmake_minimum_required(VERSION 3.20)
project(SkyGuestEntryProbe LANGUAGES CXX ASM)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64)$")
  message(FATAL_ERROR "The synthetic guest entry probe requires Linux x86-64")
endif()

find_package(Threads REQUIRED)
add_executable(guest-start-test ../test_guest_start.cpp ../../guest_start.S ../../bridge_features.cpp)
target_compile_features(guest-start-test PRIVATE cxx_std_20)
target_compile_options(guest-start-test PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-Wall;-Wextra;-Wconversion;-Wshadow>)
target_include_directories(guest-start-test PRIVATE ../..)
target_link_libraries(guest-start-test PRIVATE Threads::Threads)
enable_testing()
add_test(NAME synthetic-guest-entry-fs COMMAND guest-start-test)

add_test(NAME synthetic-guest-entry-fs-syscall COMMAND guest-start-test)
set_tests_properties(synthetic-guest-entry-fs-syscall PROPERTIES ENVIRONMENT "SKY_TLS_BRIDGE=syscall")

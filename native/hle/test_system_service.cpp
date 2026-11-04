// SPDX-License-Identifier: GPL-3.0-or-later
#include "system_service.hpp"
#include <array>
#include <cstdlib>
#include <iostream>
#include <stdexcept>

int main() {
    try {
        const auto check = [](bool condition) { if (!condition) throw std::runtime_error("system service language contract failed"); };
        check(SystemService::language_from(nullptr) == 1 && SystemService::language_from("") == 1);
        check(SystemService::language_from("2") == 2 && SystemService::language_from("22") == 22);
        for (const char* bad : {"-1", "31", "fr", "2x"}) {
            bool refused = false;
            try { SystemService::language_from(bad); } catch (const std::runtime_error&) { refused = true; }
            check(refused);
        }
        SystemService service;
        std::int32_t value = -1;
        const std::array<std::uint64_t, 6> args{1, reinterpret_cast<std::uintptr_t>(&value)};
        check(service.call("fZo48un7LK4#libSceSystemService#libSceSystemService", args.data()) == 0);
        check(value == SystemService::language_from(std::getenv("SKY_SYSTEM_LANGUAGE")));
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

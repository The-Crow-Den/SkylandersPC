// SPDX-License-Identifier: GPL-3.0-or-later
#include "../game_hooks.hpp"
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <unistd.h>

namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
}
int main() {
    try {
        const auto root = std::filesystem::temp_directory_path() / ("sky-game-hooks-" + std::to_string(getpid()));
        std::filesystem::create_directories(root);
        { std::ofstream(root / "eboot.bin", std::ios::binary) << "abc"; }
        check(GameHooks::sha256_file((root / "eboot.bin").string()) ==
              "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "SHA-256 mismatch");
        // A matching title ID with an unknown executable must not select hooks.
        check(!GameHooks::configure("CUSA00626", root.string()), "title ID alone selected a build");
        check(!GameHooks::active(), "inactive hooks reported a build");
        GameHooks::frame(false);
        check(!GameHooks::configure("CUSA00626", ""), "empty root selected a build");
        std::filesystem::remove_all(root);
        check(!GameHooks::configure("CUSA00626", root.string()), "missing executable selected a build");
        std::puts("game hooks: exact-build selection checks passed");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "game hooks test failed: %s\n", error.what());
        return 1;
    }
}

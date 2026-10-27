// SPDX-License-Identifier: GPL-3.0-or-later
#include "game_hooks.hpp"
#include "trap_team_hooks.hpp"
#include <array>
#include <atomic>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <openssl/evp.h>

namespace {
std::atomic<const GameHooks::Build*> selected = nullptr;
}
namespace GameHooks {
std::string sha256_file(const std::string& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot open executable for build identity");
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(), &EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1)
        throw std::runtime_error("cannot initialize SHA-256");
    std::array<char, 1 << 16> buffer{};
    while (stream.read(buffer.data(), buffer.size()) || stream.gcount() > 0) {
        if (EVP_DigestUpdate(context.get(), buffer.data(), static_cast<std::size_t>(stream.gcount())) != 1)
            throw std::runtime_error("SHA-256 update failed");
    }
    if (stream.bad()) throw std::runtime_error("cannot read executable for build identity");
    std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
    unsigned length = 0;
    if (EVP_DigestFinal_ex(context.get(), digest.data(), &length) != 1 || length != 32)
        throw std::runtime_error("SHA-256 finalization failed");
    constexpr char digits[] = "0123456789abcdef";
    std::string text(64, '0');
    for (unsigned i = 0; i < 32; ++i) { text[2*i] = digits[digest[i] >> 4]; text[2*i+1] = digits[digest[i] & 15]; }
    return text;
}
const Build* configure(std::string_view title_id, const std::string& game_root) {
    selected = nullptr;
    if (game_root.empty()) return nullptr;
    // Hooks are optional: an absent executable leaves them all disabled.
    if (!std::filesystem::is_regular_file(game_root + "/eboot.bin")) {
        std::fprintf(stderr, "{\"event\":\"game-hooks\",\"build\":null,\"reason\":\"no eboot.bin\"}\n");
        return nullptr;
    }
    const auto digest = sha256_file(game_root + "/eboot.bin");
    for (const auto* build : TrapTeamHooks::builds()) {
        if (build->title_id == title_id && build->executable_sha256 == digest) {
            selected = build;
            std::fprintf(stderr, "{\"event\":\"game-hooks\",\"build\":\"%.*s\"}\n",
                static_cast<int>(build->id.size()), build->id.data());
            return build;
        }
    }
    std::fprintf(stderr, "{\"event\":\"game-hooks\",\"build\":null,\"executable_sha256\":\"%s\"}\n", digest.c_str());
    return nullptr;
}
const Build* active() noexcept { return selected.load(std::memory_order_relaxed); }
void frame(bool pc_menu) {
    if (const auto* build = active(); build && build->frame) build->frame(*build, pc_menu);
}
}

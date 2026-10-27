// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Exact-build game hooks. Shared host code calls only this interface; a
// title's hooks activate when the game root's eboot.bin SHA-256 matches one of
// its registered builds. Title ID alone never selects a hook.
#include <string>
#include <string_view>

namespace GameHooks {
struct Build {
    std::string_view id, title_id, executable_sha256, window_title;
    void (*frame)(const Build& build, bool pc_menu);
};
// Hashes GAME_ROOT/eboot.bin and selects the matching build, or none. A
// missing executable selects none; an unreadable one throws.
const Build* configure(std::string_view title_id, const std::string& game_root);
const Build* active() noexcept;
// Called once per guest GPU submit; does nothing without an exact build.
void frame(bool pc_menu);
std::string sha256_file(const std::string& path);
}

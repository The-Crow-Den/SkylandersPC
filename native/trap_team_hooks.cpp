// SPDX-License-Identifier: GPL-3.0-or-later
#include "trap_team_hooks.hpp"
#include "level_events.hpp"
#include "trap_team_probe.hpp"
#include <array>

namespace {
constexpr std::string_view kTitle = "Skylanders: Trap Team";
void frame(const GameHooks::Build& build, bool pc_menu) {
    LevelEvents::sample(build.id == "us-01-01", pc_menu);
    TrapTeamProbe::frame_clock();
    TrapTeamProbe::sample();
}
constexpr GameHooks::Build eur_0100{"eur-01-00", "CUSA00697",
    "bd5c0433860287599824adb3660964ae623c0505c1300e86cd17e65d5315d3bd", kTitle, &frame};
constexpr GameHooks::Build us_0101{"us-01-01", "CUSA00626",
    "de464fa2c734dd06b1e957098e8d0a20a1acb8599f073811c4a89c09986a4e56", kTitle, &frame};
constexpr std::array<const GameHooks::Build*, 2> registered{&eur_0100, &us_0101};
}
namespace TrapTeamHooks {
std::span<const GameHooks::Build* const> builds() { return registered; }
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "trap_team_hooks.hpp"
#include "level_events.hpp"
#include "trap_team_probe.hpp"
#include "trap_movie_skip.hpp"
#include "hle/keyboard_pad.hpp"
#include <array>

namespace {
constexpr std::string_view kTitle = "Skylanders: Trap Team";
void skip_movies(bool pc_menu) {
    static const auto settings = TrapMovieSkip::settings_from_environment();
    if (!settings.any) return;
    static TrapMovieSkip::Skipper skipper;
    const auto presses = KeyboardPad::presses.exchange(0);
    const auto movies = TrapMovieGate::sample(TrapTeamProbe::read);
    skipper.frame(movies.data, movies.count, movies.valid, presses, pc_menu, settings, TrapTeamProbe::read,
        [](std::uintptr_t state) {
            // Guest memory is mapped at its guest address in this process.
            std::int32_t expected = TrapMovieSkip::kPlay;
            return __atomic_compare_exchange_n(reinterpret_cast<std::int32_t*>(state), &expected,
                TrapMovieSkip::kEnded, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);
        },
        [](const TrapMovieSkip::Skipped& movie) {
            std::fprintf(stderr, "{\"event\":\"trap-movie-skipped\",\"observed_us\":%llu,\"movie\":\"%s\"}\n",
                static_cast<unsigned long long>(TrapTeamProbe::timestamp()), movie.name.c_str());
        });
}
void frame(const GameHooks::Build& build, bool pc_menu) {
    LevelEvents::sample(build.id == "us-01-01", pc_menu);
    // Movie layout offsets are verified only for the US 01.01 executable.
    if (build.id == "us-01-01") skip_movies(pc_menu);
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

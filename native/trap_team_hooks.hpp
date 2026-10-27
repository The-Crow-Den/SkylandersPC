// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "game_hooks.hpp"
#include <span>

// Trap Team builds whose fixed guest addresses were observed. Hashes match
// profiles/trap-team.json validated_builds.
namespace TrapTeamHooks {
std::span<const GameHooks::Build* const> builds();
}

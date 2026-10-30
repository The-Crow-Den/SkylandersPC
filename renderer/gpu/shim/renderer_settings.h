// SPDX-License-Identifier: GPL-2.0-or-later
// renderer: user settings changed at run time from the in-game menu (renderer_overlay.h) and kept
// in renderer.ini (SKY_RENDERER_CONFIG overrides the path). Readers load the atomics every frame;
// writers are the menu and Load().

#pragma once
#include <atomic>

namespace SkySettings {

enum class MenuLanguage { English, Russian };

struct Values {
    std::atomic<MenuLanguage> menu_language{MenuLanguage::Russian};
    /// Chosen in the menu (or already in renderer.ini): only then is it saved, so the language
    /// the menu merely started with keeps following the launcher's (#134).
    std::atomic<bool> menu_language_chosen{false};
    std::atomic<bool> show_fps{false};
};

Values& Get();
/// Localized overlay text; the Language selector itself stays in English.
const char* MenuText(const char* english, const char* russian);

/// Reads the file. Called once at start.
void Load();
/// Writes the file (menu changes).
void Save();

} // namespace SkySettings

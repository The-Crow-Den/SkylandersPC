// SPDX-License-Identifier: GPL-2.0-or-later
#include "renderer_settings.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>

namespace SkySettings {

namespace {

// The file was called bbport.ini before the rename: take it over once, in the same directory.
void AdoptLegacyFile(const std::string& path) {
    const auto slash = path.find_last_of('/');
    const std::string legacy = (slash == std::string::npos ? "" : path.substr(0, slash + 1)) + "bbport.ini";
    if (std::FILE* current = std::fopen(path.c_str(), "rb")) {
        std::fclose(current);
        return;
    }
    if (std::rename(legacy.c_str(), path.c_str()) == 0)
        std::printf("Settings: moved %s to %s\n", legacy.c_str(), path.c_str());
}

const char* Path() {
    const char* env = std::getenv("SKY_RENDERER_CONFIG");
    const char* path = env && env[0] ? env : "renderer.ini";
    static const bool adopted = (AdoptLegacyFile(path), true);
    (void)adopted;
    return path;
}

void Set(Values& v, const std::string& key, const std::string& value) {
    if (key == "menu_language") {
        if (value == "en") v.menu_language = MenuLanguage::English;
        else if (value == "ru") v.menu_language = MenuLanguage::Russian;
        else std::printf("Settings: unknown menu_language '%s' (expected en or ru)\n", value.c_str());
        v.menu_language_chosen = value == "en" || value == "ru";
    } else if (key == "show_fps") {
        v.show_fps = std::atoi(value.c_str()) != 0;
    }
}

} // namespace

Values& Get() {
    static Values values;
    return values;
}

const char* MenuText(const char* english, const char* russian) {
    return Get().menu_language == MenuLanguage::Russian ? russian : english;
}

void Load() {
    auto& v = Get();
    // renderer: the menu's language until one is chosen in it (menu_language in renderer.ini): the
    // launcher's (SKY_RENDERER_MENU_LANGUAGE), else the system's, as the launcher picks its own.
    {
        const char* lang = std::getenv("SKY_RENDERER_MENU_LANGUAGE");
        if (!lang || !*lang) {
            for (const char* key : {"LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"}) {
                if (const char* value = std::getenv(key); value && *value) {
                    lang = value;
                    break;
                }
            }
        }
        v.menu_language = lang && (lang[0] == 'r' || lang[0] == 'R') && (lang[1] == 'u' || lang[1] == 'U')
                              ? MenuLanguage::Russian
                              : MenuLanguage::English;
    }
    if (FILE* file = std::fopen(Path(), "r")) {
        char line[256];
        while (std::fgets(line, sizeof(line), file)) {
            std::string text{line};
            text.erase(text.find_last_not_of(" \t\r\n") + 1);
            const auto eq = text.find('=');
            if (text.empty() || text[0] == '#' || eq == std::string::npos) {
                continue;
            }
            Set(v, text.substr(0, eq), text.substr(eq + 1));
        }
        std::fclose(file);
        std::printf("Settings: %s\n", Path());
    }
}

void Save() {
    const auto& v = Get();
    // The keys the menu writes, in this order; the rest of the file stays as it is: the
    // launcher's controls (key.* / pad.*) and its other keys, comments.
    std::vector<std::pair<std::string, std::string>> keys;
    const auto put = [&](const char* key, std::string value) { keys.emplace_back(key, std::move(value)); };
    const auto flag = [](bool value) { return std::string(value ? "1" : "0"); };
    if (v.menu_language_chosen) {
        put("menu_language", v.menu_language == MenuLanguage::Russian ? "ru" : "en");
    }
    put("show_fps", flag(v.show_fps));
    std::string out;
    bool had_lines = false;
    std::vector<bool> written(keys.size());
    if (FILE* file = std::fopen(Path(), "r")) {
        char line[512];
        while (std::fgets(line, sizeof(line), file)) {
            had_lines = true;
            std::string text{line};
            text.erase(text.find_last_not_of("\r\n") + 1);
            const auto eq = text.find('=');
            if (!text.empty() && text[0] != '#' && eq != std::string::npos) {
                std::string key = text.substr(0, eq);
                key.erase(key.find_last_not_of(" \t") + 1);
                key.erase(0, key.find_first_not_of(" \t"));
                const auto it = std::find_if(keys.begin(), keys.end(),
                                             [&](const auto& k) { return k.first == key; });
                if (it != keys.end()) {
                    out += it->first + "=" + it->second + "\n";
                    written[size_t(it - keys.begin())] = true;
                    continue;
                }
            }
            out += text + "\n";
        }
        std::fclose(file);
    }
    if (!had_lines) {
        out = "# renderer settings (in-game menu: Insert / L3+R3)\n";
    }
    for (size_t k = 0; k < keys.size(); ++k) {
        if (!written[k]) {
            out += keys[k].first + "=" + keys[k].second + "\n";
        }
    }
    // Replaced whole: a crash while writing leaves the old file.
    const std::string temporary = std::string(Path()) + ".tmp";
    FILE* file = std::fopen(temporary.c_str(), "w");
    bool ok = file && std::fwrite(out.data(), 1, out.size(), file) == out.size();
    ok = file && std::fclose(file) == 0 && ok;
    if (!ok || std::rename(temporary.c_str(), Path()) != 0) {
        std::printf("Settings: cannot write %s\n", Path());
    }
}

} // namespace SkySettings

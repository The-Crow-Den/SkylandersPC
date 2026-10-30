// SPDX-License-Identifier: GPL-2.0-or-later
// renderer_settings.cpp: the menu saves its keys into renderer.ini and keeps the launcher's (controls).
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <unistd.h>
#include "gpu/shim/renderer_settings.h"

static std::string Read(const char* path) {
    std::ifstream file(path);
    std::stringstream text;
    text << file.rdbuf();
    return text.str();
}

int main() {
    char path[] = "/tmp/renderer-settings-test-XXXXXX";
    const int fd = mkstemp(path);
    assert(fd >= 0);
    const char ini[] = "# launcher\nupscaler=fsr3\nkey.cross=X, Space\npad.circle=a\nshow_fps=0\n"
                       "fullscreen_hint=1\n";
    assert(write(fd, ini, sizeof(ini) - 1) == ssize_t(sizeof(ini) - 1));
    close(fd);
    setenv("SKY_RENDERER_CONFIG", path, 1);

    SkySettings::Load();
    auto& s = SkySettings::Get();
    assert(!s.show_fps);
    s.show_fps = true;
    SkySettings::Save();

    const std::string saved = Read(path);
    // The launcher's controls, its other keys (an old upscaler key too) and comments stay; the
    // menu's keys are replaced in place.
    assert(saved == "# launcher\nupscaler=fsr3\nkey.cross=X, Space\npad.circle=a\nshow_fps=1\n"
                    "fullscreen_hint=1\n");

    s.show_fps = false;
    SkySettings::Load();
    assert(s.show_fps);
    assert(saved.find("menu_language=") == std::string::npos); // only started with it (#134)

    // A language chosen in the menu is saved and wins over the launcher's from then on.
    s.menu_language = SkySettings::MenuLanguage::Russian;
    s.menu_language_chosen = true;
    SkySettings::Save();
    assert(Read(path).find("menu_language=ru\n") != std::string::npos);
    setenv("SKY_RENDERER_MENU_LANGUAGE", "en", 1);
    s.menu_language_chosen = false;
    SkySettings::Load();
    assert(s.menu_language == SkySettings::MenuLanguage::Russian && s.menu_language_chosen);
    unlink(path);
    std::puts("PASS: settings save keeps other keys, FPS counter, menu language");
}

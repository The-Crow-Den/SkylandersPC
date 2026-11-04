// SPDX-License-Identifier: GPL-3.0-or-later
// Lists connected portals as JSON for the launcher and run_session.
// --identify resets each portal to read its model and capabilities.
#include "transport.hpp"
#include <cstdio>
#include <cstring>
#include <string>

namespace {
std::string quoted(const std::string& text) {
    std::string out = "\"";
    for (const char c : text) {
        if (c == '"' || c == '\\') out += '\\';
        if (static_cast<unsigned char>(c) >= 0x20) out += c;
    }
    return out + '"';
}
}
int main(int argc, char** argv) {
    const bool probe = argc > 1 && std::strcmp(argv[1], "--identify") == 0;
    std::printf("[");
    bool first = true;
    for (auto info : PortalDevice::enumerate()) {
        std::string state = "listed";
        if (probe) {
            auto transport = info.family == PortalDevice::Family::hid ? PortalDevice::open_hid(info) : PortalDevice::open_xbox(info);
            if (!transport) state = "no-access";
            else if (!PortalDevice::identify(*transport)) state = "no-reply";
            else { info = transport->info(); state = info.identified ? "identified" : "unknown-model"; }
        }
        std::printf("%s\n  {\"id\":%s,\"name\":%s,\"family\":\"%s\",\"vendor\":\"%04x\",\"product\":\"%04x\",\"state\":\"%s\","
                    "\"traps\":%s,\"audio\":%s,\"leds\":%s}",
            first ? "" : ",", quoted(info.id).c_str(), quoted(info.name).c_str(), PortalDevice::family_name(info.family),
            info.vendor, info.product, state.c_str(),
            info.caps.traps ? "true" : "false", info.caps.audio ? "true" : "false", info.caps.leds ? "true" : "false");
        first = false;
    }
    std::printf("%s]\n", first ? "" : "\n");
    return 0;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Portal protocol core and the real-portal USB bus, driven by a synthetic
// transcript. No hardware and no figure contents are involved.
#include "../portal_device/protocol.hpp"
#include "../portal_device/transport.hpp"
#include "../hle/real_portal_bus.hpp"
#include <libusb.h>
#include <algorithm>
#include <array>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace {
using namespace PortalDevice;
using U = std::uint64_t;
void check(bool ok, const char* what) { if (!ok) throw std::runtime_error(what); }

struct Step { bool host; Report report{}; };
std::vector<Step> load(const std::filesystem::path& path) {
    std::ifstream input(path); std::string line; std::vector<Step> steps;
    while (std::getline(input, line)) {
        if (line.size() < 2 || (line[0] != '>' && line[0] != '<')) continue;
        Step step{line[0] == '>'};
        std::istringstream bytes(line.substr(2)); unsigned value = 0; std::size_t i = 0;
        while (bytes >> std::hex >> value && i < report_size) step.report[i++] = static_cast<std::uint8_t>(value);
        steps.push_back(step);
    }
    return steps;
}
// The HID portal's USB shape: device descriptor, then one configuration with
// a HID interface and interrupt IN 0x81 / OUT 0x02 endpoints. Synthetic.
std::vector<std::uint8_t> descriptors() {
    return {18, 1, 0x00, 0x02, 0, 0, 0, 64, 0x30, 0x14, 0x50, 0x01, 0x00, 0x01, 1, 2, 0, 1,
            9, 2, 41, 0, 1, 1, 0, 0x80, 0xfa,
            9, 4, 0, 0, 2, 3, 0, 0, 0,
            9, 0x21, 0x11, 1, 0, 1, 0x22, 0x1d, 0,
            7, 5, 0x81, 3, 64, 0, 1,
            7, 5, 0x02, 3, 64, 0, 1};
}
class Scripted final : public Transport {
public:
    explicit Scripted(std::vector<Step> steps) : Transport(make()), steps_(std::move(steps)) { deliver(); }
    bool write_report(std::span<const std::uint8_t> report) override {
        Report sent{}; std::copy_n(report.begin(), std::min(report.size(), report_size), sent.begin());
        writes.push_back(sent);
        if (sent[0] == 'Q' || sent[0] == 'W') {
            // All-zero figure store with a fixed synthetic identity in block 0.
            if (sent[0] == 'Q' && sent[2] == 0) replies_.push_back({'S', 1, 0, 0, 0, 7, 1});
            Report reply{sent[0], sent[1], sent[2]};
            if (sent[0] == 'Q' && sent[2] == 0) { reply[3] = 0xa1; reply[4] = 0xb2; reply[5] = 0xc3; reply[6] = 0xd4; }
            replies_.push_back(reply);
            return true;
        }
        if (at_ >= steps_.size() || !steps_[at_].host || steps_[at_].report != sent) throw std::runtime_error("report differs from transcript");
        ++at_; deliver(); return true;
    }
    int read_report(std::span<std::uint8_t> output, int) override {
        if (replies_.empty()) return 0;
        const auto reply = replies_.front(); replies_.pop_front();
        const auto count = std::min(output.size(), report_size);
        std::copy_n(reply.begin(), count, output.begin());
        return static_cast<int>(count);
    }
    bool write_audio(std::span<const std::uint8_t> pcm) override { audio += pcm.size(); return true; }
    std::vector<Report> writes;
    std::size_t audio = 0;
private:
    static Info make() {
        Info info; info.id = "test:transcript"; info.name = "Transcript portal"; info.family = Family::hid;
        info.vendor = 0x1430; info.product = 0x0150; info.usb_descriptors = descriptors(); info.report_descriptor = {6, 0, 0xff};
        return info;
    }
    void deliver() { while (at_ < steps_.size() && !steps_[at_].host) replies_.push_back(steps_[at_++].report); }
    std::vector<Step> steps_;
    std::size_t at_ = 0;
    std::deque<Report> replies_;
};

U call(const char* nid, std::array<U, 12> args = {}) {
    return RealPortalBus::call(std::string(nid) + "#libSceUsbd#libSceUsbd", args.data());
}
template <class T> U ptr(T* p) { return reinterpret_cast<U>(p); }
U control(libusb_device_handle* handle, Report& report, std::size_t length = report_size) {
    return call("RRKFcKQ1Ka4", {ptr(handle), 0x21, 9, 0x200, 0, ptr(report.data()), length, 100});
}
Report next_reply(libusb_device_handle* handle, libusb_transfer* transfer, char kind) {
    Report buffer{};
    for (unsigned tries = 0; tries < 16; ++tries) {
        check(call("t3J5pXxhJlI", {ptr(transfer), ptr(handle), 0x81, ptr(buffer.data()), report_size, 0, 0, 50}) == 0, "fill");
        check(call("L0EHgZZNVas", {ptr(transfer)}) == 0, "submit");
        check(call("EkqGLxWC-S0") == 0, "handle events");
        if (transfer->actual_length && buffer[0] == kind) return buffer;
    }
    throw std::runtime_error("reply never arrived");
}
}

int main(int argc, char** argv) {
    try {
        const std::filesystem::path transcript = argc > 1 ? argv[1] : "native/tests/data/portal_transcript_hid.txt";
        const auto steps = load(transcript);
        check(steps.size() >= 8, "transcript loads");

        // Protocol core.
        const Report traptanium{'R', 0x02, 0x18}, imaginators{'R', 0x02, 0x0a, 0x05, 0x08}, odd{'R', 0x7f, 0x7f};
        check(PortalDevice::identify(traptanium).caps.traps && PortalDevice::identify(traptanium).caps.audio, "traptanium caps");
        check(PortalDevice::identify(imaginators).name == "Imaginators portal" && !PortalDevice::identify(imaginators).caps.traps, "imaginators");
        check(!PortalDevice::identify(odd).known, "unknown model is not guessed");
        const Report status_reply{'S', 0x01, 0, 0, 0x80, 9, 1};
        const auto status = parse_status(status_reply);
        check(status && status->state[0] == SlotState::present && status->state[15] == SlotState::removed && status->active, "status");
        check(query(3, 9)[1] == 0x13 && query(3, 9)[2] == 9, "query encoding");
        check(write_target(write(2, 5, std::array<std::uint8_t, 16>{}))->first == 2, "write target");

        // Identification over a transport.
        Scripted probe(steps);
        check(PortalDevice::identify(probe) && probe.info().identified && probe.info().name == "Traptanium portal", "identify");

        // The USB bus presents the attached device's own identity.
        const auto backups = std::filesystem::temp_directory_path() / ("sky-portal-test-" + std::to_string(getpid()));
        std::filesystem::remove_all(backups);
        Scripted* live = nullptr;
        RealPortalBus::configure([&] { auto t = std::make_unique<Scripted>(steps); live = t.get(); return t; }, backups, false);
        check(call("TOhg7P6kTH4") == 0, "init");
        libusb_device** devices = nullptr;
        check(call("8qB9Ar4P5nc", {ptr(&devices)}) == 1 && devices[0] && !devices[1], "device list");
        libusb_device_descriptor descriptor{};
        check(call("bhomgbiQgeo", {ptr(devices[0]), ptr(&descriptor)}) == 0 && descriptor.idVendor == 0x1430 && descriptor.idProduct == 0x0150, "descriptor");
        libusb_config_descriptor* config = nullptr;
        check(call("Dkm5qe8j3XE", {ptr(devices[0]), 0, ptr(&config)}) == 0, "config");
        const auto& alt = config->interface[0].altsetting[0];
        check(config->bNumInterfaces == 1 && alt.bInterfaceClass == 3 && alt.bNumEndpoints == 2 && alt.extra_length == 9 &&
              alt.endpoint[0].bEndpointAddress == 0x81 && alt.endpoint[1].bEndpointAddress == 0x02, "config parse");
        check(call("Hvd3S--n25w", {ptr(config)}) == 0, "free config");
        check(call("vrQXYRo1Gwk", {0x1430, 0x1f17}) == 0, "other identity is absent");
        auto* handle = reinterpret_cast<libusb_device_handle*>(call("vrQXYRo1Gwk", {0x1430, 0x0150}));
        check(handle, "open by vid/pid");
        std::array<std::uint8_t, 64> raw{};
        check(call("RRKFcKQ1Ka4", {ptr(handle), 0x80, 6, 0x0200, 0, ptr(raw.data()), 64, 100}) == 41 && raw[1] == 2, "get config descriptor");
        check(call("RRKFcKQ1Ka4", {ptr(handle), 0x80, 6, 0x0300, 0, ptr(raw.data()), 64, 100}) >= 0x80240000, "no invented strings");

        auto* transfer = reinterpret_cast<libusb_transfer*>(call("0ktE1PhzGFU"));
        check(transfer, "alloc");
        Report report = reset();
        check(control(handle, report) == report_size, "send reset");
        check(next_reply(handle, transfer, 'R')[2] == 0x18, "reset reply");
        report = activate(true); check(control(handle, report) == report_size, "activate");
        check(next_reply(handle, transfer, 'A')[3] == 0x77, "activate reply");
        report = colour(0, 0x40, 0); check(control(handle, report) == report_size, "colour");
        report = audio(true); check(control(handle, report) == report_size, "audio on");
        check(next_reply(handle, transfer, 'M')[3] == 0x19, "audio reply");

        // Figure writes are refused unless allowed.
        const std::array<std::uint8_t, 16> zero{};
        report = write(0, 5, zero);
        check(control(handle, report) >= 0x80240000, "write refused by default");
        check(!std::filesystem::exists(backups), "no backup without a write");
        check(call("-sgi7EeLSO8", {ptr(transfer)}) == 0 && call("EQ6SCLMqzkM", {ptr(devices), 1}) == 0 && call("Fq6+0Fm55xU") == 0, "teardown");

        // Allowed writes back the figure up first, once per figure.
        RealPortalBus::configure([&] { auto t = std::make_unique<Scripted>(std::vector<Step>{}); live = t.get(); return t; }, backups, true);
        check(call("TOhg7P6kTH4") == 0, "init again");
        handle = reinterpret_cast<libusb_device_handle*>(call("vrQXYRo1Gwk", {0x1430, 0x0150}));
        report = write(0, 5, zero);
        check(control(handle, report) == report_size, "allowed write");
        unsigned files = 0;
        for (const auto& entry : std::filesystem::directory_iterator(backups)) {
            ++files;
            struct stat info{};
            check(stat(entry.path().c_str(), &info) == 0 && (info.st_mode & 0777) == 0600, "backup is private");
            check(std::filesystem::file_size(entry) == 1024 && entry.path().filename().string().rfind("a1b2c3d4-", 0) == 0, "backup contents");
        }
        check(files == 1, "one backup");
        check(live->writes.size() == figure_blocks + 1 && live->writes.back()[0] == 'W', "write forwarded after backup");
        check(control(handle, report) == report_size && live->writes.size() == figure_blocks + 2, "second write needs no backup");
        transfer = reinterpret_cast<libusb_transfer*>(call("0ktE1PhzGFU"));
        check(next_reply(handle, transfer, 'S')[5] == 7, "status read during backup reaches the game");
        std::array<std::uint8_t, 64> pcm{};
        check(call("t3J5pXxhJlI", {ptr(transfer), ptr(handle), 0x02, ptr(pcm.data()), 64, 0, 0, 50}) == 0 &&
              call("L0EHgZZNVas", {ptr(transfer)}) == 0 && call("EkqGLxWC-S0") == 0 && live->audio == 64, "speaker packet");
        check(call("-sgi7EeLSO8", {ptr(transfer)}) == 0 && call("Fq6+0Fm55xU") == 0, "teardown again");
        std::filesystem::remove_all(backups);
        std::cout << "portal device tests passed\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}

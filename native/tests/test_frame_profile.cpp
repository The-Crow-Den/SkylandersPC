// SPDX-License-Identifier: GPL-3.0-or-later
#include "../frame_profile.hpp"
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <unistd.h>

namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::vector<std::string> split(const std::string& line) {
    std::vector<std::string> fields; std::stringstream stream(line); std::string field;
    while (std::getline(stream, field, ',')) fields.push_back(field);
    return fields;
}
}
int main() {
    try {
        check(!FrameProfile::enabled(), "profile enabled without configuration");
        FrameProfile::frame(); // Disabled: must be a no-op.
        const auto path = std::filesystem::temp_directory_path() / ("sky-frame-profile-" + std::to_string(getpid()) + ".csv");
        setenv("SKY_FRAME_PROFILE", path.c_str(), 1);
        FrameProfile::configure();
        check(FrameProfile::enabled(), "profile not enabled");
        FrameProfile::thread_started(true);
        FrameProfile::record(FrameProfile::Bucket::Gpu, 2000000);
        std::thread worker([] {
            FrameProfile::thread_started(false);
            FrameProfile::record(FrameProfile::Bucket::Sync, 3000000);
            volatile unsigned long spin = 0; for (unsigned long i = 0; i < 20000000; ++i) spin = spin + i;
            FrameProfile::thread_finished();
        });
        worker.join();
        FrameProfile::frame();
        FrameProfile::frame();
        // Force the buffered rows out by filling the flush interval.
        for (int i = 0; i < 60; ++i) FrameProfile::frame();
        std::ifstream input(path);
        std::string header, first, second;
        std::getline(input, header); std::getline(input, first); std::getline(input, second);
        const auto names = split(header), row = split(first), quiet = split(second);
        check(names.size() == 16 && row.size() == 16 && quiet.size() == 16, "unexpected column count");
        const auto column = [&](const std::vector<std::string>& values, const char* name) {
            for (std::size_t i = 0; i < names.size(); ++i) if (names[i] == name) return std::stod(values[i]);
            throw std::runtime_error(std::string("missing column ") + name);
        };
        check(column(row, "main_gpu_ms") == 2.0 && column(row, "all_gpu_ms") == 2.0, "main GPU service time");
        check(column(row, "main_sync_ms") == 0.0 && column(row, "all_sync_ms") == 3.0, "worker sync time");
        check(column(row, "service_calls") == 2, "service call count");
        check(column(row, "worker_cpu_ms") > 0.0, "retired worker CPU time missing");
        check(column(quiet, "all_gpu_ms") == 0.0 && column(quiet, "service_calls") == 0, "second frame not a delta");
        std::filesystem::remove(path);
        std::puts("frame profile: per-frame deltas and thread accounting passed");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "frame profile test failed: %s\n", error.what());
        return 1;
    }
}

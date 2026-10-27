// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_file.hpp"
#include <array>
#include <chrono>
#include <fcntl.h>
#include <future>
#include <sys/stat.h>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unistd.h>

int main() {
    std::filesystem::path directory;
    try {
        using U = std::uint64_t;
        const auto check = [](bool value) { if (!value) throw std::runtime_error("file contract failed"); };
        const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
        char pattern[] = "/tmp/skylanders-files-XXXXXX";
        auto* path = mkdtemp(pattern);
        check(path); directory = path;
        std::filesystem::create_directory(directory / "game");
        std::ofstream(directory / "game/data.bin") << "abcdef";
        std::ofstream(directory / "outside.bin") << "outside";
        std::filesystem::create_symlink(directory / "outside.bin", directory / "game/link.bin");
        {
            KernelFile files;
            files.configure((directory / "game").string());
            const auto call = [&](const char* nid, std::array<U, 6> args = {}) {
                return files.call(std::string(nid) + "#libkernel#libkernel", args.data());
            };
            check(!KernelFile::supports("1G3lF1Gg1k8#wrong#libkernel"));
            const auto fd = call("1G3lF1Gg1k8", {pointer("/app0/data.bin"), 0});
            check(fd >= 3 && fd < 1024);
            std::array<char, 8> data{};
            check(call("Cg4srZ6TKbU", {fd, pointer(data.data()), 3}) == 3);
            check(std::string(data.data(), 3) == "abc");
            check(call("+r3rMFwItV4", {fd, pointer(data.data()), 3, 1}) == 3);
            check(std::string(data.data(), 3) == "bcd");
            check(call("oib76F-12fk", {fd, 0, 1}) == 3);
            std::array<unsigned char, 120> stat{};
            check(call("kBwCPsYX-m4", {fd, pointer(stat.data())}) == 0);
            std::int64_t size = 0;
            std::memcpy(&size, stat.data() + 72, sizeof(size));
            check(size == 6);
            check(call("UK2Tl2DWUns", {fd}) == 0);
            check(static_cast<std::int64_t>(call("Cg4srZ6TKbU", {fd, pointer(data.data()), 1})) < 0);
            for (const char* denied : {"/app0/../outside.bin", "/app0/link.bin", "/etc/passwd"})
                check(static_cast<std::int64_t>(call("1G3lF1Gg1k8", {pointer(denied), 0})) < 0);
            check(static_cast<std::int64_t>(call("1G3lF1Gg1k8", {pointer("/app0/data.bin"), 0x401})) < 0);
            check(std::filesystem::file_size(directory / "game/data.bin") == 6);

            // A read blocked on one descriptor must not stall other file calls.
            check(mkfifo((directory / "game/stream").c_str(), 0600) == 0);
            const int writer = open((directory / "game/stream").c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
            check(writer >= 0);
            const auto stream = call("1G3lF1Gg1k8", {pointer("/app0/stream"), 0});
            check(stream >= 3 && stream < 1024);
            std::array<char, 4> streamed{};
            auto blocked = std::async(std::launch::async, [&] {
                return call("Cg4srZ6TKbU", {stream, pointer(streamed.data()), 2});
            });
            check(blocked.wait_for(std::chrono::milliseconds(50)) == std::future_status::timeout);
            auto other = std::async(std::launch::async, [&] {
                const auto again = call("1G3lF1Gg1k8", {pointer("/app0/data.bin"), 0});
                std::array<char, 2> bytes{};
                const auto count = call("Cg4srZ6TKbU", {again, pointer(bytes.data()), 2});
                call("UK2Tl2DWUns", {again});
                return count;
            });
            const bool independent = other.wait_for(std::chrono::seconds(2)) == std::future_status::ready;
            check(write(writer, "xy", 2) == 2);
            check(blocked.get() == 2 && std::string(streamed.data(), 2) == "xy");
            check(independent && other.get() == 2);
            check(call("UK2Tl2DWUns", {stream}) == 0);
            close(writer);
        }
        std::filesystem::remove_all(directory);
        std::cout << "read-only game file and directory confinement tests passed\n";
    } catch (const std::exception& e) {
        if (!directory.empty()) std::filesystem::remove_all(directory);
        std::cerr << e.what() << '\n'; return 1;
    }
}

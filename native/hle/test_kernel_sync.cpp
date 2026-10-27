// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_sync.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
#include <future>

int main() {
    try {
        KernelSync service;
        const auto invoke = [&](const char* nid, std::uint64_t* handle, std::uint64_t second = 0) {
            const std::string name = std::string(nid) + "#libkernel#libkernel";
            const std::array<std::uint64_t, 6> args{reinterpret_cast<std::uintptr_t>(handle), second};
            return service.call(name, args.data());
        };
        const auto check = [](bool condition) { if (!condition) throw std::runtime_error("kernel synchronization contract failed"); };
        check(!KernelSync::supports("F8bUHwAG284#wrong#libkernel"));
        check(invoke("F8bUHwAG284", nullptr) == 0x80020016);
        std::uint64_t attr = 0, mutex = 0;
        check(invoke("F8bUHwAG284", &attr) == 0 && attr != 0);
        check(invoke("iMp8QpE+XO4", &attr, 0) == 0x80020016);
        check(invoke("1FGvU0i9saQ", &attr, 1) == 0x8002002d);
        check(invoke("iMp8QpE+XO4", &attr, 2) == 0);
        check(invoke("cmo1RIYva9o", &mutex, reinterpret_cast<std::uintptr_t>(&attr)) == 0);
        check(invoke("smWEktiyyG0", &attr) == 0 && attr == 0);
        check(invoke("9UK1vLZQft4", &mutex) == 0);
        check(invoke("9UK1vLZQft4", &mutex) == 0); // recursive
        check(invoke("2Of0f+3mhhE", &mutex) == 0x80020010); // busy
        check(invoke("tn3VlD0hG60", &mutex) == 0);
        check(invoke("tn3VlD0hG60", &mutex) == 0);
        check(invoke("2Of0f+3mhhE", &mutex) == 0 && mutex == 2);
        check(invoke("9UK1vLZQft4", &mutex) == 0x80020016);
        mutex = 0;
        check(invoke("IafI2PxcPnQ", &mutex, 1000) == 0);
        auto timed = std::async(std::launch::async, [&] { return invoke("IafI2PxcPnQ", &mutex, 1000); });
        check(timed.get() == 60);
        check(invoke("tn3VlD0hG60", &mutex) == 0);
        check(invoke("IafI2PxcPnQ", &mutex, 0) == 0);
        check(invoke("tn3VlD0hG60", &mutex) == 0);
        check(invoke("9UK1vLZQft4", &mutex) == 0); // lazy default
        check(invoke("9UK1vLZQft4", &mutex) == 0x8002000b); // deadlock detection
        check(invoke("tn3VlD0hG60", &mutex) == 0);
        check(invoke("tn3VlD0hG60", &mutex) == 0x80020001); // wrong ownership
        check(invoke("2Of0f+3mhhE", &mutex) == 0);
        std::cout << "kernel synchronization tests passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}

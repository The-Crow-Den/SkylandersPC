// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_memory.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

int main() {
    try {
        KernelMemory memory;
        const auto call = [&](const char* nid, std::array<std::uint64_t, 6> args = {}) {
            return memory.call(std::string(nid) + "#libkernel#libkernel", args.data());
        };
        const auto check = [](bool condition) { if (!condition) throw std::runtime_error("memory contract failed"); };
        const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
        check(!KernelMemory::supports("pO96TwzOm5E#wrong#libkernel"));
        const auto size = call("pO96TwzOm5E");
        std::uint64_t physical = 99;
        check(call("rTXw65xmLIA", {0, size, 16385, 16384, 0, pointer(&physical)}) == 0x80020016);
        check(call("rTXw65xmLIA", {0, size, 16384, 16384, 0, pointer(&physical)}) == 0 && physical == 0);
        std::uint64_t first = 0, second = 0;
        check(call("L-Q3LEjIbgA", {pointer(&first), 16384, 3, 0, physical, 16384}) == 0);
        check(call("L-Q3LEjIbgA", {pointer(&second), 16384, 3, 0, physical, 16384}) == 0);
        check(first != second && first < (1ull << 40) && second < (1ull << 40));
        *reinterpret_cast<std::uint64_t*>(first) = 0x123456789abcdef0;
        check(*reinterpret_cast<std::uint64_t*>(second) == 0x123456789abcdef0); // aliases
        auto collision = first;
        check(call("L-Q3LEjIbgA", {pointer(&collision), 16384, 3, 0x10, physical, 16384}) == 0x8002000c);
        check(*reinterpret_cast<std::uint64_t*>(first) == 0x123456789abcdef0);
        check(call("cQke9UuBQOk", {first, 16384}) == 0);
        check(call("cQke9UuBQOk", {second, 16384}) == 0);
        check(call("MBuItvba6z8", {physical, 16384}) == 0);
        std::uint64_t flexible = 0;
        check(call("IWIBBdTHit4", {pointer(&flexible), 16384, 3, 0}) == 0);
        check(*reinterpret_cast<std::uint64_t*>(flexible) == 0);
        check(call("cQke9UuBQOk", {flexible, 16384}) == 0);
        check(call("IWIBBdTHit4", {pointer(&flexible), 449ull * 1024 * 1024, 3, 0}) == 0x8002000c);
        std::cout << "kernel memory alias, collision and budget tests passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "../gpu_backend.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

int main() {
    try {
        using U = std::uint64_t;
        const auto check = [](bool value) { if (!value) throw std::runtime_error("GPU adapter contract failed"); };
        const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
        check(SkyGpu::enabled());
        check(!SkyGpu::supports("Idffwf3yh8s#wrong#libSceGnmDriver"));
        check(SkyGpu::stack_arguments("xbxNatawohc#libSceGnmDriver#libSceGnmDriver") == 3);
        std::array<std::uint32_t, 4096> commands{};
        const std::array<U, 12> draw{pointer(commands.data()), commands.size()};
        check(SkyGpu::call("Idffwf3yh8s#libSceGnmDriver#libSceGnmDriver", draw.data()) == 256);
        check(commands[0] != 0);
        const auto memory = [&](const char* nid, std::array<U, 12> args = {}) {
            return SkyGpu::memory_call(std::string(nid) + "#libkernel#libkernel", args.data());
        };
        const auto total = memory("pO96TwzOm5E");
        U physical = 0, first = 0, second = 0;
        check(memory("rTXw65xmLIA", {0, total, 16384, 16384, 0, pointer(&physical)}) == 0);
        check(memory("L-Q3LEjIbgA", {pointer(&first), 16384, 3, 0, physical, 16384}) == 0);
        check(memory("L-Q3LEjIbgA", {pointer(&second), 16384, 3, 0, physical, 16384}) == 0);
        std::array<U, 10> query{};
        query[9] = 0xabcdef;
        check(SkyGpu::supports("rVjRvHJ0X6c#libkernel#libkernel"));
        check(!SkyGpu::supports("rVjRvHJ0X6c#wrong#libkernel"));
        check(memory("rVjRvHJ0X6c", {first + 8, 0, pointer(query.data()), 72}) == 0);
        check(query[0] == first && query[1] == first + 16384 && query[9] == 0xabcdef);
        check(memory("rVjRvHJ0X6c", {first, 0, pointer(query.data()), 71}) != 0);
        *reinterpret_cast<U*>(first) = 0x123456789abcdef0;
        check(*reinterpret_cast<U*>(second) == 0x123456789abcdef0);
        check(memory("cQke9UuBQOk", {first, 16384}) == 0);
        check(memory("cQke9UuBQOk", {second, 16384}) == 0);
        check(memory("MBuItvba6z8", {physical, 16384}) == 0);
        bool rejected = false;
        const std::array<U, 12> empty{};
        try { (void)SkyGpu::memory_call("pO96TwzOm5E#wrong#libkernel", empty.data()); }
        catch (const std::exception&) { rejected = true; }
        check(rejected);
        const auto media = [&](const char* nid, std::array<U, 12> args = {}) {
            return SkyGpu::call(std::string(nid) + "#libSceAjm#libSceAjm", args.data());
        };
        std::uint32_t context = 0, instance = 0;
        check(media("dl+4eHSzUu4", {0, pointer(&context)}) == 0 && context);
        check(media("Q3dyFuwGn64", {context, 1, 0}) == 0);
        check(media("Q3dyFuwGn64", {context, 1, 0}) == 0x80930009);
        check(media("AxoDrINp4J8", {context, 1, 1, pointer(&instance)}) == 0 && instance);
        check(media("RbLbuKv8zho", {context, instance}) == 0);
        check(media("Wi7DtlLV+KI", {context, 1}) == 0);
        check(media("MHur6qCsUus", {context}) == 0);
        std::cout << "GPU adapter scope, encoder and shared physical alias tests passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}

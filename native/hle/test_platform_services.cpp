// SPDX-License-Identifier: GPL-3.0-or-later
#include "kernel_clock.hpp"
#include "kernel_semaphore.hpp"
#include "user_service.hpp"
#include "local_players.hpp"
#include "local_np.hpp"
#include <array>
#include <future>
#include <iostream>
#include <stdexcept>
#include <string>

int main() {
    try {
        using U = std::uint64_t;
        const auto check = [](bool value) { if (!value) throw std::runtime_error("platform service contract failed"); };
        const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
        KernelClock clock;
        const std::array<U, 6> empty{};
        const auto frequency = clock.call("1j3S3n-tTW4#libkernel#libkernel", empty.data());
        check(frequency > 0 && frequency == clock.call("1j3S3n-tTW4#libkernel#libkernel", empty.data()));
        const auto first = clock.call("-2IRUCO--PM#libkernel#libkernel", empty.data());
        check(clock.call("-2IRUCO--PM#libkernel#libkernel", empty.data()) >= first);
        const std::array<U, 6> invalid_clock{0, 0};
        check(clock.call("QBi7HCK03hw#libkernel#libkernel", invalid_clock.data()) == 0x80020016);
        std::array<std::int64_t,2> wall{};
        std::array<std::int32_t,2> zone{};
        std::array<U,6> tod{pointer(wall.data()),pointer(zone.data())};
        check(clock.call("n88vx3C5nW8#libScePosix#libkernel",tod.data())==0);
        check(wall[0]>0 && wall[1]>=0 && wall[1]<1000000);
        check(clock.call("n88vx3C5nW8#libScePosix#libkernel",empty.data())==0);
        check(!KernelClock::supports("n88vx3C5nW8#wrong#libkernel"));
        UserService users;
        const auto user = [&](const char* nid, std::array<U, 6> args = {}) {
            return users.call(std::string(nid) + "#libSceUserService#libSceUserService", args.data());
        };
        std::int32_t id = -1;
        check(user("CdWp0oHWGr0", {pointer(&id)}) == 0x80960002);
        check(user("j3YMu1MVNNo") == 0);
        check(user("CdWp0oHWGr0", {pointer(&id)}) == 0 && id == 0x1000);
        std::array<std::int32_t, 2> event{};
        check(user("yH17Q6NWtVg", {pointer(event.data())}) == 0 && event[0] == 0 && event[1] == id);
        check(user("yH17Q6NWtVg", {pointer(event.data())}) == 0x80960007);
        std::array<char, 32> name{};
        check(user("1xxcMiGu2fo", {static_cast<U>(id), pointer(name.data()), 1}) == 0x8096000a);
        check(user("1xxcMiGu2fo", {static_cast<U>(id), pointer(name.data()), name.size()}) == 0 && name[0]);
        std::array<std::int32_t,4> logged{};
        LocalPlayers::second_connected=true;
        check(user("fPhymKNvK-A", {pointer(logged.data())})==0 && logged[0]==0x1000 && logged[1]==0x1001 && logged[2]==-1);
        check(user("yH17Q6NWtVg", {pointer(event.data())})==0 && event[0]==0 && event[1]==0x1001);
        check(user("1xxcMiGu2fo", {0x1001,pointer(name.data()),name.size()})==0 && std::string(name.data())=="Player 2");
        LocalPlayers::second_connected=false;
        check(user("yH17Q6NWtVg", {pointer(event.data())})==0 && event[0]==1 && event[1]==0x1001);
        check(user("fPhymKNvK-A", {pointer(logged.data())})==0 && logged[1]==-1);
        check(user("yH17Q6NWtVg", {pointer(event.data())})==0x80960007);
        LocalNp np;
        const auto state_call=[&](std::uint64_t user) {
            const std::array<U,6> args{user,pointer(&id)};
            return np.call("eQH7nWPcAgc#libSceNpManager#libSceNpManager",args.data());
        };
        check(state_call(0x1001)==0x80550003);
        LocalPlayers::second_connected=true;check(state_call(0x1001)==0 && id==0);
        LocalPlayers::second_connected=false;check(state_call(0x1002)==0x80550003);
        KernelSemaphore semaphores;
        const auto sema = [&](const char* nid, std::array<U, 6> args = {}) {
            return semaphores.call(std::string(nid) + "#libkernel#libkernel", args.data());
        };
        std::uint32_t handle = 0;
        check(sema("188x57JYp0g", {pointer(&handle), pointer("test"), 2, 0, 2}) == 0);
        check(sema("12wOHk8ywb0", {handle, 1}) == 0x80020010);
        std::uint32_t timeout = 0;
        check(sema("Zxa0VhQVTsk", {handle, 1, pointer(&timeout)}) == 0x8002003c);
        auto waiter = std::async(std::launch::async, [&] {
            std::uint32_t deadline = 1000000;
            return sema("Zxa0VhQVTsk", {handle, 2, pointer(&deadline)});
        });
        check(sema("4czppHBiriw", {handle, 2}) == 0);
        check(waiter.get() == 0);
        check(sema("4czppHBiriw", {handle, 3}) == 0x80020016);
        check(sema("R1Jvn8bSCW8", {handle}) == 0);
        check(sema("12wOHk8ywb0", {handle, 1}) == 0x80020003);
        U posix_handle = 0;
        const auto posix = [&](const char* nid, std::array<U, 6> args = {}) {
            return semaphores.call(std::string(nid) + "#libScePosix#libkernel", args.data());
        };
        check(!KernelSemaphore::supports("pDuPEf3m4fI#wrong#libkernel"));
        check(posix("pDuPEf3m4fI", {pointer(&posix_handle), 0, 0}) == 0 && posix_handle);
        check(posix("WBWzsRifCEA", {pointer(&posix_handle)}) == static_cast<U>(-1));
        auto posix_waiter = std::async(std::launch::async, [&] {
            return posix("YCV5dGGBcCo", {pointer(&posix_handle)});
        });
        check(posix("IKP8typ0QUk", {pointer(&posix_handle)}) == 0);
        check(posix_waiter.get() == 0);
        std::array<std::int64_t, 2> expired{0, 0};
        check(posix("w5IHyvahg-o", {pointer(&posix_handle), pointer(expired.data())}) == static_cast<U>(-1));
        expired[1] = 1000000000;
        check(posix("w5IHyvahg-o", {pointer(&posix_handle), pointer(expired.data())}) == static_cast<U>(-1));
        check(posix("IKP8typ0QUk", {pointer(&posix_handle)}) == 0);
        // An immediately available token succeeds even with an expired deadline.
        expired[1] = 0;
        check(posix("w5IHyvahg-o", {pointer(&posix_handle), pointer(expired.data())}) == 0);
        std::int32_t value = -1;
        check(posix("Bq+LRV-N6Hk", {pointer(&posix_handle), pointer(&value)}) == 0 && value == 0);
        check(posix("cDW233RAwWo", {pointer(&posix_handle)}) == 0 && !posix_handle);
        check(posix("YCV5dGGBcCo", {pointer(&posix_handle)}) == static_cast<U>(-1));
        std::cout << "clock, local user and semaphore tests passed\n";
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}

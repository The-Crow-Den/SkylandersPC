// SPDX-License-Identifier: GPL-3.0-or-later
#include "offline_network.hpp"
#include <array>
#include <future>
#include <stdexcept>
#include <string>
int main() {
    using U = std::uint64_t;
    OfflineNetwork net;
    auto call = [&](const char* name) { const std::array<U,6> a{}; return net.call(std::string(name)+"#libSceNet#libSceNet",a.data()); };
    auto check = [](bool value) { if (!value) throw std::runtime_error("offline network contract failed"); };
    check(!OfflineNetwork::supports("Q4qBuN-c0ZM#wrong#libSceNet"));
    check(call("Q4qBuN-c0ZM")==0x804101c8);
    check(call("Nlev7Lg8k3A")==0);
    check(call("Q4qBuN-c0ZM")==0x80410132);
    auto* error = reinterpret_cast<std::int32_t*>(call("HQOwnfMGipQ"));
    check(*error==50);
    auto other=std::async(std::launch::async,[&] {
        auto* local=reinterpret_cast<std::int32_t*>(call("HQOwnfMGipQ"));
        check(local!=error && *local==0);
        check(call("Q4qBuN-c0ZM")==0x80410132 && *local==50);
    });
    other.get();
    check(*error==50);
    check(call("cTGkc6-TBlI")==0);
    check(call("Q4qBuN-c0ZM")==0x804101c8);
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "local_trophies.hpp"
#include <iostream>
#include <stdexcept>
int main() {
  namespace fs = std::filesystem;
  using U = std::uint64_t;
  auto check = [](bool value) {
    if (!value)
      throw std::runtime_error("local trophy contract failed");
  };
  auto ptr = [](auto *value) { return reinterpret_cast<U>(value); };
  char temporary[] = "/tmp/sky-trophies-XXXXXX";
  const auto *directory = mkdtemp(temporary);
  if (!directory)
    return 2;
  const fs::path root(directory);
  try {
    fs::create_directories(root / "catalogues");
    fs::create_directories(root / "icons");
    setenv("SKY_TROPHY_STORE", root.c_str(), 1);
    setenv("SKY_TROPHY_CATALOGUES", (root / "catalogues").c_str(), 1);
    setenv("SKY_TROPHY_ICONS", (root / "icons").c_str(), 1);
    for (int user : {4096, 4097}) {
      std::ofstream file(root / "catalogues" / (std::to_string(user) + ".tsv"));
      file << "SKYTROPHIES1\tNPWR12345_00\tSynthetic "
              "test\n0\t1\t0\t0\t0\t0\tPlatinum\tAll\n1\t4\t0\t0\t0\t0\tFirst\t"
              "One\n2\t2\t0\t0\t0\t0\tSecond\tTwo\n";
    }
    auto call = [](LocalTrophies &backend, std::string_view nid,
                   std::array<U, 6> args = {}) {
      return backend.call(std::string(nid) + "#libSceNpTrophy#libSceNpTrophy",
                          args.data());
    };
    LocalTrophies trophies;
    int context = 0, handle = 0, platinum = -7;
    check(!LocalTrophies::supports("XbkjbobZlCY#wrong#libSceNpTrophy"));
    check(call(trophies, "XbkjbobZlCY", {ptr(&context), 4096}) == 0);
    check(call(trophies, "XbkjbobZlCY", {ptr(&context), 4096}) == 0x80551613);
    check(call(trophies, "q7U6tEAQf7c", {ptr(&handle)}) == 0);
    const U c = static_cast<U>(context), h = static_cast<U>(handle);
    check(call(trophies, "28xmRUFao68", {c, h, 1, ptr(&platinum)}) ==
          0x8055160f);
    check(call(trophies, "TJCAxto9SEU", {c, h}) == 0);
    check(call(trophies, "28xmRUFao68", {c, h, 0, ptr(&platinum)}) ==
          0x8055160d);
    check(call(trophies, "28xmRUFao68", {c, h, 127, ptr(&platinum)}) ==
          0x8055160a);
    check(call(trophies, "28xmRUFao68", {c, h, 1, ptr(&platinum)}) == 0 &&
          platinum == -1);
    check(call(trophies, "28xmRUFao68", {c, h, 1, ptr(&platinum)}) ==
          0x8055160c);
    std::array<std::uint32_t, 4> flags{};
    std::uint32_t count = 0;
    check(call(trophies, "LHuSmO3SLd8",
               {c, h, ptr(flags.data()), ptr(&count)}) == 0 &&
          count == 3 && flags[0] == 2);
    LocalTrophies restarted;
    int other_context = 0, other_handle = 0;
    check(call(restarted, "XbkjbobZlCY", {ptr(&other_context), 4096}) == 0);
    check(call(restarted, "q7U6tEAQf7c", {ptr(&other_handle)}) == 0);
    const U rc = static_cast<U>(other_context),
            rh = static_cast<U>(other_handle);
    check(call(restarted, "TJCAxto9SEU", {rc, rh}) == 0);
    check(call(restarted, "LHuSmO3SLd8",
               {rc, rh, ptr(flags.data()), ptr(&count)}) == 0 &&
          flags[0] == 2);
    check(call(restarted, "28xmRUFao68", {rc, rh, 2, ptr(&platinum)}) == 0 &&
          platinum == 0);
    check(call(restarted, "LHuSmO3SLd8",
               {rc, rh, ptr(flags.data()), ptr(&count)}) == 0 &&
          flags[0] == 7);
    LocalPlayers::second_connected = true;
    int second = 0;
    check(call(restarted, "XbkjbobZlCY", {ptr(&second), 4097}) == 0);
    check(call(restarted, "TJCAxto9SEU", {static_cast<U>(second), rh}) == 0);
    check(call(restarted, "LHuSmO3SLd8",
               {static_cast<U>(second), rh, ptr(flags.data()), ptr(&count)}) ==
              0 &&
          flags[0] == 0);
    std::ofstream(root / "users/4096/NPWR12345_00.xml")
        << "<trophyconf><trophy id=\"1\" unlockstate=\"true\" "
           "timestamp=\"1\"/></trophyconf>";
    LocalTrophies corrupt;
    check(call(corrupt, "XbkjbobZlCY", {ptr(&other_context), 4096}) ==
          0x80551622);
    unsetenv("SKY_TROPHY_CATALOGUES");
    LocalTrophies absent;
    check(call(absent, "XbkjbobZlCY", {ptr(&other_context), 4096}) ==
          0x80551622);
    fs::remove_all(root);
    std::cout << "local trophy persistence, validation and users passed\n";
    return 0;
  } catch (const std::exception &error) {
    fs::remove_all(root);
    std::cerr << error.what() << '\n';
    return 1;
  }
}

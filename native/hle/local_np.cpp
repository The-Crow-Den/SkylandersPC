// SPDX-License-Identifier: GPL-3.0-or-later
#include "local_np.hpp"
#include "local_players.hpp"
#include <array>
#include <cstring>
#include <stdexcept>
namespace {
constexpr std::array<std::string_view, 3> names{
    "A2CQ3kgSopQ#libSceNpManager#libSceNpManager",
    "eQH7nWPcAgc#libSceNpManager#libSceNpManager",
    "XbkjbobZlCY#libSceNpTrophy#libSceNpTrophy"};
struct Restriction {
    std::uint64_t size;
    std::int8_t age;
    unsigned char padding[3];
    std::int32_t count;
    const unsigned char* countries;
};
static_assert(sizeof(Restriction) == 24);
}
bool LocalNp::supports(std::string_view identity) noexcept {
    if(LocalTrophies::supports(identity))return true;
    for (auto name : names) if (identity == name) return true;
    return false;
}
std::uint64_t LocalNp::call(std::string_view identity, const std::uint64_t* a) {
    std::lock_guard lock(lock_);
    if(LocalTrophies::supports(identity))return trophies_.call(identity,a);
    if (identity == names[0]) {
        if (!a[0]) return 0x80550003;
        const auto* restriction = reinterpret_cast<const Restriction*>(a[0]);
        if (restriction->size != sizeof(Restriction)) return 0x80550011;
        if (restriction->age < 0 || restriction->count < 0 || restriction->count > 256 ||
            (restriction->count && !restriction->countries)) return 0x80550003;
        country_restrictions_.resize(static_cast<std::size_t>(restriction->count) * 8);
        if (!country_restrictions_.empty()) std::memcpy(country_restrictions_.data(), restriction->countries, country_restrictions_.size());
        age_ = restriction->age;
        return 0;
    }
    if (identity == names[1]) {
        if (!LocalPlayers::valid_user(a[0]) || !a[1]) return 0x80550003;
        *reinterpret_cast<std::int32_t*>(a[1]) = 0; // Signed out of PSN.
        return 0;
    }
    throw std::runtime_error("unsupported local NP import");
}

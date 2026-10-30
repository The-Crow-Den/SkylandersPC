// SPDX-License-Identifier: GPL-2.0-or-later
// renderer: code that runs when the enclosing scope ends.
//   SCOPE_EXIT { close(fd); };
//   auto guard = SCOPE_GUARD { undo(); };  guard.Cancel();
#pragma once

#include <utility>

namespace Common::Detail {

template <class F>
class ScopeGuard {
public:
    constexpr explicit ScopeGuard(F f) : func{std::move(f)} {}
    constexpr ScopeGuard(ScopeGuard&& other) : func{std::move(other.func)}, armed{other.armed} {
        other.armed = false;
    }
    ScopeGuard& operator=(ScopeGuard&&) = delete;
    constexpr ~ScopeGuard() {
        if (armed) {
            func();
        }
    }
    constexpr void Cancel() {
        armed = false;
    }

private:
    F func;
    bool armed = true;
};

struct ScopeGuardTag {};

template <typename F>
constexpr ScopeGuard<std::decay_t<F>> operator+(ScopeGuardTag, F&& f) {
    return ScopeGuard<std::decay_t<F>>(std::forward<F>(f));
}

} // namespace Common::Detail

#define SKY_RENDERER_CONCAT_IMPL(a, b) a##b
#define SKY_RENDERER_CONCAT(a, b) SKY_RENDERER_CONCAT_IMPL(a, b)

#define SCOPE_GUARD ::Common::Detail::ScopeGuardTag{} + [&]()
#define SCOPE_EXIT auto SKY_RENDERER_CONCAT(scope_exit_, __COUNTER__) = SCOPE_GUARD

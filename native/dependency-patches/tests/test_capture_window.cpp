// SPDX-License-Identifier: GPL-2.0-or-later
#include "render/capture_window.h"
#include <stdexcept>
int main() {
    using W = Vulkan::CaptureWindow;
    using A = W::Action;
    auto check=[](bool ok){if(!ok)throw std::runtime_error("capture-window contract");};
    W window;
    check(window.Advance(false,100,2)==A::None);
    check(window.Advance(true,100,2)==A::Begin);
    // Multiple display passes/draws in the same interval do not finish it.
    for(unsigned i=0;i<100;++i)check(window.Advance(false,100,2)==A::None);
    check(window.Advance(false,101,2)==A::None);
    check(window.Advance(false,102,2)==A::FinishFlips);
    check(window.Advance(false,103,2)==A::None);
    check(window.Advance(true,200,1)==A::Begin);
    check(window.Start()==200);
    check(window.Advance(false,201,1)==A::FinishFlips);
    check(window.Advance(true,300,4)==A::Begin);
    // A backwards counter must not underflow into an apparent completed window.
    check(window.Advance(false,299,4)==A::None);
    for(unsigned i=1;i<W::MaxPolls-1;++i)check(window.Advance(false,300,4)==A::None);
    check(window.Advance(false,300,4)==A::FinishBudget);
    check(window.Advance(false,304,4)==A::None);
    check(window.Advance(true,400,0)==A::None);
    check(window.Advance(true,400,5)==A::None);
}

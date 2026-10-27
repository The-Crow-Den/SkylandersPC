// SPDX-License-Identifier: GPL-3.0-or-later
#include "thread_context.hpp"
#include "guest_start.hpp"
#include <array>
#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>

namespace {
thread_local GuestThreadContext* current_context = nullptr;
// Guest-visible stacks and TLS stay below 2 GiB as before; no requirement for
// this is documented, so it is kept until a guest is verified without it.
// Host-only memory such as the signal stack passes low = false.
struct Memory {
    void* pointer;
    std::size_t size;
    Memory(std::size_t length, int protection, bool low = true) : size(length) {
        pointer = mmap(nullptr, length, protection, MAP_PRIVATE | MAP_ANONYMOUS | (low ? MAP_32BIT : 0), -1, 0);
        if (pointer == MAP_FAILED) throw std::runtime_error("cannot allocate guest thread memory");
    }
    ~Memory() { munmap(pointer, size); }
};
std::size_t page_size() {
    const auto size = sysconf(_SC_PAGESIZE);
    if (size <= 0) throw std::runtime_error("cannot query thread page size");
    return static_cast<std::size_t>(size);
}
std::unique_ptr<Memory> guarded_stack(std::size_t usable, std::size_t page) {
    auto stack = std::make_unique<Memory>(usable + 2 * page, PROT_READ | PROT_WRITE);
    if (mprotect(stack->pointer, page, PROT_NONE) ||
        mprotect(static_cast<unsigned char*>(stack->pointer) + stack->size - page, page, PROT_NONE))
        throw std::runtime_error("cannot guard guest callback stack");
    return stack;
}
}
struct GuestThreadContext::Impl {
    std::size_t page = page_size();
    std::size_t guard;
    Memory stack, tls, alternate;
    unsigned char* tcb;
    std::array<std::uint64_t, 18> dtv{};
    std::array<unsigned char*, 17> tls_blocks{};
    std::array<std::uint64_t, 17> tls_sizes{};
    std::vector<std::unique_ptr<Memory>> module_tls;
    // Outermost callbacks reuse one stack; nested callbacks get their own.
    std::unique_ptr<Memory> callback_stack;
    unsigned callback_depth = 0;
    Impl(const SkyBootPlan& boot, std::size_t stack_size, std::size_t guard_size)
        : guard(std::max<std::size_t>(page, ((guard_size + page - 1) / page) * page)),
          stack(((stack_size + page - 1) / page) * page + 2 * guard, PROT_READ | PROT_WRITE),
          tls(2 * 1024 * 1024 + page, PROT_READ | PROT_WRITE),
          alternate(128 * 1024, PROT_READ | PROT_WRITE, false),
          tcb(static_cast<unsigned char*>(tls.pointer) + 2 * 1024 * 1024) {
        if (mprotect(stack.pointer, guard, PROT_NONE) ||
            mprotect(static_cast<unsigned char*>(stack.pointer) + stack.size - guard, guard, PROT_NONE))
            throw std::runtime_error("cannot guard guest thread stack");
        auto** fields = reinterpret_cast<void**>(tcb);
        fields[0] = tcb; fields[1] = dtv.data(); fields[2] = tcb + 128;
        *reinterpret_cast<void**>(tcb + 128) = tcb;
        dtv[0] = 1; dtv[1] = boot.modules.size();
        for (const auto& module : boot.modules) {
            if (!module.tls_memsz) continue;
            unsigned char* block;
            if (module.id == 1) {
                const auto size = (module.tls_memsz + module.tls_align - 1) & ~(module.tls_align - 1);
                block = tcb - size;
            } else {
                auto memory = std::make_unique<Memory>(module.tls_memsz, PROT_READ | PROT_WRITE);
                block = static_cast<unsigned char*>(memory->pointer);
                module_tls.push_back(std::move(memory));
            }
            std::memcpy(block, reinterpret_cast<const void*>(module.tls_address), module.tls_filesz);
            tls_blocks[module.id] = block; tls_sizes[module.id] = module.tls_memsz;
            dtv[module.id + 1] = reinterpret_cast<std::uintptr_t>(block);
        }
    }
};
GuestThreadContext::GuestThreadContext(const SkyBootPlan& boot, std::size_t stack_size, std::size_t guard_size)
    : impl_(std::make_unique<Impl>(boot, stack_size, guard_size)) {}
GuestThreadContext::~GuestThreadContext() = default;
GuestThreadContext* GuestThreadContext::current() noexcept { return current_context; }
std::uint64_t GuestThreadContext::handle() const { return reinterpret_cast<std::uintptr_t>(impl_->tcb + 128); }
std::int32_t* GuestThreadContext::error_pointer() const { return reinterpret_cast<std::int32_t*>(impl_->tcb + 192); }
bool GuestThreadContext::is_stack_guard(std::uint64_t address) const noexcept {
    const auto start = reinterpret_cast<std::uintptr_t>(impl_->stack.pointer);
    return address >= start && address - start < impl_->stack.size &&
        (address - start < impl_->guard || address - start >= impl_->stack.size - impl_->guard);
}
std::uint64_t GuestThreadContext::signal_mask(int operation, const void* set, void* old_set) {
    auto* mask = reinterpret_cast<std::uint32_t*>(impl_->tcb + 256);
    std::array<std::uint32_t, 4> replacement{};
    if (set) {
        if (operation < 1 || operation > 3) { *error_pointer() = 22; return ~std::uint64_t{0}; }
        std::memcpy(replacement.data(), set, sizeof(replacement));
    }
    if (old_set) std::memcpy(old_set, mask, sizeof(replacement));
    if (set) {
        for (std::size_t i = 0; i < 4; ++i) {
            if (operation == 1) mask[i] |= replacement[i];
            else if (operation == 2) mask[i] &= ~replacement[i];
            else mask[i] = replacement[i];
        }
        mask[0] &= ~((1u << 8) | (1u << 16)); // SIGKILL and SIGSTOP cannot be masked.
    }
    return 0;
}
std::uint64_t GuestThreadContext::tls_address(std::uint64_t module, std::uint64_t offset) const {
    if (!module || module > 16 || !impl_->tls_blocks[module] || offset >= impl_->tls_sizes[module])
        throw std::runtime_error("unsupported TLS module/offset");
    return reinterpret_cast<std::uintptr_t>(impl_->tls_blocks[module] + offset);
}
std::uint64_t GuestThreadContext::run(std::uint64_t entry, const void* argument) {
    auto* prior_context = current_context;
    current_context = this;
    stack_t alternate{}, prior_stack{};
    alternate.ss_sp = impl_->alternate.pointer; alternate.ss_size = impl_->alternate.size;
    if (sigaltstack(&alternate, &prior_stack)) {
        current_context = prior_context;
        throw std::runtime_error("cannot install thread signal stack");
    }
    SkyGuestStartContext context{reinterpret_cast<void*>(entry),
        static_cast<unsigned char*>(impl_->stack.pointer) + impl_->stack.size - impl_->guard - 64,
        impl_->tcb, argument, nullptr};
    std::uint64_t result = 0;
    const auto status = sky_guest_start(&context, &result);
    current_context = prior_context;
    if (sigaltstack(&prior_stack, nullptr)) throw std::runtime_error("cannot restore thread signal stack");
    if (status) throw std::runtime_error("guest thread entry bridge failed");
    return result;
}
std::uint64_t GuestThreadContext::callback(std::uint64_t entry, const void* argument) {
    // A service callback must not reuse the suspended caller's live guest stack.
    // Reuse this thread's TCB/TLS and enter on a separate guarded stack.
    if (current_context != this || !entry) throw std::runtime_error("invalid guest callback context");
    constexpr std::size_t usable = 1024 * 1024;
    std::unique_ptr<Memory> nested;
    Memory* stack;
    if (impl_->callback_depth == 0) {
        if (!impl_->callback_stack) impl_->callback_stack = guarded_stack(usable, impl_->page);
        stack = impl_->callback_stack.get();
    } else {
        nested = guarded_stack(usable, impl_->page);
        stack = nested.get();
    }
    SkyGuestStartContext context{reinterpret_cast<void*>(entry),
        static_cast<unsigned char*>(stack->pointer) + stack->size - impl_->page - 64,
        impl_->tcb, argument, nullptr};
    std::uint64_t result = 0;
    ++impl_->callback_depth;
    const auto status = sky_guest_start(&context, &result);
    --impl_->callback_depth;
    if (status) throw std::runtime_error("guest callback entry failed");
    return result;
}

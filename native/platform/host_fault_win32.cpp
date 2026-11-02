// SPDX-License-Identifier: GPL-3.0-or-later
#include "host_fault.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <atomic>

namespace SkyHost {
namespace {
std::atomic<FaultHandler> handler{nullptr};
static_assert(decltype(handler)::is_always_lock_free);
void* registration = nullptr;
LONG CALLBACK dispatch(EXCEPTION_POINTERS* info) noexcept {
    const auto* record = info->ExceptionRecord;
    if (record->ExceptionFlags & EXCEPTION_NONCONTINUABLE) return EXCEPTION_CONTINUE_SEARCH;
    Fault fault{};
    fault.native_code = record->ExceptionCode;
    fault.address = reinterpret_cast<std::uintptr_t>(record->ExceptionAddress);
    switch (record->ExceptionCode) {
    case EXCEPTION_ACCESS_VIOLATION:
        if (record->NumberParameters < 2) return EXCEPTION_CONTINUE_SEARCH;
        fault.kind = FaultKind::access;
        fault.native_error = record->ExceptionInformation[0];
        fault.address = record->ExceptionInformation[1];
        switch (record->ExceptionInformation[0]) {
        case 0: fault.access = FaultAccess::read; break;
        case 1: fault.access = FaultAccess::write; break;
        case 8: fault.access = FaultAccess::execute; break;
        default: return EXCEPTION_CONTINUE_SEARCH;
        }
        break;
    case EXCEPTION_ILLEGAL_INSTRUCTION: fault.kind = FaultKind::illegal_instruction; break;
    case EXCEPTION_INT_DIVIDE_BY_ZERO:
    case EXCEPTION_INT_OVERFLOW:
    case EXCEPTION_FLT_DIVIDE_BY_ZERO:
    case EXCEPTION_FLT_INVALID_OPERATION:
    case EXCEPTION_FLT_OVERFLOW:
    case EXCEPTION_FLT_UNDERFLOW:
    case EXCEPTION_FLT_INEXACT_RESULT:
    case EXCEPTION_FLT_DENORMAL_OPERAND:
        fault.kind = FaultKind::arithmetic; break;
    case EXCEPTION_BREAKPOINT: fault.kind = FaultKind::breakpoint; break;
    default: return EXCEPTION_CONTINUE_SEARCH;
    }
    auto* c = info->ContextRecord;
    fault.cpu.gpr = {c->Rax,c->Rcx,c->Rdx,c->Rbx,c->Rsp,c->Rbp,c->Rsi,c->Rdi,
                     c->R8,c->R9,c->R10,c->R11,c->R12,c->R13,c->R14,c->R15};
    fault.cpu.pc = c->Rip;
    fault.cpu.flags = c->EFlags;
    const auto callback = handler.load(std::memory_order_acquire);
    if (!callback || !callback(fault)) return EXCEPTION_CONTINUE_SEARCH;
    c->Rax=fault.cpu.gpr[0]; c->Rcx=fault.cpu.gpr[1]; c->Rdx=fault.cpu.gpr[2];
    c->Rbx=fault.cpu.gpr[3]; c->Rsp=fault.cpu.gpr[4]; c->Rbp=fault.cpu.gpr[5];
    c->Rsi=fault.cpu.gpr[6]; c->Rdi=fault.cpu.gpr[7]; c->R8=fault.cpu.gpr[8];
    c->R9=fault.cpu.gpr[9]; c->R10=fault.cpu.gpr[10]; c->R11=fault.cpu.gpr[11];
    c->R12=fault.cpu.gpr[12]; c->R13=fault.cpu.gpr[13]; c->R14=fault.cpu.gpr[14];
    c->R15=fault.cpu.gpr[15]; c->Rip=fault.cpu.pc;
    c->EFlags=static_cast<DWORD>(fault.cpu.flags);
    return EXCEPTION_CONTINUE_EXECUTION;
}
}
bool install_fault_handler(FaultHandler callback) noexcept {
    if (!callback || registration) return false;
    handler.store(callback, std::memory_order_release);
    registration = AddVectoredExceptionHandler(1, &dispatch);
    if (!registration) handler.store(nullptr, std::memory_order_release);
    return registration != nullptr;
}
bool remove_fault_handler() noexcept {
    if (!registration) return false;
    if (!RemoveVectoredExceptionHandler(registration)) return false;
    registration = nullptr;
    handler.store(nullptr, std::memory_order_release);
    return true;
}
}

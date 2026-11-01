// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_code.hpp"
#include <Zydis/Zydis.h>
#include <algorithm>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <tuple>

namespace GuestCode {
namespace {
[[noreturn]] void fail(std::uint64_t address, const char* reason) {
    std::ostringstream message;
    message << "guest code at 0x" << std::hex << address << ": " << reason;
    throw std::runtime_error(message.str());
}
}
Analysis discover(std::span<const std::uint8_t> executable,
                  std::span<const GuestTls::CodeRange> executable_ranges,
                  std::span<const std::uint64_t> roots, const std::string& expected_sha256,
                  std::size_t max_instructions, std::span<const NoReturnTarget> no_return) {
    GuestTls::verify_executable(executable, expected_sha256);
    if (roots.empty() || executable_ranges.empty() || !max_instructions || max_instructions > 8'000'000)
        throw std::runtime_error("guest code discovery requires roots, ranges and a bounded instruction limit");
    std::vector<GuestTls::CodeRange> ranges(executable_ranges.begin(), executable_ranges.end());
    std::sort(ranges.begin(), ranges.end(), [](const auto& a, const auto& b) { return a.address < b.address; });
    std::uint64_t end = 0;
    for (const auto& range : ranges) {
        if (!range.size || range.file_offset > executable.size() || range.size > executable.size() - range.file_offset ||
            range.address > std::numeric_limits<std::uint64_t>::max() - range.size || range.address < end)
            throw std::runtime_error("guest code discovery has invalid/overlapping executable ranges");
        end = range.address + range.size;
    }
    const auto locate = [&](std::uint64_t pc) -> const GuestTls::CodeRange* {
        auto at = std::upper_bound(ranges.begin(), ranges.end(), pc,
                                  [](auto value, const auto& range) { return value < range.address; });
        if (at == ranges.begin()) return nullptr;
        --at;
        return pc - at->address < at->size ? &*at : nullptr;
    };
    std::map<std::uint64_t,bool> terminating;
    for (const auto& target : no_return) {
        const auto* range = locate(target.address);
        if (!range || target.expected_bytes.empty() || target.expected_bytes.size() > range->size - (target.address - range->address))
            fail(target.address, "invalid nonreturning target annotation");
        const auto source = range->file_offset + target.address - range->address;
        if (!std::equal(target.expected_bytes.begin(), target.expected_bytes.end(), executable.begin() + static_cast<std::ptrdiff_t>(source)))
            fail(target.address, "nonreturning target bytes mismatch");
        if (!terminating.emplace(target.address,true).second) fail(target.address, "duplicate nonreturning target");
    }
    std::vector<std::uint64_t> pending(roots.begin(), roots.end());
    std::sort(pending.begin(), pending.end(), std::greater<>());
    pending.erase(std::unique(pending.begin(), pending.end()), pending.end());
    for (auto pc : pending) if (!locate(pc)) fail(pc, "root outside executable bytes");
    ZydisDecoder decoder{};
    if (!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, ZYDIS_MACHINE_MODE_LONG_64, ZYDIS_STACK_WIDTH_64)))
        throw std::runtime_error("cannot initialize guest control-flow decoder");
    std::map<std::uint64_t, GuestTls::CodeRange> decoded;
    Analysis result;
    while (!pending.empty()) {
        auto pc = pending.back(); pending.pop_back();
        auto predecessor = pc;
        for (;;) {
            auto next = decoded.lower_bound(pc);
            if (next != decoded.end() && next->first == pc) break;
            if (next != decoded.begin()) {
                const auto& previous = std::prev(next)->second;
                if (pc - previous.address < previous.size) fail(pc, "control flow enters an instruction interior");
            }
            if (decoded.size() >= max_instructions) fail(pc, "instruction limit exceeded");
            const auto* range = locate(pc);
            if (!range) fail(pc, "internal discovery work item is unmapped");
            const auto offset = pc - range->address;
            const auto source = range->file_offset + offset;
            ZydisDecodedInstruction instruction{};
            ZydisDecodedOperand operands[ZYDIS_MAX_OPERAND_COUNT]{};
            if (!ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, executable.data() + source,
                                                    static_cast<std::size_t>(range->size - offset), &instruction, operands)))
                {
                    std::ostringstream context;
                    context << "cannot decode reachable instruction (fallthrough from 0x" << std::hex << predecessor << ")";
                    fail(pc, context.str().c_str());
                }
            const auto fallthrough = pc + instruction.length; // Contained in the validated range.
            if (next != decoded.end() && next->first < fallthrough) fail(pc, "decoded instruction overlaps prior entry");
            decoded.emplace(pc, GuestTls::CodeRange{source, pc, instruction.length});
            const auto category = instruction.meta.category;
            if (category == ZYDIS_CATEGORY_RET) break;
            if (category == ZYDIS_CATEGORY_INTERRUPT || category == ZYDIS_CATEGORY_SYSCALL ||
                category == ZYDIS_CATEGORY_SYSRET || instruction.mnemonic == ZYDIS_MNEMONIC_UD0 ||
                instruction.mnemonic == ZYDIS_MNEMONIC_UD1 || instruction.mnemonic == ZYDIS_MNEMONIC_UD2 ||
                instruction.mnemonic == ZYDIS_MNEMONIC_HLT) {
                result.unresolved.push_back({pc, ExitKind::Trap, 0}); break;
            }
            const bool call = category == ZYDIS_CATEGORY_CALL;
            const bool conditional = category == ZYDIS_CATEGORY_COND_BR;
            const bool branch = conditional || category == ZYDIS_CATEGORY_UNCOND_BR;
            // Transaction abort is another control-flow edge, not ordinary fallthrough.
            if (instruction.mnemonic == ZYDIS_MNEMONIC_XBEGIN) fail(pc, "transactional control flow is unsupported");
            bool returns = true;
            if (call || branch) {
                if (instruction.operand_count_visible < 1) fail(pc, "branch has no visible target");
                const auto& target_operand = operands[0];
                if (target_operand.type == ZYDIS_OPERAND_TYPE_IMMEDIATE && target_operand.imm.is_relative) {
                    ZyanU64 target = 0;
                    if (!ZYAN_SUCCESS(ZydisCalcAbsoluteAddress(&instruction, &target_operand, pc, &target)))
                        fail(pc, "cannot resolve relative control flow");
                    if (call && terminating.contains(target)) returns = false;
                    if (locate(target)) pending.push_back(target);
                    else result.unresolved.push_back({pc, call ? ExitKind::ExternalCall : ExitKind::ExternalBranch, target});
                } else if (!conditional && (target_operand.type == ZYDIS_OPERAND_TYPE_REGISTER ||
                                            target_operand.type == ZYDIS_OPERAND_TYPE_MEMORY)) {
                    result.unresolved.push_back({pc, call ? ExitKind::IndirectCall : ExitKind::IndirectJump, 0});
                } else fail(pc, "unsupported control-transfer form");
                if ((branch && !conditional) || !returns) break;
            }
            if (!locate(fallthrough)) {
                result.unresolved.push_back({pc, ExitKind::ExternalBranch, fallthrough}); break;
            }
            predecessor = pc;
            pc = fallthrough;
        }
    }
    result.instructions.reserve(decoded.size());
    for (const auto& [address, range] : decoded) { (void)address; result.instructions.push_back(range); }
    std::sort(result.unresolved.begin(), result.unresolved.end(), [](const auto& a, const auto& b) {
        return std::tie(a.address,a.kind,a.target) < std::tie(b.address,b.kind,b.target);
    });
    return result;
}
}

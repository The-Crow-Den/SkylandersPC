// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_constants.hpp"
#include <Zydis/Zydis.h>
#include <array>

namespace GuestCode::Detail {
std::optional<std::uint64_t>
known_rip_base(std::span<const std::uint8_t> executable,
               const std::map<std::uint64_t, GuestTls::CodeRange> &instructions,
               const std::multimap<std::uint64_t, std::uint64_t> &branch_predecessors,
               const std::set<std::uint64_t> &entries, const std::set<std::uint64_t> &terminating_calls,
               std::uint64_t read_address, unsigned gpr) {
    if (gpr >= 16 || gpr == 4 || !instructions.contains(read_address))
        return {};
    const auto wanted = static_cast<ZydisRegister>(ZYDIS_REGISTER_RAX + gpr);
    const bool callee_saved = gpr == 3 || gpr == 5 || gpr >= 12; // Guest SysV ABI on both hosts.
    ZydisDecoder decoder{};
    if (!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, ZYDIS_MACHINE_MODE_LONG_64, ZYDIS_STACK_WIDTH_64)))
        return {};
    const auto decode = [&](std::uint64_t pc, ZydisDecodedInstruction &i, auto &operands) {
        const auto at = instructions.find(pc);
        if (at == instructions.end() || at->second.file_offset > executable.size() ||
            at->second.size > executable.size() - at->second.file_offset)
            return false;
        return ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, executable.data() + at->second.file_offset,
                                                   static_cast<std::size_t>(at->second.size), &i,
                                                   operands.data())) &&
               i.length == at->second.size;
    };
    std::vector<std::uint64_t> pending{read_address};
    std::set<std::uint64_t> visited;
    std::optional<std::uint64_t> constant;
    const auto consume = [&](std::uint64_t source) {
        ZydisDecodedInstruction i{};
        std::array<ZydisDecodedOperand, ZYDIS_MAX_OPERAND_COUNT> operands{};
        if (!decode(source, i, operands))
            return false;
        bool writes = false;
        for (unsigned n = 0; n < i.operand_count; ++n) {
            const auto &o = operands[n];
            if (o.type == ZYDIS_OPERAND_TYPE_REGISTER &&
                ZydisRegisterGetLargestEnclosing(ZYDIS_MACHINE_MODE_LONG_64, o.reg.value) == wanted &&
                (o.actions & ZYDIS_OPERAND_ACTION_MASK_WRITE))
                writes = true;
        }
        if (writes) {
            if (i.mnemonic != ZYDIS_MNEMONIC_LEA || i.operand_count_visible != 2 ||
                operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER || operands[0].reg.value != wanted ||
                operands[0].size != 64 || operands[1].type != ZYDIS_OPERAND_TYPE_MEMORY ||
                operands[1].mem.base != ZYDIS_REGISTER_RIP || operands[1].mem.index != ZYDIS_REGISTER_NONE ||
                i.address_width != 64)
                return false;
            ZyanU64 value = 0;
            if (!ZYAN_SUCCESS(ZydisCalcAbsoluteAddress(&i, &operands[1], source, &value)))
                return false;
            if (constant && *constant != value)
                return false;
            constant = value;
        } else {
            if (i.meta.category == ZYDIS_CATEGORY_CALL && !callee_saved)
                return false;
            pending.push_back(source);
        }
        return true;
    };
    while (!pending.empty()) {
        const auto pc = pending.back();
        pending.pop_back();
        if (!visited.insert(pc).second)
            continue;
        if (visited.size() > 65536 || entries.contains(pc))
            return {};
        bool predecessor = false;
        auto at = instructions.lower_bound(pc);
        if (at != instructions.begin()) {
            --at;
            if (at->second.address + at->second.size == pc && !terminating_calls.contains(at->first)) {
                ZydisDecodedInstruction i{};
                std::array<ZydisDecodedOperand, ZYDIS_MAX_OPERAND_COUNT> operands{};
                if (!decode(at->first, i, operands))
                    return {};
                const auto category = i.meta.category;
                const bool terminal =
                    category == ZYDIS_CATEGORY_RET || category == ZYDIS_CATEGORY_UNCOND_BR ||
                    category == ZYDIS_CATEGORY_INTERRUPT || category == ZYDIS_CATEGORY_SYSCALL ||
                    category == ZYDIS_CATEGORY_SYSRET || i.mnemonic == ZYDIS_MNEMONIC_UD0 ||
                    i.mnemonic == ZYDIS_MNEMONIC_UD1 || i.mnemonic == ZYDIS_MNEMONIC_UD2 ||
                    i.mnemonic == ZYDIS_MNEMONIC_HLT;
                if (!terminal) {
                    predecessor = true;
                    if (!consume(at->first))
                        return {};
                }
            }
        }
        const auto [first, last] = branch_predecessors.equal_range(pc);
        for (auto edge = first; edge != last; ++edge) {
            predecessor = true;
            if (!consume(edge->second))
                return {};
        }
        if (!predecessor)
            return {};
    }
    return constant;
}
} // namespace GuestCode::Detail

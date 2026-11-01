// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_bounds.hpp"
#include <Zydis/Zydis.h>
#include <algorithm>
#include <array>
#include <tuple>

namespace GuestCode::Detail {
namespace {
struct Instruction {
    ZydisDecodedInstruction i{};
    std::array<ZydisDecodedOperand, ZYDIS_MAX_OPERAND_COUNT> operands{};
};
unsigned number(ZydisRegister r) {
    r = ZydisRegisterGetLargestEnclosing(ZYDIS_MACHINE_MODE_LONG_64, r);
    return r >= ZYDIS_REGISTER_RAX && r <= ZYDIS_REGISTER_R15 ? static_cast<unsigned>(r - ZYDIS_REGISTER_RAX)
                                                              : 16;
}
bool writes(const Instruction &ins, unsigned r) {
    for (unsigned i = 0; i < ins.i.operand_count; ++i) {
        const auto &o = ins.operands[i];
        if (o.type == ZYDIS_OPERAND_TYPE_REGISTER && number(o.reg.value) == r &&
            (o.actions & ZYDIS_OPERAND_ACTION_MASK_WRITE))
            return true;
    }
    return false;
}
bool clobbering_call(const Instruction &ins, unsigned r) {
    return ins.i.meta.category == ZYDIS_CATEGORY_CALL && !(r == 3 || r == 5 || r >= 12);
}
struct Graph {
    std::span<const std::uint8_t> bytes;
    const std::map<std::uint64_t, GuestTls::CodeRange> &instructions;
    const std::multimap<std::uint64_t, std::uint64_t> &edges;
    const std::set<std::uint64_t> &entries;
    const std::set<std::uint64_t> &terminating;
    ZydisDecoder decoder{};
    // Shared by nested upper-bit checks as well as the main walk.
    mutable std::size_t remaining_decodes = 262144;
    bool decode(std::uint64_t pc, Instruction &out) const {
        if (!remaining_decodes)
            return false;
        --remaining_decodes;
        const auto at = instructions.find(pc);
        if (at == instructions.end() || at->second.file_offset > bytes.size() ||
            at->second.size > bytes.size() - at->second.file_offset)
            return false;
        return ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, bytes.data() + at->second.file_offset,
                                                   static_cast<std::size_t>(at->second.size), &out.i,
                                                   out.operands.data())) &&
               out.i.length == at->second.size;
    }
    std::vector<std::uint64_t> predecessors(std::uint64_t pc) const {
        std::vector<std::uint64_t> result;
        auto at = instructions.lower_bound(pc);
        if (at != instructions.begin()) {
            --at;
            if (at->first + at->second.size == pc && !terminating.contains(at->first)) {
                Instruction ins;
                if (!decode(at->first, ins))
                    return {};
                const auto category = ins.i.meta.category;
                if (category != ZYDIS_CATEGORY_RET && category != ZYDIS_CATEGORY_UNCOND_BR &&
                    category != ZYDIS_CATEGORY_INTERRUPT && category != ZYDIS_CATEGORY_SYSCALL &&
                    category != ZYDIS_CATEGORY_SYSRET && ins.i.mnemonic != ZYDIS_MNEMONIC_UD0 &&
                    ins.i.mnemonic != ZYDIS_MNEMONIC_UD1 && ins.i.mnemonic != ZYDIS_MNEMONIC_UD2 &&
                    ins.i.mnemonic != ZYDIS_MNEMONIC_HLT)
                    result.push_back(at->first);
            }
        }
        const auto [first, last] = edges.equal_range(pc);
        for (auto edge = first; edge != last; ++edge)
            result.push_back(edge->second);
        std::sort(result.begin(), result.end());
        result.erase(std::unique(result.begin(), result.end()), result.end());
        return result;
    }
    bool upper_zero(std::uint64_t pc, unsigned r) const {
        std::vector<std::uint64_t> pending{pc};
        std::set<std::uint64_t> visited;
        bool definition = false;
        while (!pending.empty()) {
            const auto read = pending.back();
            pending.pop_back();
            if (!visited.insert(read).second)
                continue;
            if (visited.size() > 65536 || entries.contains(read))
                return false;
            const auto from = predecessors(read);
            if (from.empty())
                return false;
            for (auto source : from) {
                Instruction ins;
                if (!decode(source, ins) || clobbering_call(ins, r))
                    return false;
                if (!writes(ins, r)) {
                    pending.push_back(source);
                    continue;
                }
                const auto &o = ins.operands[0];
                if (o.type != ZYDIS_OPERAND_TYPE_REGISTER || number(o.reg.value) != r || o.size != 32 ||
                    !(o.actions & ZYDIS_OPERAND_ACTION_WRITE) || (o.actions & ZYDIS_OPERAND_ACTION_CONDWRITE))
                    return false;
                switch (ins.i.mnemonic) {
                case ZYDIS_MNEMONIC_MOV:
                case ZYDIS_MNEMONIC_MOVZX:
                case ZYDIS_MNEMONIC_MOVSX:
                case ZYDIS_MNEMONIC_LEA:
                case ZYDIS_MNEMONIC_ADD:
                case ZYDIS_MNEMONIC_SUB:
                case ZYDIS_MNEMONIC_AND:
                case ZYDIS_MNEMONIC_OR:
                case ZYDIS_MNEMONIC_XOR:
                case ZYDIS_MNEMONIC_INC:
                case ZYDIS_MNEMONIC_DEC:
                    definition = true;
                    break;
                default:
                    return false;
                }
            }
        }
        return definition;
    }
    bool same_masked_value(std::uint64_t pc, unsigned compared, unsigned compare_width, unsigned wanted,
                           std::uint64_t wanted_mask) const {
        auto mask = compare_width == 32 ? std::uint64_t{0xffffffff} : ~std::uint64_t{0};
        // A full-width query may rely on a separately proved zero high half.
        if ((wanted_mask >> 32) && upper_zero(pc, wanted))
            wanted_mask &= 0xffffffffu;
        for (unsigned step = 0; step < 64; ++step) {
            if (compared == wanted && !(wanted_mask & ~mask))
                return true;
            if (entries.contains(pc))
                return false;
            const auto from = predecessors(pc);
            if (from.size() != 1)
                return false;
            Instruction ins;
            if (!decode(from[0], ins) || clobbering_call(ins, wanted) || clobbering_call(ins, compared) ||
                writes(ins, wanted))
                return false;
            if (writes(ins, compared)) {
                if (ins.i.operand_count_visible != 2)
                    return false;
                const auto &to = ins.operands[0];
                const auto &value = ins.operands[1];
                if (to.type != ZYDIS_OPERAND_TYPE_REGISTER || number(to.reg.value) != compared ||
                    (to.size != 32 && to.size != 64) || !(to.actions & ZYDIS_OPERAND_ACTION_WRITE) ||
                    (to.actions & ZYDIS_OPERAND_ACTION_CONDWRITE))
                    return false;
                if (to.size == 32)
                    mask &= 0xffffffffu;
                if (ins.i.mnemonic == ZYDIS_MNEMONIC_AND && value.type == ZYDIS_OPERAND_TYPE_IMMEDIATE)
                    mask &= value.imm.value.u;
                else if (ins.i.mnemonic == ZYDIS_MNEMONIC_MOV && value.type == ZYDIS_OPERAND_TYPE_REGISTER &&
                         value.size == to.size && number(value.reg.value) < 16 &&
                         number(value.reg.value) != 4)
                    compared = number(value.reg.value);
                else
                    return false;
            }
            pc = from[0];
        }
        return false;
    }
    std::optional<std::uint64_t> guard(std::uint64_t source, std::uint64_t target, unsigned r,
                                       std::uint64_t mask, const Instruction &ins) const {
        const bool bounded_taken =
            ins.i.mnemonic == ZYDIS_MNEMONIC_JB || ins.i.mnemonic == ZYDIS_MNEMONIC_JBE;
        if (!bounded_taken && ins.i.mnemonic != ZYDIS_MNEMONIC_JNBE && ins.i.mnemonic != ZYDIS_MNEMONIC_JNB)
            return {};
        if (ins.i.operand_count_visible != 1 || ins.operands[0].type != ZYDIS_OPERAND_TYPE_IMMEDIATE ||
            !ins.operands[0].imm.is_relative)
            return {};
        ZyanU64 taken = 0;
        const auto fallthrough = source + ins.i.length;
        if (!ZYAN_SUCCESS(ZydisCalcAbsoluteAddress(&ins.i, &ins.operands[0], source, &taken)) ||
            taken == fallthrough || target != (bounded_taken ? taken : fallthrough))
            return {};
        auto at = instructions.find(source);
        if (at == instructions.begin())
            return {};
        --at;
        if (at->first + at->second.size != source)
            return {};
        const auto guard_predecessors = predecessors(source);
        if (entries.contains(source) || guard_predecessors.size() != 1 || guard_predecessors[0] != at->first)
            return {};
        Instruction cmp;
        if (!decode(at->first, cmp) || cmp.i.mnemonic != ZYDIS_MNEMONIC_CMP ||
            cmp.i.operand_count_visible != 2)
            return {};
        const auto &reg = cmp.operands[0];
        const auto &immediate = cmp.operands[1];
        if (reg.type != ZYDIS_OPERAND_TYPE_REGISTER || number(reg.reg.value) >= 16 ||
            (reg.size != 32 && reg.size != 64) || immediate.type != ZYDIS_OPERAND_TYPE_IMMEDIATE ||
            (immediate.imm.is_signed && immediate.imm.value.s < 0) || immediate.imm.value.u > 65535)
            return {};
        if (!same_masked_value(at->first, number(reg.reg.value), reg.size, r, mask))
            return {};
        const bool inclusive = ins.i.mnemonic == ZYDIS_MNEMONIC_JNBE || ins.i.mnemonic == ZYDIS_MNEMONIC_JBE;
        const auto count = immediate.imm.value.u + (inclusive ? 1u : 0u);
        return count ? std::optional<std::uint64_t>{count} : std::nullopt;
    }
};
} // namespace
std::optional<std::uint64_t>
known_index_bound(std::span<const std::uint8_t> executable,
                  const std::map<std::uint64_t, GuestTls::CodeRange> &instructions,
                  const std::multimap<std::uint64_t, std::uint64_t> &branch_predecessors,
                  const std::set<std::uint64_t> &entries, const std::set<std::uint64_t> &terminating_calls,
                  std::uint64_t read_address, unsigned gpr) {
    if (gpr >= 16 || gpr == 4 || !instructions.contains(read_address))
        return {};
    Graph graph{executable, instructions, branch_predecessors, entries, terminating_calls, {}};
    if (!ZYAN_SUCCESS(ZydisDecoderInit(&graph.decoder, ZYDIS_MACHINE_MODE_LONG_64, ZYDIS_STACK_WIDTH_64)))
        return {};
    using State = std::tuple<std::uint64_t, unsigned, std::uint64_t>;
    std::vector<State> pending{{read_address, gpr, ~std::uint64_t{0}}};
    std::set<State> visited;
    std::optional<std::uint64_t> bound;
    const auto observe = [&](std::uint64_t count) { bound = std::max(bound.value_or(0), count); };
    while (!pending.empty()) {
        const auto state = pending.back();
        pending.pop_back();
        if (!visited.insert(state).second)
            continue;
        const auto [pc, r, mask] = state;
        if (visited.size() > 65536 || graph.entries.contains(pc))
            return {};
        const auto from = graph.predecessors(pc);
        if (from.empty())
            return {};
        for (auto source : from) {
            Instruction ins;
            if (!graph.decode(source, ins) || clobbering_call(ins, r))
                return {};
            if (const auto count = graph.guard(source, pc, r, mask, ins)) {
                observe(*count);
                continue;
            }
            if (!writes(ins, r)) {
                pending.emplace_back(source, r, mask);
                continue;
            }
            // Keep the masked expression, rather than assuming every value
            // below the mask is a table entry. It still needs a matching guard.
            if (ins.i.mnemonic == ZYDIS_MNEMONIC_AND && ins.i.operand_count_visible == 2) {
                const auto &to = ins.operands[0];
                const auto &value = ins.operands[1];
                if (to.type == ZYDIS_OPERAND_TYPE_REGISTER && number(to.reg.value) == r &&
                    (to.size == 32 || to.size == 64) && (to.actions & ZYDIS_OPERAND_ACTION_WRITE) &&
                    !(to.actions & ZYDIS_OPERAND_ACTION_CONDWRITE) &&
                    value.type == ZYDIS_OPERAND_TYPE_IMMEDIATE) {
                    const auto truncated = to.size == 32 ? mask & 0xffffffffu : mask;
                    pending.emplace_back(source, r, truncated & value.imm.value.u);
                    continue;
                }
            }
            if (ins.i.mnemonic != ZYDIS_MNEMONIC_MOV || ins.i.operand_count_visible != 2)
                return {};
            const auto &to = ins.operands[0];
            const auto &value = ins.operands[1];
            if (to.type != ZYDIS_OPERAND_TYPE_REGISTER || number(to.reg.value) != r ||
                (to.size != 32 && to.size != 64) || to.actions != ZYDIS_OPERAND_ACTION_WRITE)
                return {};
            const auto next_mask = to.size == 32 ? mask & 0xffffffffu : mask;
            if (value.type == ZYDIS_OPERAND_TYPE_REGISTER && value.size == to.size &&
                number(value.reg.value) < 16 && number(value.reg.value) != 4)
                pending.emplace_back(source, number(value.reg.value), next_mask);
            else
                return {};
        }
    }
    return bound;
}
} // namespace GuestCode::Detail

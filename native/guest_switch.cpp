// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_switch.hpp"
#include <Zydis/Zydis.h>
#include <algorithm>
#include <array>
#include <limits>
#include <stdexcept>

namespace GuestCode::Detail {
namespace {
struct Decoded {
    GuestTls::CodeRange range;
    ZydisDecodedInstruction instruction{};
    std::array<ZydisDecodedOperand, ZYDIS_MAX_OPERAND_COUNT> operands{};
};
bool reg(const Decoded &i, unsigned operand, ZydisRegister expected, unsigned width = 64) {
    const auto &o = i.operands[operand];
    return operand < i.instruction.operand_count_visible && o.type == ZYDIS_OPERAND_TYPE_REGISTER &&
           o.reg.value == expected && o.size == width;
}
ZydisRegister enclosing(ZydisRegister r) {
    return ZydisRegisterGetLargestEnclosing(ZYDIS_MACHINE_MODE_LONG_64, r);
}
} // namespace
std::optional<SwitchTable> recognize_switch(std::span<const std::uint8_t> executable,
                                            std::span<const GuestTls::CodeRange> ranges,
                                            std::span<const GuestTls::CodeRange> tail) {
    if (tail.size() < 6 || tail.size() > 8)
        return {};
    ZydisDecoder decoder{};
    if (!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, ZYDIS_MACHINE_MODE_LONG_64, ZYDIS_STACK_WIDTH_64)))
        throw std::runtime_error("cannot initialize switch decoder");
    std::vector<Decoded> code;
    code.reserve(tail.size());
    for (const auto &range : tail) {
        if (range.file_offset > executable.size() || range.size > executable.size() - range.file_offset)
            throw std::runtime_error("switch instruction source outside executable");
        Decoded decoded{range};
        if (!ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, executable.data() + range.file_offset,
                                                 static_cast<std::size_t>(range.size), &decoded.instruction,
                                                 decoded.operands.data())) ||
            decoded.instruction.length != range.size)
            throw std::runtime_error("switch evidence is not an instruction");
        if (!code.empty() && code.back().range.address + code.back().range.size != range.address)
            return {};
        code.push_back(decoded);
    }
    const auto n = code.size();
    const auto &jump = code[n - 1];
    const auto &add = code[n - 2];
    const auto &load = code[n - 3];
    if (jump.instruction.mnemonic != ZYDIS_MNEMONIC_JMP || jump.instruction.operand_count_visible != 1 ||
        jump.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER || jump.operands[0].size != 64)
        return {};
    const auto destination = jump.operands[0].reg.value;
    if (destination == ZYDIS_REGISTER_RSP || add.instruction.mnemonic != ZYDIS_MNEMONIC_ADD ||
        !reg(add, 0, destination) || add.operands[1].type != ZYDIS_OPERAND_TYPE_REGISTER ||
        add.operands[1].size != 64)
        return {};
    const auto base = add.operands[1].reg.value;
    if (base == destination || base == ZYDIS_REGISTER_RSP ||
        load.instruction.mnemonic != ZYDIS_MNEMONIC_MOVSXD || !reg(load, 0, destination))
        return {};
    const auto &memory = load.operands[1];
    if (memory.type != ZYDIS_OPERAND_TYPE_MEMORY || memory.size != 32 || memory.mem.base != base ||
        memory.mem.index == ZYDIS_REGISTER_NONE || memory.mem.index == base ||
        memory.mem.index == ZYDIS_REGISTER_RSP || memory.mem.scale != 4 ||
        (memory.mem.disp.has_displacement && memory.mem.disp.value != 0) ||
        load.instruction.address_width != 64 ||
        (memory.mem.segment != ZYDIS_REGISTER_DS && memory.mem.segment != ZYDIS_REGISTER_SS))
        return {};
    const auto index = memory.mem.index;
    // The bound may apply directly to the table index or to a source copied
    // into it by MOV r32,r32 after the guard (which clears unknown upper bits).
    std::size_t lea_at, guard_at, cmp_at, copy_at = n;
    if (code[n - 4].instruction.mnemonic == ZYDIS_MNEMONIC_LEA) {
        lea_at = n - 4;
        if (code[n - 5].instruction.mnemonic == ZYDIS_MNEMONIC_MOV) {
            if (n < 7)
                return {};
            copy_at = n - 5;
            guard_at = n - 6;
            cmp_at = n - 7;
        } else {
            guard_at = n - 5;
            cmp_at = n - 6;
        }
    } else {
        if (code[n - 4].instruction.mnemonic == ZYDIS_MNEMONIC_MOV) {
            copy_at = n - 4;
            guard_at = n - 5;
            cmp_at = n - 6;
        } else {
            guard_at = n - 4;
            cmp_at = n - 5;
        }
        lea_at = cmp_at;
        while (lea_at && code[lea_at].instruction.mnemonic != ZYDIS_MNEMONIC_LEA)
            --lea_at;
        if (code[lea_at].instruction.mnemonic != ZYDIS_MNEMONIC_LEA)
            return {};
    }
    auto comparison_index = index;
    if (copy_at != n) {
        const auto &copy = code[copy_at];
        if (copy.instruction.operand_count_visible != 2 ||
            copy.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER || copy.operands[0].size != 32 ||
            enclosing(copy.operands[0].reg.value) != index ||
            copy.operands[1].type != ZYDIS_OPERAND_TYPE_REGISTER || copy.operands[1].size != 32)
            return {};
        comparison_index = enclosing(copy.operands[1].reg.value);
    }
    const auto &lea = code[lea_at];
    const auto &guard = code[guard_at];
    const auto &cmp = code[cmp_at];
    if (!reg(lea, 0, base) || lea.operands[1].type != ZYDIS_OPERAND_TYPE_MEMORY ||
        lea.operands[1].mem.base != ZYDIS_REGISTER_RIP || lea.operands[1].mem.index != ZYDIS_REGISTER_NONE ||
        lea.instruction.address_width != 64 || cmp.instruction.mnemonic != ZYDIS_MNEMONIC_CMP ||
        (guard.instruction.mnemonic != ZYDIS_MNEMONIC_JNBE &&
         guard.instruction.mnemonic != ZYDIS_MNEMONIC_JNB) ||
        guard.operands[0].type != ZYDIS_OPERAND_TYPE_IMMEDIATE || !guard.operands[0].imm.is_relative ||
        cmp.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER ||
        enclosing(cmp.operands[0].reg.value) != comparison_index ||
        (cmp.operands[0].size != 32 && cmp.operands[0].size != 64) ||
        cmp.operands[1].type != ZYDIS_OPERAND_TYPE_IMMEDIATE)
        return {};
    const auto &immediate = cmp.operands[1].imm;
    if (immediate.is_signed && immediate.value.s < 0)
        return {};
    const auto limit = immediate.value.u;
    if (limit > 65535)
        return {};
    const auto count = limit + (guard.instruction.mnemonic == ZYDIS_MNEMONIC_JNBE ? 1u : 0u);
    if (!count)
        return {};
    auto entry_at = std::min(cmp_at, lea_at);
    auto zero_at = n;
    if (cmp.operands[0].size == 32 && copy_at == n) {
        // A low-32 comparison cannot bound the full address index unless an
        // unconditional 32-bit write has first cleared the upper half.
        bool zero_extended = false;
        for (std::size_t at = cmp_at; at > 0;) {
            --at;
            const auto &writer = code[at];
            if (at == lea_at)
                continue; // Writes a distinct table-base register.
            const auto &operand = writer.operands[0];
            const auto mnemonic = writer.instruction.mnemonic;
            const bool defined_write = mnemonic == ZYDIS_MNEMONIC_MOV || mnemonic == ZYDIS_MNEMONIC_MOVZX ||
                                       mnemonic == ZYDIS_MNEMONIC_MOVSX || mnemonic == ZYDIS_MNEMONIC_LEA;
            if (defined_write && writer.instruction.operand_count_visible &&
                operand.type == ZYDIS_OPERAND_TYPE_REGISTER && enclosing(operand.reg.value) == index &&
                operand.size == 32 && operand.actions == ZYDIS_OPERAND_ACTION_WRITE &&
                writer.instruction.meta.category != ZYDIS_CATEGORY_CALL) {
                entry_at = std::min(entry_at, at);
                zero_at = at;
                zero_extended = true;
            }
            break; // No arbitrary backward dataflow guesses.
        }
        if (!zero_extended)
            return {};
    }
    // Between the LEA and CMP, only that proven index initialization is allowed.
    for (std::size_t at = entry_at; at < cmp_at; ++at) {
        if (at == lea_at || at == zero_at)
            continue;
        return {};
    }
    ZyanU64 table = 0, out_of_bounds = 0;
    if (!ZYAN_SUCCESS(
            ZydisCalcAbsoluteAddress(&lea.instruction, &lea.operands[1], lea.range.address, &table)) ||
        !ZYAN_SUCCESS(ZydisCalcAbsoluteAddress(&guard.instruction, &guard.operands[0], guard.range.address,
                                               &out_of_bounds)))
        return {};
    if (out_of_bounds >= guard.range.address + guard.range.size &&
        out_of_bounds < jump.range.address + jump.range.size)
        return {};
    const auto locate = [&](std::uint64_t address) -> const GuestTls::CodeRange * {
        auto at = std::upper_bound(ranges.begin(), ranges.end(), address,
                                   [](auto pc, const auto &r) { return pc < r.address; });
        if (at == ranges.begin())
            return nullptr;
        --at;
        return address - at->address < at->size ? &*at : nullptr;
    };
    const auto *range = locate(table);
    if (!range)
        return {}; // Other memory regions are not yet modeled by this recognizer.
    const auto bytes = count * 4;
    if (bytes > range->size - (table - range->address))
        throw std::runtime_error("bounded switch table exceeds mapped source");
    const auto source = range->file_offset + table - range->address;
    SwitchTable result{
        code[entry_at].range.address, guard.range.address, jump.range.address, table, bytes, {}};
    for (std::uint64_t i = 0; i < count; ++i) {
        std::uint32_t bits = 0;
        for (unsigned byte = 0; byte < 4; ++byte)
            bits |= std::uint32_t{executable[static_cast<std::size_t>(source + i * 4 + byte)]} << (8 * byte);
        const auto delta = (bits & 0x80000000u) ? static_cast<std::int64_t>(bits) - 0x100000000LL
                                                : static_cast<std::int64_t>(bits);
        if ((delta < 0 && table < static_cast<std::uint64_t>(-delta)) ||
            (delta >= 0 &&
             table > std::numeric_limits<std::uint64_t>::max() - static_cast<std::uint64_t>(delta)))
            throw std::runtime_error("bounded switch target overflows address space");
        const auto target = delta < 0 ? table - static_cast<std::uint64_t>(-delta)
                                      : table + static_cast<std::uint64_t>(delta);
        if (!locate(target) || (target >= table && target - table < bytes))
            throw std::runtime_error("bounded switch target outside executable code or inside table");
        result.targets.push_back(target);
    }
    return result;
}
} // namespace GuestCode::Detail

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
std::optional<SwitchTable> read_table(std::span<const std::uint8_t> executable,
                                      std::span<const GuestTls::CodeRange> ranges, SwitchTable result,
                                      bool strict = true) {
    const auto table = result.table_address;
    const auto count = result.table_size / 4;
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
    const auto bytes = result.table_size;
    if (bytes > range->size - (table - range->address)) {
        if (!strict)
            return {};
        throw std::runtime_error("bounded switch table exceeds mapped source");
    }
    const auto source = range->file_offset + table - range->address;
    for (std::uint64_t i = 0; i < count; ++i) {
        std::uint32_t bits = 0;
        for (unsigned byte = 0; byte < 4; ++byte)
            bits |= std::uint32_t{executable[static_cast<std::size_t>(source + i * 4 + byte)]} << (8 * byte);
        const auto delta = (bits & 0x80000000u) ? static_cast<std::int64_t>(bits) - 0x100000000LL
                                                : static_cast<std::int64_t>(bits);
        if ((delta < 0 && table < static_cast<std::uint64_t>(-delta)) ||
            (delta >= 0 &&
             table > std::numeric_limits<std::uint64_t>::max() - static_cast<std::uint64_t>(delta))) {
            if (!strict)
                return {};
            throw std::runtime_error("bounded switch target overflows address space at dispatch " +
                                     std::to_string(result.dispatch_address) + " entry " + std::to_string(i) +
                                     " of " + std::to_string(count));
        }
        const auto target = delta < 0 ? table - static_cast<std::uint64_t>(-delta)
                                      : table + static_cast<std::uint64_t>(delta);
        if (!locate(target) || (target >= table && target - table < bytes)) {
            if (!strict)
                return {};
            throw std::runtime_error("bounded switch target outside executable code or inside table");
        }
        result.targets.push_back(target);
    }
    return result;
}
} // namespace
std::optional<SwitchTable>
recognize_switch(std::span<const std::uint8_t> executable, std::span<const GuestTls::CodeRange> ranges,
                 std::span<const GuestTls::CodeRange> tail,
                 const std::function<std::optional<std::uint64_t>(std::uint64_t, unsigned)> &known_base) {
    if (tail.size() < 6 || tail.size() > 32)
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
    const auto number = [](ZydisRegister r) -> unsigned {
        r = enclosing(r);
        return r >= ZYDIS_REGISTER_RAX && r <= ZYDIS_REGISTER_R15
                   ? static_cast<unsigned>(r - ZYDIS_REGISTER_RAX)
                   : 16;
    };
    const auto context_move = [&](const Decoded &i) {
        const auto mnemonic = i.instruction.mnemonic;
        if (mnemonic != ZYDIS_MNEMONIC_MOV && mnemonic != ZYDIS_MNEMONIC_MOVZX &&
            mnemonic != ZYDIS_MNEMONIC_MOVSX && mnemonic != ZYDIS_MNEMONIC_MOVSXD &&
            mnemonic != ZYDIS_MNEMONIC_LEA)
            return false;
        if (i.instruction.operand_count_visible != 2 || i.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER ||
            number(i.operands[0].reg.value) >= 16 || (i.operands[0].size != 32 && i.operands[0].size != 64))
            return false;
        const auto kind = i.operands[1].type;
        return kind == ZYDIS_OPERAND_TYPE_REGISTER || kind == ZYDIS_OPERAND_TYPE_MEMORY ||
               (mnemonic == ZYDIS_MNEMONIC_MOV && kind == ZYDIS_OPERAND_TYPE_IMMEDIATE);
    };
    const auto defined_alu32 = [&](const Decoded &i) {
        const auto mnemonic = i.instruction.mnemonic;
        const bool unary = mnemonic == ZYDIS_MNEMONIC_INC || mnemonic == ZYDIS_MNEMONIC_DEC;
        const bool binary = mnemonic == ZYDIS_MNEMONIC_ADD || mnemonic == ZYDIS_MNEMONIC_SUB ||
                            mnemonic == ZYDIS_MNEMONIC_AND || mnemonic == ZYDIS_MNEMONIC_OR ||
                            mnemonic == ZYDIS_MNEMONIC_XOR;
        return (unary || binary) && i.instruction.operand_count_visible == (unary ? 1 : 2) &&
               i.operands[0].type == ZYDIS_OPERAND_TYPE_REGISTER && i.operands[0].size == 32 &&
               number(i.operands[0].reg.value) < 16 && (i.operands[0].actions & ZYDIS_OPERAND_ACTION_WRITE) &&
               !(i.operands[0].actions & ZYDIS_OPERAND_ACTION_CONDWRITE);
    };
    const auto safe_vector = [&](const Decoded &i) {
        const auto encoding = i.instruction.encoding;
        if (encoding != ZYDIS_INSTRUCTION_ENCODING_VEX && encoding != ZYDIS_INSTRUCTION_ENCODING_EVEX &&
            encoding != ZYDIS_INSTRUCTION_ENCODING_XOP)
            return false;
        const auto category = i.instruction.meta.category;
        if (category == ZYDIS_CATEGORY_CALL || category == ZYDIS_CATEGORY_COND_BR ||
            category == ZYDIS_CATEGORY_UNCOND_BR || category == ZYDIS_CATEGORY_RET ||
            category == ZYDIS_CATEGORY_INTERRUPT || category == ZYDIS_CATEGORY_SYSCALL ||
            category == ZYDIS_CATEGORY_SYSRET)
            return false;
        for (unsigned operand = 0; operand < i.instruction.operand_count; ++operand) {
            const auto &o = i.operands[operand];
            if (!(o.actions & ZYDIS_OPERAND_ACTION_MASK_WRITE))
                continue;
            if (o.type == ZYDIS_OPERAND_TYPE_MEMORY ||
                (o.type == ZYDIS_OPERAND_TYPE_REGISTER && number(o.reg.value) < 16))
                return false;
        }
        return true;
    };
    const auto writes_gpr = [&](const Decoded &i, ZydisRegister r) {
        for (unsigned operand = 0; operand < i.instruction.operand_count; ++operand) {
            const auto &o = i.operands[operand];
            if (o.type == ZYDIS_OPERAND_TYPE_REGISTER && enclosing(o.reg.value) == r &&
                (o.actions & ZYDIS_OPERAND_ACTION_MASK_WRITE))
                return true;
        }
        return false;
    };
    const auto n = code.size();
    const auto &jump = code[n - 1];
    if (jump.instruction.mnemonic != ZYDIS_MNEMONIC_JMP || jump.instruction.operand_count_visible != 1 ||
        jump.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER || jump.operands[0].size != 64)
        return {};
    auto destination = jump.operands[0].reg.value;
    if (destination == ZYDIS_REGISTER_RSP || number(destination) >= 16)
        return {};
    auto add_at = n;
    for (std::size_t at = n - 1; at > 0;) {
        --at;
        const auto &i = code[at];
        if (i.instruction.mnemonic == ZYDIS_MNEMONIC_ADD && reg(i, 0, destination)) {
            add_at = at;
            break;
        }
        if (safe_vector(i))
            continue;
        if (!context_move(i))
            return {};
        if (writes_gpr(i, destination)) {
            if (i.instruction.mnemonic != ZYDIS_MNEMONIC_MOV || !reg(i, 0, destination) ||
                i.operands[1].type != ZYDIS_OPERAND_TYPE_REGISTER || i.operands[1].size != 64 ||
                number(i.operands[1].reg.value) >= 16 || i.operands[1].reg.value == ZYDIS_REGISTER_RSP)
                return {};
            destination = i.operands[1].reg.value;
        }
    }
    if (add_at == n || !add_at)
        return {};
    const auto load_at = add_at - 1;
    const auto &add = code[add_at];
    const auto &load = code[load_at];
    if (add.operands[1].type != ZYDIS_OPERAND_TYPE_REGISTER || add.operands[1].size != 64)
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
    std::size_t lea_at = n, guard_at = n, cmp_at = n;
    for (std::size_t at = load_at; at > 0;) {
        --at;
        const auto &candidate = code[at];
        if (guard_at == n && at > 0 &&
            (candidate.instruction.mnemonic == ZYDIS_MNEMONIC_JNBE ||
             candidate.instruction.mnemonic == ZYDIS_MNEMONIC_JNB) &&
            code[at - 1].instruction.mnemonic == ZYDIS_MNEMONIC_CMP) {
            guard_at = at;
            cmp_at = at - 1;
        }
    }
    auto needed_base = base;
    for (std::size_t at = load_at; at > 0;) {
        --at;
        const auto &candidate = code[at];
        if (!writes_gpr(candidate, needed_base))
            continue;
        if (candidate.instruction.mnemonic == ZYDIS_MNEMONIC_LEA && reg(candidate, 0, needed_base) &&
            candidate.operands[1].type == ZYDIS_OPERAND_TYPE_MEMORY &&
            candidate.operands[1].mem.base == ZYDIS_REGISTER_RIP &&
            candidate.operands[1].mem.index == ZYDIS_REGISTER_NONE &&
            candidate.instruction.address_width == 64) {
            lea_at = at;
            break;
        }
        if (candidate.instruction.mnemonic == ZYDIS_MNEMONIC_MOV && reg(candidate, 0, needed_base) &&
            candidate.operands[1].type == ZYDIS_OPERAND_TYPE_REGISTER && candidate.operands[1].size == 64 &&
            number(candidate.operands[1].reg.value) < 16 &&
            candidate.operands[1].reg.value != ZYDIS_REGISTER_RSP) {
            needed_base = candidate.operands[1].reg.value;
            continue;
        }
        return {};
    }
    std::optional<std::uint64_t> invariant_base;
    // A callee-saved RIP base may be initialized long before the compare,
    // across calls/loop edges that are outside the local guard proof. Prefer
    // the independently checked CFG invariant in that case, rather than
    // treating those intervening instructions as part of index validation.
    if ((lea_at == n || lea_at < cmp_at) && needed_base == base && known_base) {
        invariant_base = known_base(load.range.address, number(base));
        if (invariant_base) lea_at = n;
    }
    if ((lea_at == n && !invariant_base) || guard_at == n)
        return {};
    const auto &guard = code[guard_at];
    const auto &cmp = code[cmp_at];
    if (guard.operands[0].type != ZYDIS_OPERAND_TYPE_IMMEDIATE || !guard.operands[0].imm.is_relative ||
        cmp.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER ||
        (cmp.operands[0].size != 32 && cmp.operands[0].size != 64) ||
        cmp.operands[1].type != ZYDIS_OPERAND_TYPE_IMMEDIATE)
        return {};
    // Consecutive identical guards observe the same flags. Once the first
    // guard falls through, each repeated guard necessarily falls through too.
    // Only adjacent copies are admitted; no flag-writing instruction or other
    // condition may be crossed. Late entries into this span invalidate the
    // proof in discover(), just as entries bypassing the first guard do.
    auto guard_end = guard_at;
    while (guard_end + 1 < load_at) {
        const auto &next = code[guard_end + 1];
        if (next.instruction.mnemonic != guard.instruction.mnemonic ||
            next.instruction.operand_count_visible != 1 ||
            next.operands[0].type != ZYDIS_OPERAND_TYPE_IMMEDIATE || !next.operands[0].imm.is_relative)
            break;
        ++guard_end;
    }
    const auto comparison_index = enclosing(cmp.operands[0].reg.value);
    if (number(comparison_index) >= 16 || number(index) >= 16)
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
    bool upper_zero = cmp.operands[0].size == 64;
    if (!upper_zero) {
        for (std::size_t at = cmp_at; at > 0;) {
            --at;
            const auto &writer = code[at];
            if (writer.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER ||
                enclosing(writer.operands[0].reg.value) != comparison_index ||
                !(writer.operands[0].actions & ZYDIS_OPERAND_ACTION_MASK_WRITE))
                continue;
            if ((context_move(writer) || defined_alu32(writer)) &&
                (writer.operands[0].actions == ZYDIS_OPERAND_ACTION_WRITE || defined_alu32(writer)) &&
                (writer.operands[0].size == 32 ||
                 (writer.instruction.mnemonic == ZYDIS_MNEMONIC_MOVSXD && writer.operands[0].size == 64 &&
                  writer.operands[1].size == 32))) {
                upper_zero = true;
                entry_at = std::min(entry_at, at);
            }
            break;
        }
    }
    struct Bound {
        bool low = false;
        bool full = false;
    };
    std::array<Bound, 16> bounds{};
    bounds[number(comparison_index)] = {true, upper_zero};
    // Track only the guarded value through explicit moves. Modeled arithmetic
    // after the guard kills facts; vector operations must leave GPRs and memory
    // unchanged. No unrelated value is guessed to carry the bound.
    for (std::size_t at = entry_at; at < load_at; ++at) {
        if (at == cmp_at || (at >= guard_at && at <= guard_end))
            continue;
        const auto &i = code[at];
        if (safe_vector(i))
            continue;
        if (!context_move(i) && !defined_alu32(i))
            return {};
        const auto destination_number = number(i.operands[0].reg.value);
        if (at <= guard_at)
            continue;
        Bound value{};
        if (i.instruction.mnemonic == ZYDIS_MNEMONIC_MOV &&
            i.operands[1].type == ZYDIS_OPERAND_TYPE_REGISTER && i.operands[0].size == i.operands[1].size &&
            number(i.operands[1].reg.value) < 16) {
            value = bounds[number(i.operands[1].reg.value)];
            if (i.operands[0].size == 32)
                value.full = value.low;
        }
        bounds[destination_number] = value;
    }
    if (!bounds[number(index)].full)
        return {};
    ZyanU64 table = 0, out_of_bounds = 0;
    if (invariant_base)
        table = *invariant_base;
    else {
        const auto &lea = code[lea_at];
        if (!ZYAN_SUCCESS(
                ZydisCalcAbsoluteAddress(&lea.instruction, &lea.operands[1], lea.range.address, &table)))
            return {};
    }
    if (!ZYAN_SUCCESS(ZydisCalcAbsoluteAddress(&guard.instruction, &guard.operands[0], guard.range.address,
                                               &out_of_bounds)))
        return {};
    if (out_of_bounds >= guard.range.address + guard.range.size &&
        out_of_bounds < jump.range.address + jump.range.size)
        return {};
    SwitchTable result{
        code[entry_at].range.address, guard.range.address, jump.range.address, table, count * 4, {}, {}, {}};
    if (invariant_base)
        result.invariant_base = BaseRead{load.range.address, number(base)};
    return read_table(executable, ranges, std::move(result));
}
std::optional<SwitchTable> recognize_cfg_switch(
    std::span<const std::uint8_t> executable, std::span<const GuestTls::CodeRange> ranges,
    std::span<const GuestTls::CodeRange> tail,
    const std::function<std::optional<std::uint64_t>(std::uint64_t, unsigned)> &known_base,
    const std::function<std::optional<std::uint64_t>(std::uint64_t, unsigned)> &known_bound) {
    if (tail.size() < 3 || tail.size() > 32 || !known_base || !known_bound)
        return {};
    ZydisDecoder decoder{};
    if (!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, ZYDIS_MACHINE_MODE_LONG_64, ZYDIS_STACK_WIDTH_64)))
        return {};
    std::vector<Decoded> code;
    for (const auto &r : tail) {
        if (r.file_offset > executable.size() || r.size > executable.size() - r.file_offset)
            return {};
        Decoded c{r};
        if (!ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder, executable.data() + r.file_offset,
                                                 static_cast<std::size_t>(r.size), &c.instruction,
                                                 c.operands.data())) ||
            c.instruction.length != r.size ||
            (!code.empty() && code.back().range.address + code.back().range.size != r.address))
            return {};
        code.push_back(c);
    }
    const auto valid_gpr = [](ZydisRegister r) {
        r = enclosing(r);
        return r >= ZYDIS_REGISTER_RAX && r <= ZYDIS_REGISTER_R15 && r != ZYDIS_REGISTER_RSP;
    };
    const auto &jump = code.back();
    if (jump.instruction.mnemonic != ZYDIS_MNEMONIC_JMP || jump.instruction.operand_count_visible != 1 ||
        jump.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER || jump.operands[0].size != 64 ||
        !valid_gpr(jump.operands[0].reg.value))
        return {};
    const auto preserve_move = [&](const Decoded &c, ZydisRegister &target) {
        if (c.instruction.mnemonic == ZYDIS_MNEMONIC_NOP)
            return true;
        if (c.instruction.mnemonic != ZYDIS_MNEMONIC_MOV || c.instruction.operand_count_visible != 2 ||
            c.operands[0].type != ZYDIS_OPERAND_TYPE_REGISTER || !valid_gpr(c.operands[0].reg.value) ||
            (c.operands[0].size != 32 && c.operands[0].size != 64))
            return false;
        if (c.operands[1].type != ZYDIS_OPERAND_TYPE_REGISTER &&
            c.operands[1].type != ZYDIS_OPERAND_TYPE_MEMORY &&
            c.operands[1].type != ZYDIS_OPERAND_TYPE_IMMEDIATE)
            return false;
        if (enclosing(c.operands[0].reg.value) == target) {
            if (!reg(c, 0, target) || c.operands[1].type != ZYDIS_OPERAND_TYPE_REGISTER ||
                c.operands[1].size != 64 || !valid_gpr(c.operands[1].reg.value))
                return false;
            target = c.operands[1].reg.value;
        }
        return true;
    };
    auto destination = jump.operands[0].reg.value;
    auto add_at = code.size();
    for (std::size_t at = code.size() - 1; at > 0;) {
        --at;
        const auto &c = code[at];
        if (c.instruction.mnemonic == ZYDIS_MNEMONIC_ADD && reg(c, 0, destination)) {
            add_at = at;
            break;
        }
        if (!preserve_move(c, destination))
            return {};
    }
    if (add_at == code.size() || !add_at)
        return {};
    const auto &add = code[add_at];
    if (add.instruction.operand_count_visible != 2 || add.operands[1].type != ZYDIS_OPERAND_TYPE_REGISTER ||
        add.operands[1].size != 64)
        return {};
    const auto base = add.operands[1].reg.value;
    if (!valid_gpr(base) || base == destination)
        return {};
    // The signed offset may be copied before ADD, but the table base must not
    // change between the load and its use in ADD. Track only MOV/NOP paths.
    auto offset_register = destination;
    auto load_at = code.size();
    for (std::size_t at = add_at; at > 0;) {
        --at;
        const auto &c = code[at];
        if (c.instruction.mnemonic == ZYDIS_MNEMONIC_MOVSXD && reg(c, 0, offset_register)) {
            load_at = at;
            break;
        }
        if (c.operands[0].type == ZYDIS_OPERAND_TYPE_REGISTER && enclosing(c.operands[0].reg.value) == base)
            return {};
        if (!preserve_move(c, offset_register) || offset_register == base)
            return {};
    }
    if (load_at == code.size())
        return {};
    const auto &load = code[load_at];
    if (load.instruction.operand_count_visible != 2)
        return {};
    const auto &memory = load.operands[1];
    if (base < ZYDIS_REGISTER_RAX || base > ZYDIS_REGISTER_R15 || base == ZYDIS_REGISTER_RSP ||
        base == destination || memory.type != ZYDIS_OPERAND_TYPE_MEMORY || memory.size != 32 ||
        memory.mem.base != base || memory.mem.index < ZYDIS_REGISTER_RAX ||
        memory.mem.index > ZYDIS_REGISTER_R15 || memory.mem.index == ZYDIS_REGISTER_RSP ||
        memory.mem.index == base || memory.mem.scale != 4 ||
        (memory.mem.disp.has_displacement && memory.mem.disp.value != 0) ||
        load.instruction.address_width != 64 ||
        (memory.mem.segment != ZYDIS_REGISTER_DS && memory.mem.segment != ZYDIS_REGISTER_SS))
        return {};
    const auto base_gpr = static_cast<unsigned>(base - ZYDIS_REGISTER_RAX);
    const auto index_gpr = static_cast<unsigned>(memory.mem.index - ZYDIS_REGISTER_RAX);
    const auto table = known_base(load.range.address, base_gpr);
    const auto count = known_bound(load.range.address, index_gpr);
    if (!table || !count || !*count || *count > 65536)
        return {};
    SwitchTable result{load.range.address,
                       0,
                       jump.range.address,
                       *table,
                       *count * 4,
                       {},
                       BaseRead{load.range.address, base_gpr},
                       BaseRead{load.range.address, index_gpr}};
    // CFG bounds can overestimate the domain when other conditions are not
    // modeled. If that domain is not a fully valid table, retain the original
    // unresolved transfer; no data classification or targets are published.
    return read_table(executable, ranges, std::move(result), false);
}
} // namespace GuestCode::Detail

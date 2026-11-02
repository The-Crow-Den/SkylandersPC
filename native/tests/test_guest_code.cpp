// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_code.hpp"
#include "guest_constants.hpp"
#include "guest_bounds.hpp"
#include "guest_switch.hpp"
#include <openssl/evp.h>
#include <array>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <source_location>

void require(bool ok, std::source_location site=std::source_location::current()) {
    if (!ok) throw std::runtime_error("guest code assertion failed at line " + std::to_string(site.line()));
}
template<class F> void rejects(F action, const char* expected, std::source_location site=std::source_location::current()) {
    std::string actual = "no rejection";
    try { action(); } catch (const std::runtime_error& e) {
        actual = e.what();
        if (actual.find(expected) != std::string::npos) return;
    }
    throw std::runtime_error("expected rejection '" + std::string(expected) + "' at line " +
        std::to_string(site.line()) + ": " + actual);
}

std::string hash(std::span<const std::uint8_t> bytes) {
    std::array<unsigned char,EVP_MAX_MD_SIZE> digest{};
    unsigned length = 0;
    require(EVP_Digest(bytes.data(),bytes.size(),digest.data(),&length,EVP_sha256(),nullptr) == 1);
    std::ostringstream out;
    for (unsigned i=0;i<length;++i) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(digest[i]);
    return out.str();
}
GuestCode::Analysis analyze(std::span<const std::uint8_t> code,
                           std::span<const std::uint64_t> roots, std::size_t limit = 100) {
    const std::array<GuestTls::CodeRange,1> ranges{{{0,0x10000,code.size()}}};
    return GuestCode::discover(code,ranges,roots,hash(code),limit);
}
std::vector<std::uint8_t> switch_fixture(bool base_first = false) {
    std::vector<std::uint8_t> code;
    if (!base_first) code={0x89,0xf8,0x83,0xf8,1,0x77,16,0x48,0x8d,0x15,10,0,0,0};
    else code={0x48,0x8d,0x15,17,0,0,0,0x89,0xf8,0x83,0xf8,1,0x77,9};
    const std::vector<std::uint8_t> rest{0x48,0x63,0x04,0x82,0x48,0x01,0xd0,0xff,0xe0,0xc3,
        8,0,0,0,18,0,0,0,0x64,0x48,0x8b,4,0x25,0,0,0,0,0xc3,0xc3};
    code.insert(code.end(),rest.begin(),rest.end());
    return code;
}
std::vector<std::uint8_t> copy_switch_fixture(bool wide_compare, bool wide_copy, unsigned initialization=0, bool chain=false) {
    std::vector<std::uint8_t> code;
    if(initialization==1) code={0x89,0xf7}; // MOV EDI,ESI clears the high half.
    if(initialization==2) code={0x48,0x63,0xfe}; // MOVSXD RDI,ESI; guard excludes negatives.
    if(wide_compare) code.push_back(0x48);
    code.insert(code.end(),{0x83,0xff,1});
    const auto guard=code.size(); code.insert(code.end(),{0x77,0});
    if(chain) code.insert(code.end(),{0x89,0xf9,0x89,0xc8}); // EDI -> ECX -> EAX.
    else { if(wide_copy) code.push_back(0x48); code.insert(code.end(),{0x89,0xf8}); }
    code.insert(code.end(),{0xb9,42,0,0,0}); // Unrelated MOV ECX,42 must not destroy RAX's bound.
    const auto lea=code.size();code.insert(code.end(),{0x48,0x8d,0x15,0,0,0,0});
    code.insert(code.end(),{0x48,0x63,0x04,0x82,0x48,0x01,0xd0,0xff,0xe0});
    const auto default_case=code.size();code.push_back(0xc3);
    const auto table=code.size();code.resize(code.size()+8);
    const auto first=code.size();code.insert(code.end(),{0x64,0x48,0x8b,4,0x25,0,0,0,0,0xc3});
    const auto second=code.size();code.push_back(0xc3);
    code[guard+1]=static_cast<std::uint8_t>(default_case-guard-2);
    for(unsigned i=0;i<4;++i) {
        code[lea+3+i]=static_cast<std::uint8_t>((table-lea-7)>>(8*i));
        code[table+i]=static_cast<std::uint8_t>((first-table)>>(8*i));
        code[table+4+i]=static_cast<std::uint8_t>((second-table)>>(8*i));
    }
    return code;
}
void constant_tests() {
    const std::array<std::uint64_t,1> root{0x10000};
    const std::vector<std::uint8_t> loop{0x4c,0x8d,0x3d,0x39,0,0,0,0x90,0x75,0xfd,0xc3};
    const auto evidence=analyze(loop,root);
    std::map<std::uint64_t,GuestTls::CodeRange> instructions;
    for(const auto& r:evidence.instructions) instructions.emplace(r.address,r);
    const std::multimap<std::uint64_t,std::uint64_t> back_edge{{0x10007,0x10008}};
    require(GuestCode::Detail::known_rip_base(loop,instructions,back_edge,{0x10000},{},0x10007,15)==0x10040);
    require(!GuestCode::Detail::known_rip_base(loop,instructions,back_edge,{0x10000,0x10007},{},0x10007,15));
    // Different incoming definitions must agree, even if both paths are valid.
    std::vector<std::uint8_t> conflict{0x85,0xc0,0x74,9,
        0x4c,0x8d,0x3d,0,0,0,0,0xeb,7,0x4c,0x8d,0x3d,0,0,0,0,0x90,0xc3};
    const auto set_lea=[&](unsigned offset,std::uint64_t value) {
        const auto displacement=static_cast<std::uint32_t>(value-(0x10000+offset+7));
        for(unsigned i=0;i<4;++i) conflict[offset+3+i]=static_cast<std::uint8_t>(displacement>>(i*8));
    };
    set_lea(4,0x11000); set_lea(13,0x12000);
    auto graph=analyze(conflict,root); instructions.clear();
    for(const auto& r:graph.instructions) instructions.emplace(r.address,r);
    const std::multimap<std::uint64_t,std::uint64_t> incoming{{0x1000d,0x10002},{0x10014,0x1000b}};
    require(!GuestCode::Detail::known_rip_base(conflict,instructions,incoming,{0x10000},{},0x10014,15));
    set_lea(13,0x11000);
    require(GuestCode::Detail::known_rip_base(conflict,instructions,incoming,{0x10000},{},0x10014,15)==0x11000);
    // Calls preserve guest callee-saved registers, but not RAX/other volatile registers.
    for(unsigned gpr : {0u,15u}) {
        std::vector<std::uint8_t> call={static_cast<std::uint8_t>(gpr==15?0x4c:0x48),0x8d,
            static_cast<std::uint8_t>(gpr==15?0x3d:0x05),0x39,0,0,0,0xff,0xd2,0x90,0xc3};
        graph=analyze(call,root); instructions.clear();
        for(const auto& r:graph.instructions) instructions.emplace(r.address,r);
        const auto value=GuestCode::Detail::known_rip_base(call,instructions,{}, {0x10000},{},0x10009,gpr);
        require(gpr==15 ? value==0x10040 : !value);
        require(!GuestCode::Detail::known_rip_base(call,instructions,{}, {0x10000},{0x10007},0x10009,gpr));
    }
}

std::vector<std::uint8_t> invariant_switch_fixture() {
    std::vector<std::uint8_t> code{0x4c,0x8d,0x3d,0,0,0,0,0xeb,8};
    code.insert(code.end(),8,0xff); // Unreachable gap: no contiguous backward LEA search can cross it.
    code.insert(code.end(),{0x89,0xf8,0x83,0xf8,1});
    const auto guard=code.size();code.insert(code.end(),{0x77,0});
    code.insert(code.end(),{0x49,0x63,0x04,0x87,0x4c,0x01,0xf8,0xff,0xe0});
    const auto default_case=code.size();code.push_back(0xc3);
    const auto table=code.size();code.resize(code.size()+8);
    const auto first=code.size();code.insert(code.end(),{0x64,0x48,0x8b,4,0x25,0,0,0,0,0xc3});
    const auto second=code.size();code.push_back(0xc3);
    code[guard+1]=static_cast<std::uint8_t>(default_case-guard-2);
    for(unsigned i=0;i<4;++i) {
        code[3+i]=static_cast<std::uint8_t>((table-7)>>(8*i));
        code[table+i]=static_cast<std::uint8_t>((first-table)>>(8*i));
        code[table+4+i]=static_cast<std::uint8_t>((second-table)>>(8*i));
    }
    return code;
}

std::vector<std::uint8_t> decorated_switch_fixture(bool copied_base, bool copied_target, unsigned vector_kind=0, bool clobber_base=false) {
    std::vector<std::uint8_t> code{0x89,0xf8,0x83,0xf8,1};
    const auto guard=code.size();code.insert(code.end(),{0x77,0});
    if(vector_kind==1) code.insert(code.end(),{0xc5,0xf8,0x57,0xc0}); // VXORPS XMM0,XMM0,XMM0.
    if(vector_kind==2) code.insert(code.end(),{0xc5,0xfa,0x2c,0xc0}); // VCVTTSS2SI EAX,XMM0 kills the index bound.
    const auto lea=code.size();code.insert(code.end(),{0x48,0x8d,static_cast<std::uint8_t>(copied_base?0x3d:0x15),0,0,0,0});
    if(copied_base) code.insert(code.end(),{0x48,0x89,0xfa}); // RDI table address -> RDX.
    if(clobber_base) code.insert(code.end(),{0xba,0,0,0,0});
    if(vector_kind==3) code.insert(code.end(),{0xc5,0xfa,0x11,0x02}); // VMOVSS [RDX],XMM0 writes table memory.
    code.insert(code.end(),{0x48,0x63,0x04,0x82,0x48,0x01,0xd0});
    if(copied_target) code.insert(code.end(),{0x48,0x89,0xc1}); // Copy formed target RAX -> RCX.
    code.insert(code.end(),{0xba,123,0,0,0}); // Base may be restored/clobbered AFTER the target is formed.
    code.insert(code.end(),{0xff,static_cast<std::uint8_t>(copied_target?0xe1:0xe0)});
    const auto default_case=code.size();code.push_back(0xc3);
    const auto table=code.size();code.resize(code.size()+8);
    const auto first=code.size();code.insert(code.end(),{0x64,0x48,0x8b,4,0x25,0,0,0,0,0xc3});
    const auto second=code.size();code.push_back(0xc3);
    code[guard+1]=static_cast<std::uint8_t>(default_case-guard-2);
    for(unsigned i=0;i<4;++i) {
        code[lea+3+i]=static_cast<std::uint8_t>((table-lea-7)>>(8*i));
        code[table+i]=static_cast<std::uint8_t>((first-table)>>(8*i));
        code[table+4+i]=static_cast<std::uint8_t>((second-table)>>(8*i));
    }
    return code;
}

void switch_tests() {
    const std::array<std::uint64_t,1> root{0x10000};
    for (bool base_first : {false,true}) {
        const auto code=switch_fixture(base_first);
        const auto analysis=analyze(code,root);
        require(analysis.unresolved.empty() && analysis.switch_tables.size()==1);
        const auto& table=analysis.switch_tables[0];
        require(table.dispatch_address==0x10015 && table.table_address==0x10018 && table.table_size==8 &&
            table.targets==std::vector<std::uint64_t>{0x10020,0x1002a});
        require(GuestTls::inspect(code,analysis.instructions).sites.size()==1);
        for(const auto& ins:analysis.instructions) require(ins.address<0x10018 || ins.address>=0x10020);
    }
    // The guard may check an argument's low 32 bits before copying them to
    // the actual address index. That copy must use the same source register.
    auto copied_index=switch_fixture();
    const std::array<std::uint8_t,7> copy_prefix{0x83,0xff,1,0x77,18,0x89,0xf8};
    std::copy(copy_prefix.begin(),copy_prefix.end(),copied_index.begin());
    require(analyze(copied_index,root).switch_tables.size()==1);
    auto unrelated_copy=copied_index; unrelated_copy[6]=0xc8; // MOV EAX,ECX, not EDI.
    require(analyze(unrelated_copy,root).switch_tables.empty());
    require(analyze(copy_switch_fixture(false,false),root).switch_tables.size()==1);
    require(analyze(copy_switch_fixture(false,true),root).switch_tables.empty()); // Unknown upper half copied too.
    require(analyze(copy_switch_fixture(true,true),root).switch_tables.size()==1);
    require(analyze(copy_switch_fixture(false,true,1),root).switch_tables.size()==1);
    require(analyze(copy_switch_fixture(false,true,2),root).switch_tables.size()==1);
    require(analyze(copy_switch_fixture(false,false,0,true),root).switch_tables.size()==1);
    const auto invariant=invariant_switch_fixture();
    require(analyze(invariant,root).switch_tables.size()==1);
    require(analyze(invariant,std::array<std::uint64_t,2>{0x10000,0x10011}).switch_tables.empty());
    for(bool copied_base : {false,true}) for(bool copied_target : {false,true}) {
        const auto decorated=decorated_switch_fixture(copied_base,copied_target,1);
        const auto discovered=analyze(decorated,root);
        require(discovered.switch_tables.size()==1 && GuestTls::inspect(decorated,discovered.instructions).sites.size()==1);
    }
    require(analyze(decorated_switch_fixture(true,false,2),root).switch_tables.empty());
    require(analyze(decorated_switch_fixture(true,false,3),root).switch_tables.empty());
    require(analyze(decorated_switch_fixture(true,false,0,true),root).switch_tables.empty());
    auto additional_caller=invariant;
    const auto caller_offset=additional_caller.size();
    additional_caller.push_back(0xe8);
    const auto displacement=static_cast<std::uint32_t>(17-caller_offset-5);
    for(unsigned i=0;i<4;++i) additional_caller.push_back(static_cast<std::uint8_t>(displacement>>(8*i)));
    additional_caller.push_back(0xc3);
    require(analyze(additional_caller,std::array<std::uint64_t,2>{0x10000,0x10000+caller_offset}).switch_tables.empty());
    auto late_entry=invariant;
    const auto second_root=late_entry.size();
    auto second_switch=switch_fixture();
    const auto cross_target=static_cast<std::uint32_t>(17-second_root-24);
    for(unsigned i=0;i<4;++i) second_switch[24+i]=static_cast<std::uint8_t>(cross_target>>(8*i));
    late_entry.insert(late_entry.end(),second_switch.begin(),second_switch.end());
    const auto revalidated=analyze(late_entry,std::array<std::uint64_t,2>{0x10000,0x10000+second_root});
    require(revalidated.switch_tables.size()==1 && revalidated.switch_tables[0].dispatch_address==0x10000+second_root+21);
    auto unknown_upper=switch_fixture(); unknown_upper[0]=0x90; unknown_upper[1]=0x90;
    require(analyze(unknown_upper,root).switch_tables.empty());
    auto undefined_writer=switch_fixture();
    undefined_writer.erase(undefined_writer.begin(),undefined_writer.begin()+2);
    undefined_writer.insert(undefined_writer.begin(),{0x0f,0xbc,0xc7}); // BSF EAX,EDI: zero input is undefined.
    require(analyze(undefined_writer,root).switch_tables.empty());
    auto normalized_index=switch_fixture(); normalized_index[0]=0xff; normalized_index[1]=0xc8; // DEC EAX.
    require(analyze(normalized_index,root).switch_tables.size()==1);
    auto incremented_index=switch_fixture(); incremented_index[0]=0xff; incremented_index[1]=0xc0; // INC EAX.
    require(analyze(incremented_index,root).switch_tables.size()==1);
    auto wrong_guard=switch_fixture(); wrong_guard[5]=0x76; // JBE does not guard the upper bound.
    require(analyze(wrong_guard,root).switch_tables.empty());
    auto guard_bypass=switch_fixture(); guard_bypass[6]=0; // Out-of-bound branch enters LEA.
    require(analyze(guard_bypass,root).switch_tables.empty());
    // A later root must not silently bypass the initialization/guard proof.
    require(analyze(switch_fixture(),std::array<std::uint64_t,2>{0x10000,0x10007}).switch_tables.empty());
    auto outside=switch_fixture(); outside[24]=0xff; outside[25]=0xff; outside[26]=0xff; outside[27]=0x7f;
    rejects([&] { analyze(outside,root); },"switch target outside");
    auto in_table=switch_fixture(); in_table[24]=0;
    rejects([&] { analyze(in_table,root); },"inside table");
    auto truncated=switch_fixture(); truncated[10]=27; // Table points too close to the mapping end.
    rejects([&] { analyze(truncated,root); },"table exceeds");
    auto interior=switch_fixture(); interior[28]=9; // Case two enters case one's MOV.
    rejects([&] { analyze(interior,root); },"overlaps");
    // JAE with limit two bounds the same two entries (instead of JA limit one).
    auto exclusive=switch_fixture(); exclusive[4]=2; exclusive[5]=0x73;
    require(analyze(exclusive,root).switch_tables.size()==1);
}

void cfg_bound_tests() {
    const std::array<std::uint64_t,1> root{0x10000};
    const std::vector<std::uint8_t> original{0x89,0xf8,0x83,0xf8,1,0x77,7,0xeb,4,
        0xff,0xff,0xff,0xff,0xc3,0xc3};
    const auto query=[&](const auto& code,unsigned read,
        const std::multimap<std::uint64_t,std::uint64_t>& edges,
        std::span<const std::uint64_t> entries,unsigned gpr=0) {
        const auto a=analyze(code,entries);
        std::map<std::uint64_t,GuestTls::CodeRange> instructions;
        for(const auto& r:a.instructions) instructions.emplace(r.address,r);
        return GuestCode::Detail::known_index_bound(code,instructions,edges,
            std::set<std::uint64_t>(entries.begin(),entries.end()),{},0x10000+read,gpr);
    };
    const std::multimap<std::uint64_t,std::uint64_t> edges{{0x1000e,0x10005},{0x1000d,0x10007}};
    require(!query(std::vector<std::uint8_t>{0x48,0x83,0xe0,7,0xc3},4,{},root));
    require(!query(std::vector<std::uint8_t>{0x83,0xe0,5,0xc3},3,{},root));
    require(!query(std::vector<std::uint8_t>{0x83,0xe0,0,0xc3},3,{},root));
    require(!query(std::vector<std::uint8_t>{0x48,0x83,0xe0,0xff,0xc3},4,{},root));
    require(!query(std::vector<std::uint8_t>{0x66,0x83,0xe0,7,0xc3},4,{},root));
    require(!query(std::vector<std::uint8_t>{0x48,0x25,0,0,1,0,0xc3},6,{},root));
    const std::vector<std::uint8_t> alias{0x89,0xf9,0x89,0xc8,0x83,0xe0,7,0x83,0xf8,1,
        0x77,11,0x48,0x83,0xe1,7,0xeb,4,0xff,0xff,0xff,0xff,0xc3,0xc3};
    const std::multimap<std::uint64_t,std::uint64_t> alias_edges{{0x10017,0x1000a},{0x10016,0x10010}};
    require(query(alias,22,alias_edges,root,1)==2);
    auto mismatch=alias;mismatch[15]=15;
    require(!query(mismatch,22,alias_edges,root,1)); // Guard masked off a bit the query still reads.
    auto overwritten=alias;overwritten.insert(overwritten.begin()+4,{0xff,0xc1}); // INC ECX after the copy.
    require(!query(overwritten,24,{{0x10019,0x1000c},{0x10018,0x10012}},root,1));
    const std::array<std::uint64_t,2> alias_entry{0x10000,0x10007};
    require(!query(alias,22,alias_edges,alias_entry,1));
    require(query(original,13,edges,root)==2);
    auto flag_gap=original;flag_gap.insert(flag_gap.begin()+5,{0x89,0xd9}); // MOV ECX,EBX preserves flags.
    const std::multimap<std::uint64_t,std::uint64_t> gap_edges{{0x10010,0x10007},{0x1000f,0x10009}};
    require(query(flag_gap,15,gap_edges,root)==2);
    auto changed_register=flag_gap;changed_register[6]=0xd8; // MOV EAX,EBX invalidates the compared value.
    require(!query(changed_register,15,gap_edges,root));
    auto changed_flags=original;changed_flags.insert(changed_flags.begin()+5,{0xff,0xc1}); // INC ECX writes ZF.
    require(!query(changed_flags,15,gap_edges,root));
    changed_flags[7]=0x73; // JAE needs CF only; INC preserves it.
    require(query(changed_flags,15,gap_edges,root)==1);
    const std::array<std::uint64_t,2> inside_flags{0x10000,0x10005};
    require(!query(flag_gap,15,gap_edges,inside_flags));
    const std::array<std::uint64_t,2> at_guard{0x10000,0x10005};
    require(!query(original,13,edges,at_guard));
    const std::array<std::uint64_t,2> at_read{0x10000,0x1000d};
    require(!query(original,13,edges,at_read));
    auto both_edges=original;both_edges[6]=0; // Taken and fallthrough both reach PC7.
    require(!query(both_edges,13,{{0x10007,0x10005},{0x1000d,0x10007}},root));
    auto taken=original;taken[6]=6;taken[8]=5;
    require(!query(taken,13,{{0x1000d,0x10005},{0x1000e,0x10007}},root));
    auto below=taken;below[5]=0x76; // JBE taken means EAX <= 1.
    require(query(below,13,{{0x1000d,0x10005},{0x1000e,0x10007}},root)==2);
    below[5]=0x72; // JB taken means EAX < 1.
    require(query(below,13,{{0x1000d,0x10005},{0x1000e,0x10007}},root)==1);
    auto unbounded=original;unbounded[5]=0x76;
    require(!query(unbounded,13,edges,root)); // JBE fallthrough supplies a lower bound only.
    auto joined=both_edges;joined[5]=0x76;
    require(!query(joined,13,{{0x10007,0x10005},{0x1000d,0x10007}},root));
    require(!query(below,13,{{0x1000d,0x10005},{0x1000e,0x10007}},at_guard));
    auto changed=original;changed.insert(changed.begin()+7,{0xff,0xc0});changed[6]+=2; // INC EAX.
    require(!query(changed,15,{{0x10010,0x10005},{0x1000f,0x10009}},root));
    // A branch entering the JA directly must not borrow the preceding CMP.
    auto bypass=original;bypass.insert(bypass.begin(),{0x75,5});
    require(!query(bypass,15,{{0x10007,0x10000},{0x10010,0x10007},{0x1000f,0x10009}},root));
    // A 32-bit guard cannot bound a 64-bit index with unknown high bits.
    auto high=original;high[0]=0x48;high.insert(high.begin()+1,0x89);high[2]=0xf8;
    require(!query(high,14,{{0x1000f,0x10006},{0x1000e,0x10008}},root));
    // An unchanged index can circulate through a loop after its guard.
    auto loop=original;loop[6]=9;loop[13]=0x75;loop[14]=0xf8;loop.insert(loop.end(),{0xc3,0xc3});
    require(query(loop,13,{{0x10010,0x10005},{0x1000d,0x10007},{0x10007,0x1000d}},root)==2);
    // Independent bounded incoming paths merge conservatively with max, not min.
    auto merged=original;
    merged[8]=19; // JMP common RET at 28.
    merged.insert(merged.end(),original.begin(),original.end());
    merged[15+4]=3; // The second root's guard admits four values.
    const std::array<std::uint64_t,2> two_roots{0x10000,0x1000f};
    require(query(merged,28,{{0x1000e,0x10005},{0x1001c,0x10007},
        {0x1001d,0x10014},{0x1001c,0x10016}},two_roots)==4);
    auto call=original;call.insert(call.begin()+7,{0xe8,7,0,0,0});call[6]+=5;
    require(!query(call,18,{{0x10013,0x10005},{0x10012,0x1000c}},root));
    const std::vector<std::uint8_t> saved{0x41,0x89,0xfc,0x41,0x83,0xfc,1,0x77,12,
        0xe8,7,0,0,0,0xeb,4,0xff,0xff,0xff,0xff,0xc3,0xc3};
    require(query(saved,20,{{0x10015,0x10007},{0x10014,0x1000e}},root,12)==2);
    const std::vector<std::uint8_t> flags_call{0x41,0x89,0xfc,0x41,0x83,0xfc,1,
        0xe8,9,0,0,0,0x77,7,0xeb,4,0xff,0xff,0xff,0xff,0xc3,0xc3};
    const std::multimap<std::uint64_t,std::uint64_t> flags_call_edges{{0x10015,0x1000c},{0x10014,0x1000e}};
    require(!query(flags_call,20,flags_call_edges,root,12)); // Call preserves R12 but not comparison flags.
    auto undefined_flags=flags_call;
    undefined_flags[7]=0xf7;undefined_flags[8]=0xf1; // DIV ECX leaves used flags undefined.
    for(unsigned i=9;i<12;++i) undefined_flags[i]=0x90;
    require(!query(undefined_flags,20,flags_call_edges,root,12));
    auto partial=original;partial.insert(partial.begin()+7,{0xb0,0xff});partial[6]+=2; // MOV AL,255.
    require(!query(partial,15,{{0x10010,0x10005},{0x1000f,0x10009}},root));
}

std::vector<std::uint8_t> cfg_switch_fixture(bool invalidating_case=false) {
    std::vector<std::uint8_t> code{0x89,0xf8,0x83,0xf8,1,0x77,26,0xeb,8};
    code.insert(code.end(),8,0xff);
    code.insert(code.end(),{0x48,0x8d,0x0d,0,0,0,0,0x48,0x63,0x04,0x81,0x48,0x01,0xc8,0xff,0xe0,0xc3});
    const auto table=code.size();code.resize(table+8);
    const auto first=code.size();
    if(!invalidating_case) code.insert(code.end(),{0x64,0x48,0x8b,4,0x25,0,0,0,0,0xc3});
    else {
        code.insert(code.end(),{0x48,0x89,0xf8,0xe9,0,0,0,0}); // Unknown full-width RDI -> RAX; loop to LEA.
        const auto delta=std::uint32_t(17-first-8);
        for(unsigned i=0;i<4;++i) code[first+4+i]=static_cast<std::uint8_t>(delta>>(8*i));
    }
    const auto second=code.size();code.push_back(0xc3);
    for(unsigned i=0;i<4;++i) {
        code[20+i]=static_cast<std::uint8_t>((table-24)>>(8*i));
        code[table+i]=static_cast<std::uint8_t>((first-table)>>(8*i));
        code[table+4+i]=static_cast<std::uint8_t>((second-table)>>(8*i));
    }
    return code;
}

void cfg_switch_tests() {
    const std::array<std::uint64_t,1> root{0x10000};
    const auto code=cfg_switch_fixture();
    const auto a=analyze(code,root);
    require(a.switch_tables.size()==1 && a.switch_tables[0].invariant_index.has_value() &&
        a.switch_tables[0].invariant_base.has_value() && a.switch_tables[0].table_size==8);
    require(GuestTls::inspect(code,a.instructions).sites.size()==1);
    auto context_move=code;context_move.insert(context_move.begin()+31,{0x48,0x8b,0x1f}); // MOV RBX,[RDI].
    context_move[6]+=3;context_move[20]+=3;
    const auto context_graph=analyze(context_move,root);
    require(context_graph.switch_tables.size()==1 && context_graph.switch_tables[0].invariant_index.has_value());
    require(GuestTls::inspect(context_move,context_graph.instructions).sites.size()==1);
    auto clobbered=context_move;clobbered[33]=0x07; // MOV RAX,[RDI] destroys the target.
    require(analyze(clobbered,root).switch_tables.empty());
    auto stored=context_move;stored[32]=0x89;stored[33]=3; // MOV [RBX],RAX is not a context move.
    require(analyze(stored,root).switch_tables.empty());
    auto copied_target=code;
    copied_target.insert(copied_target.begin()+31,{0x48,0x89,0xc2,0x48,0x8b,0x07});
    copied_target[6]+=6;copied_target[20]+=6;copied_target[38]=0xe2; // JMP RDX after copy, then RAX clobber.
    require(analyze(copied_target,root).switch_tables.size()==1);
    const std::array<std::uint64_t,2> mid_target{0x10000,0x1001f};
    require(analyze(copied_target,mid_target).switch_tables.empty());
    auto scheduled=code;scheduled.insert(scheduled.begin()+5,{0x89,0xd9});
    const auto scheduled_graph=analyze(scheduled,root);
    require(scheduled_graph.switch_tables.size()==1 && scheduled_graph.switch_tables[0].table_size==8 &&
        scheduled_graph.switch_tables[0].invariant_index.has_value());
    require(GuestTls::inspect(scheduled,scheduled_graph.instructions).sites.size()==1);
    auto masked=code;
    for(unsigned i=2;i<7;++i) masked[i]=0x90; // Remove CMP+JA.
    masked.insert(masked.begin()+2,{0x48,0x83,0xe0,1});
    const auto mask_graph=analyze(masked,root);
    require(mask_graph.switch_tables.empty()); // A mask alone is not a guarded domain.
    // A comparison of a masked copy also bounds the same masked source used
    // later by a dispatch. The two registers must denote the same value.
    std::vector<std::uint8_t> correlated{0x89,0xf9,0x89,0xc8,0x83,0xe0,7,0x83,0xf8,1,
        0x77,26,0x48,0x83,0xe1,7,0xeb,4,0xff,0xff,0xff,0xff,
        0x48,0x8d,0x05,10,0,0,0,0x48,0x63,0x0c,0x88,0x48,0x01,0xc1,0xff,0xe1,0xc3,
        8,0,0,0,18,0,0,0,0x64,0x48,0x8b,4,0x25,0,0,0,0,0xc3,0xc3};
    const auto copied=analyze(correlated,root);
    require(copied.switch_tables.size()==1 && copied.switch_tables[0].table_size==8 &&
        copied.switch_tables[0].invariant_index.has_value());
    require(GuestTls::inspect(correlated,copied.instructions).sites.size()==1);
    correlated[15]=15;
    require(analyze(correlated,root).switch_tables.empty());
    for(const bool inclusive:{false,true}) {
        auto below=code;below[4]=inclusive?1:2;below[5]=inclusive?0x76:0x72;
        below[6]=10;below[8]=24; // Taken -> LEA, fallthrough -> default RET.
        const auto branch=analyze(below,root);
        require(branch.switch_tables.size()==1 && branch.switch_tables[0].table_size==8 &&
            branch.switch_tables[0].invariant_index.has_value());
        require(GuestTls::inspect(below,branch.instructions).sites.size()==1);
    }
    const std::array<std::uint64_t,2> bypass{0x10000,0x10011};
    require(analyze(code,bypass).switch_tables.empty());
    require(analyze(cfg_switch_fixture(true),root).switch_tables.empty());
    // A coarse bound is insufficient when its whole domain is not a table.
    // Preserve the unresolved dispatch instead of classifying adjacent bytes.
    auto coarse=code;coarse[4]=150;
    const auto unresolved=analyze(coarse,root);
    require(unresolved.switch_tables.empty() && unresolved.unresolved.size()==1 &&
            unresolved.unresolved[0].kind==GuestCode::ExitKind::IndirectJump);
}

void repeated_guard_tests() {
    const std::array<std::uint64_t,1> root{0x10000};
    auto code=switch_fixture();
    // Two adjacent JA instructions see the same flags. The second can have a
    // distinct destination: it is never taken after the first falls through.
    code.insert(code.begin()+7,{0x77,16});
    code[6]+=2;
    code[8]=static_cast<std::uint8_t>(code.size()-1-9); // Distinct final RET.
    require(analyze(code,root).switch_tables.size()==1);
    require(GuestTls::inspect(code,analyze(code,root).instructions).sites.size()==1);
    auto different=code;different[7]=0x73; // JAE is not redundant after JA.
    // The local redundant-guard proof cannot handle JAE. The CFG bound can
    // use the same CMP flags through JA, then JAE narrows the index to zero.
    const auto narrowed=analyze(different,root);
    require(narrowed.switch_tables.size()==1 && narrowed.switch_tables[0].invariant_index.has_value() &&
            narrowed.switch_tables[0].table_size==4);
    // An entry directly at the duplicate guard bypasses the proven compare.
    const std::array<std::uint64_t,2> bypass{0x10000,0x10007};
    require(analyze(code,bypass).switch_tables.empty());
    // A flag change cannot be ignored as a redundant guard, but does not
    // destroy an index bound already established on the earlier fallthrough.
    auto changed=code;changed.insert(changed.begin()+7,0xf8); // CLC.
    changed[6]+=1;
    const auto flags=analyze(changed,root);
    require(flags.switch_tables.size()==1 && flags.switch_tables[0].invariant_index.has_value());
    const auto local_refuses=[&](const auto& input,const auto& graph) {
        std::vector<GuestTls::CodeRange> tail;
        for(const auto& r:graph.instructions)
            if(r.address<=graph.switch_tables[0].dispatch_address) tail.push_back(r);
        const std::array<GuestTls::CodeRange,1> ranges{{{0,0x10000,input.size()}}};
        require(!GuestCode::Detail::recognize_switch(input,ranges,tail,{}));
    };
    local_refuses(different,narrowed);
    local_refuses(changed,flags);
    // A local LEA before a call is not part of the index guard. The separate
    // CFG proof must establish the callee-saved base across that call.
    std::vector<std::uint8_t> across_call{0x4c,0x8d,0x3d,0,0,0,0,0xe8,0,0,0,0,
        0x89,0xf8,0x83,0xf8,1,0x77,11,0x49,0x63,0x04,0x87,0x4c,0x01,0xf8,0xff,0xe0,0xc3,0xc3};
    // JA targets the default RET at 28, not the helper RET at 29.
    across_call[18]=9;
    across_call[8]=17; // Call helper at 29 from PC12.
    const auto table=across_call.size();across_call.resize(table+8);
    const auto first=across_call.size();across_call.push_back(0xc3);
    const auto second=across_call.size();across_call.push_back(0xc3);
    for(unsigned i=0;i<4;++i) {
        across_call[3+i]=static_cast<std::uint8_t>((table-7)>>(8*i));
        across_call[table+i]=static_cast<std::uint8_t>((first-table)>>(8*i));
        across_call[table+4+i]=static_cast<std::uint8_t>((second-table)>>(8*i));
    }
    const auto graph=analyze(across_call,root);
    require(graph.switch_tables.size()==1 && graph.switch_tables[0].invariant_base.has_value());
    // Starting after the LEA destroys the invariant, even if the contiguous
    // backward instruction list still happens to contain that LEA.
    const std::array<std::uint64_t,2> after_lea{0x10000,0x10007};
    require(analyze(across_call,after_lea).switch_tables.empty());
}

void census_tests() {
    // Operand-size/address-size/REX prefixes can precede FS. Starting only at
    // 0x64 would lose the actual entry and can change operand/address width.
    const std::vector<std::uint8_t> code{0xc3,0x66,0x64,0x48,0x8b,0x04,0x25,0,0,0,0,
        0x67,0x64,0x48,0x8b,0x00,0x48,0x64,0x8b,0x00,
        0x64,0x48,0x8d,0x00,0x64,0x0f,0x1f,0x00,0x64,0xa4,0x64,0xc3,0x64};
    const std::array<GuestTls::CodeRange,1> ranges{{{0,0x10000,code.size()}}};
    const auto candidates=GuestCode::fs_candidates(code,ranges,hash(code));
    const auto kind_at=[&](unsigned offset, GuestCode::FsCandidateKind kind) {
        for (const auto& c:candidates) if(c.bytes.address==0x10000+offset) {
            require(c.bytes.file_offset==offset && c.kind==kind);
            return;
        }
        require(false);
    };
    using Kind=GuestCode::FsCandidateKind;
    for(unsigned offset:{1,2,11,12,16,17,28}) kind_at(offset,Kind::MemoryAccess);
    kind_at(20,Kind::AddressOnly);
    kind_at(24,Kind::AddressOnly);
    kind_at(30,Kind::OtherPrefix);
    kind_at(32,Kind::Undecodable);
    rejects([&]{GuestCode::fs_candidates(code,ranges,std::string(64,'0'));},"SHA-256 mismatch");
    rejects([&]{GuestCode::fs_candidates(code,ranges,hash(code),1);},"limit exceeded");
    rejects([&]{GuestCode::fs_candidates(code,ranges,hash(code),0);},"bounded candidate limit");
    const std::array<GuestTls::CodeRange,2> overlap{{ranges[0],ranges[0]}};
    rejects([&]{GuestCode::fs_candidates(code,overlap,hash(code));},"overlapping");
    auto outside=ranges;outside[0].size+=1;
    rejects([&]{GuestCode::fs_candidates(code,outside,hash(code));},"invalid");
    // Never concatenate mappings to finish a truncated prefix/instruction.
    const std::array<std::uint8_t,3> split{0x64,0x8b,0x00};
    const std::array<GuestTls::CodeRange,2> mappings{{{0,0x10000,1},{1,0x20000,2}}};
    const auto truncated=GuestCode::fs_candidates(split,mappings,hash(split));
    require(truncated.size()==1 && truncated[0].kind==Kind::Undecodable && truncated[0].bytes.size==1);
    // FS is a source override on string instructions (hidden operands), but a
    // later GS override does not access FS. Both still appear in the census.
    const std::array<std::uint8_t,4> overridden{0x64,0x65,0x8b,0x00};
    const std::array<GuestTls::CodeRange,1> overridden_range{{{0,0x10000,4}}};
    const auto other=GuestCode::fs_candidates(overridden,overridden_range,hash(overridden));
    require(other.size()==1 && other[0].kind==Kind::OtherPrefix);
}

int main() try {
    cfg_bound_tests();
    cfg_switch_tests();
    census_tests();
    repeated_guard_tests();
    const std::array<std::uint64_t,1> root{0x10000};
    // Jump over undecodable inline data, then execute a guest FS load and RET.
    const std::vector<std::uint8_t> code{0xeb,4,0xff,0xff,0xff,0xff,
                                      0x64,0x48,0x8b,4,0x25,0,0,0,0,0xc3};
    const auto result = analyze(code,root);
    require(result.instructions.size()==3 && result.instructions[1].address==0x10006 && result.unresolved.empty());
    const auto manifest = GuestTls::inspect(code,result.instructions);
    require(manifest.sites.size()==1 && manifest.sites[0].address==0x10006);
    const std::array<GuestTls::CodeRange,1> whole{{{0,0x10000,code.size()}}};
    rejects([&] { GuestTls::inspect(code,whole); },"decode");
    rejects([&] { GuestCode::discover(code,whole,root,std::string(64,'0')); },"SHA-256 mismatch");
    rejects([&] { analyze(code,root,1); },"limit");
    rejects([&] { analyze(code,std::array<std::uint64_t,1>{0x20000}); },"root outside");
    rejects([&] { analyze(code,std::array<std::uint64_t,1>{0x10002}); },"decode reachable");
    // Branch to the middle of an instruction: refused regardless of discovery order.
    const std::vector<std::uint8_t> overlap{0x75,1,0x48,0x89,0xc0,0xc3};
    rejects([&] { analyze(overlap,root); },"interior");
    const std::vector<std::uint8_t> reverse_overlap{0x75,2,0xeb,1,0x48,0x89,0xc0,0xc3};
    rejects([&] { analyze(reverse_overlap,root); },"overlap");
    // Returns stop before data; loops and duplicate roots terminate deterministically.
    const std::vector<std::uint8_t> stop{0xc3,0xff};
    require(analyze(stop,root).instructions.size()==1);
    const std::vector<std::uint8_t> loop{0xeb,0xfe};
    require(analyze(loop,std::array<std::uint64_t,2>{0x10000,0x10000}).instructions.size()==1);
    const std::vector<std::uint8_t> cond{0x75,1,0xc3,0xc3};
    require(analyze(cond,root).instructions.size()==3);
    // A call explores its target and its continuation, including a different range.
    const std::vector<std::uint8_t> call{0xe8,1,0,0,0,0xc3,0xc3};
    require(analyze(call,root).instructions.size()==3);
    const std::array<GuestTls::CodeRange,2> separated{{{0,0x10000,6},{6,0x10006,1}}};
    require(GuestCode::discover(call,separated,root,hash(call)).instructions.size()==3);
    // Indirect jumps are unresolved and terminal; indirect calls retain fallthrough.
    const std::vector<std::uint8_t> ijump{0xff,0xe0,0xff};
    const auto indirect = analyze(ijump,root);
    require(indirect.instructions.size()==1 && indirect.unresolved.size()==1 &&
            indirect.unresolved[0].kind==GuestCode::ExitKind::IndirectJump);
    const std::vector<std::uint8_t> icall{0xff,0xd0,0xc3};
    const auto indirect_call = analyze(icall,root);
    require(indirect_call.instructions.size()==2 && indirect_call.unresolved[0].kind==GuestCode::ExitKind::IndirectCall);
    const std::vector<std::uint8_t> outside{0xe9,0,1,0,0};
    require(analyze(outside,root).unresolved[0].kind==GuestCode::ExitKind::ExternalBranch);
    const std::vector<std::uint8_t> ud2{0x0f,0x0b,0xff};
    const auto trap = analyze(ud2,root);
    require(trap.instructions.size()==1 && trap.unresolved[0].kind==GuestCode::ExitKind::Trap);
    // Explicit metadata-backed noreturn evidence prevents a fictitious return
    // into data, but stale thunk bytes refuse before discovery begins.
    const std::vector<std::uint8_t> terminating{0xe8,2,0,0,0,0xff,0xff,0x0f,0x0b};
    const std::array<GuestTls::CodeRange,1> terminating_range{{{0,0x10000,terminating.size()}}};
    const std::array<GuestCode::NoReturnTarget,1> no_return{{{0x10007,{0x0f,0x0b}}}};
    rejects([&] { analyze(terminating,root); },"decode reachable");
    require(GuestCode::discover(terminating,terminating_range,root,hash(terminating),100,no_return).instructions.size()==2);
    auto stale = no_return; stale[0].expected_bytes[0] ^= 1;
    rejects([&] { GuestCode::discover(terminating,terminating_range,root,hash(terminating),100,stale); },"bytes mismatch");
    // Fallthrough at the mapping end remains an unresolved edge.
    const std::vector<std::uint8_t> tail{0x90};
    require(analyze(tail,root).unresolved[0].target==0x10001);
    switch_tests();
    constant_tests();
    std::cout << "guest control-flow evidence and strict refusal tests passed\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }

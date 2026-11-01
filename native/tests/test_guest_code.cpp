// SPDX-License-Identifier: GPL-3.0-or-later
#include "guest_code.hpp"
#include <openssl/evp.h>
#include <array>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

void require(bool ok) { if (!ok) throw std::runtime_error("guest code assertion failed"); }
template<class F> void rejects(F action, const char* expected) {
    bool rejected = false;
    try { action(); } catch (const std::runtime_error& e) { rejected = std::string(e.what()).find(expected) != std::string::npos; }
    require(rejected);
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
int main() try {
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
    std::cout << "guest control-flow evidence and strict refusal tests passed\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }

// SPDX-License-Identifier: GPL-3.0-or-later
#include "../trap_frame_policy.hpp"
#include "../trap_ui_gate.hpp"
#include "../trap_movie_gate.hpp"
#include <map>
#include <stdexcept>
#include <vector>
int main() {
    auto check=[](bool ok){if(!ok)throw std::runtime_error("Trap Team frame policy contract");};
    TrapFramePolicy::Upshift upshift;
    check(upshift.apply(60,1000)==30);check(upshift.apply(60,500999)==30);
    check(upshift.apply(60,501000)==60);check(upshift.apply(30,501001)==30);
    check(upshift.apply(60,501002)==60); // verified world resumes without a timer
    check(upshift.apply(60,501003,1)==30); // new world must qualify again
    check(upshift.apply(30,501004,1)==30);
    check(upshift.apply(60,501005,1)==30);
    TrapFramePolicy::State state;
    TrapFramePolicy::Gates gates;gates.cutscenes_valid=true;gates.control_valid=true;gates.control_ready=true;
    auto event=[&](unsigned kind,const char* name) {LevelProtocol::Event e;e.kind=kind;std::strcpy(e.name.data(),name);state.consume(e);};
    check(state.decide(gates).fps==30);
    event(3,"Level_313_Tutorial");check(state.decide(gates).phase=="loading");
    event(2,"level0/Level_313_Tutorial");check(state.decide(gates).fps==60);
    // Hat streaming must not introduce a 30 FPS frame into active gameplay.
    // It cannot bypass uncertain UI, portal, pause, cutscene or world gates.
    const auto hat_generation=state.generation();
    event(3,"outfit/Hat_202");check(state.decide(gates).phase=="gameplay");
    check(state.generation()==hat_generation);
    gates.control_valid=false;check(state.decide(gates).fps==30);gates.control_valid=true;
    gates.control_ready=false;check(state.decide(gates).fps==30);gates.control_ready=true;
    gates.pause_ui=true;check(state.decide(gates).fps==30);gates.pause_ui=false;
    gates.cutscenes=1;check(state.decide(gates).fps==30);gates.cutscenes=0;
    gates.cutscenes_valid=false;check(state.decide(gates).fps==30);gates.cutscenes_valid=true;
    event(2,"outfit0/Hat_202");check(state.decide(gates).fps==60);
    event(3,"outfit/Hat_unknown");check(state.decide(gates).phase=="loading");
    event(2,"outfit0/Hat_unknown");
    event(3,"character/006_dinorang");check(state.decide(gates).phase=="loading");
    event(2,"character0/006_dinorang");
    event(3,"Level_313_Tutorial");event(3,"outfit/Hat_202");
    check(state.decide(gates).fps==30);
    event(2,"level0/Level_313_Tutorial");check(state.decide(gates).fps==60);
    event(2,"outfit0/Hat_202");check(state.decide(gates).fps==60);
    gates.control_ready=false;check(state.decide(gates).phase=="portal");
    gates.control_ready=true;gates.cutscenes=2;check(state.decide(gates).phase=="cutscene");
    gates.cutscenes=0;event(3,"misc/ui_pausemenu_streamed");check(state.decide(gates).fps==30);
    event(2,"misc0/ui_pausemenu_streamed");check(state.decide(gates).phase=="pause");
    event(3,"misc/");
    gates.pause_ui=true;check(state.decide(gates).fps==30);
    gates.pause_ui=false;check(state.decide(gates).fps==60);
    event(2,"misc0/");check(state.decide(gates).fps==60);
    gates.pc_menu=true;check(state.decide(gates).fps==60);
    gates.pause_ui=true;check(state.decide(gates).phase=="pause");gates.pause_ui=false;
    gates.control_ready=false;check(state.decide(gates).phase=="portal");gates.control_ready=true;
    gates.cutscenes=1;check(state.decide(gates).phase=="cutscene");gates.cutscenes=0;
    gates.movies_valid=true;gates.cutscenes=1;
    check(state.decide(gates).fps==60 && state.decide(gates).phase=="realtime-cinematic");
    gates.movies=1;check(state.decide(gates).fps==30 && state.decide(gates).phase=="video");
    gates.movies=0;gates.cutscenes=0;gates.control_ready=false;
    check(state.decide(gates).fps==60 && state.decide(gates).phase=="realtime-cinematic");
    gates.portal_ui=true;check(state.decide(gates).fps==30);
    gates.control_ready=true;gates.cutscenes=1;
    gates.portal_ui=false;gates.control_valid=false;check(state.decide(gates).fps==30);
    gates.control_valid=true;gates.movies_valid=false;check(state.decide(gates).fps==30);
    gates.cutscenes=0;
    gates.pc_menu=false;
    gates.control_valid=false;check(state.decide(gates).fps==30);gates.control_valid=true;
    state.lost();check(state.decide(gates).fps==30);
    event(2,"character1/006_dinorang");check(state.decide(gates).fps==30);
    event(2,"level0/Level_313_Tutorial");check(state.decide(gates).fps==60);
    event(3,"level/Title");gates.pc_menu=true;check(state.decide(gates).phase=="loading");
    event(2,"level0/Title");check(state.decide(gates).fps==30);gates.pc_menu=false;
    // A synthetic guest directory exercises relocation, type/name corroboration,
    // visibility bit interpretation and stale/unreadable object rejection.
    std::map<std::uintptr_t,unsigned char> memory;
    auto write=[&](std::uintptr_t p,auto value) {auto* b=reinterpret_cast<unsigned char*>(&value);for(unsigned i=0;i<sizeof(value);++i)memory[p+i]=b[i];};
    auto read=[&](std::uintptr_t p,void* out,std::size_t n) {for(unsigned i=0;i<n;++i){auto it=memory.find(p+i);if(it==memory.end())return false;static_cast<unsigned char*>(out)[i]=it->second;}return true;};
    auto word=[&](std::uintptr_t p,std::uintptr_t v){write(p,v);};
    word(0x1039d40,0x2000);word(0x2000,0xf5d700);word(0x2000+296,0x3000);
    word(0x3000,0xf86cd0);word(0x3000+40,0x4000);word(0x4000,0xf798b0);
    write(0x4000+12,std::uint32_t{311});write(0x4000+16,std::uint32_t{311});word(0x4000+32,0x5000);
    const unsigned indices[]{284,287,310};const char* names[]{"_Gameplay_Container","_UI_PauseContainer","PortalUI_Container"};
    for(unsigned i=0;i<3;++i) {
        const auto p=0x8000+i*0x1000,n=p+512;word(0x5000+indices[i]*8,p);word(p,0xf378b0);word(p+16,n);
        for(unsigned j=0;j<32;++j)memory[n+j]=j<std::strlen(names[i])?names[i][j]:0;
        write(p+244,std::uint32_t{i?0u:1u<<16});
    }
    auto ui=TrapUiGate::sample(read);check(ui.valid && ui.gameplay && !ui.pause && !ui.portal);
    write(0x8000+244,std::uint32_t{0});write(0x9000+244,std::uint32_t{1u<<16});
    ui=TrapUiGate::sample(read);check(ui.valid && !ui.gameplay && ui.pause);
    memory[0x8200]='?';check(!TrapUiGate::sample(read).valid);
    memory.erase(0x1039d40);check(!TrapUiGate::sample(read).valid);
    memory.clear();
    word(0x10a0a30,0x2000);word(0x10876f8,0x3000);write(0x3000+128,std::int16_t{2});
    word(0x2000+104,0x4000);write(0x4000+12,std::uint32_t{3});write(0x4000+16,std::uint32_t{3});word(0x4000+32,0x5000);
    word(0x5000+16,0x6000);word(0x6000+16,0x7000);word(0x7000+40,0x8000);
    write(0x8000+12,std::uint32_t{0});write(0x8000+16,std::uint32_t{8});word(0x8000+32,0x9000);
    auto movie=TrapMovieGate::sample(read);check(movie.valid && movie.count==0);
    write(0x8000+12,std::uint32_t{1});movie=TrapMovieGate::sample(read);check(movie.valid && movie.count==1);
    write(0x8000+12,std::uint32_t{9});check(!TrapMovieGate::sample(read).valid);
    write(0x8000+12,std::uint32_t{1});word(0x8000+32,0);check(!TrapMovieGate::sample(read).valid);
    word(0x8000+32,0x9000);write(0x3000+128,std::int16_t{-1});check(!TrapMovieGate::sample(read).valid);
    memory.clear();check(!TrapMovieGate::sample(read).valid);
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "../trap_team_probe.hpp"
#include <stdexcept>
int main() {
    const auto check=[](bool value) {if(!value)throw std::runtime_error("probe safety contract failed");};
    std::array<unsigned char,8> input{1,2,3,4,5,6,7,8}, output{};
    check(TrapTeamProbe::read(reinterpret_cast<std::uintptr_t>(input.data()),output.data(),output.size()));
    check(output==input);
    check(!TrapTeamProbe::read(1,output.data(),output.size()));
    check(TrapTeamProbe::field<std::uint32_t>(input,0)==0x04030201);
    check(TrapTeamProbe::field<std::uint32_t>(input,7)==0);
    check(TrapTeamProbe::hex(input)=="0102030405060708");
    check(TrapTeamProbe::timestamp()>0);
    std::array<unsigned char,40> stack{};
    const auto put=[&](std::size_t offset,auto value) {std::memcpy(stack.data()+offset,&value,sizeof(value));};
    const auto address=reinterpret_cast<std::uintptr_t>(stack.data());
    check(TrapTeamProbe::pause_stack(address).valid);
    check(TrapTeamProbe::pause_stack(address).depth==0);
    std::array<std::uint32_t,2> tokens{7,10};
    put(12,std::uint32_t{2});put(16,std::uint32_t{2});
    put(32,reinterpret_cast<std::uintptr_t>(tokens.data()));
    auto state=TrapTeamProbe::pause_stack(address);
    check(state.valid && state.depth==2 && state.token==10);
    put(12,std::uint32_t{3});check(!TrapTeamProbe::pause_stack(address).valid);
    put(12,std::uint32_t{1});put(32,std::uintptr_t{1});
    check(!TrapTeamProbe::pause_stack(address).valid);
    put(16,std::uint32_t{257});check(!TrapTeamProbe::pause_stack(address).valid);
    check(!TrapTeamProbe::pause_stack(1).valid);
    std::array<unsigned char,112> directory{};
    std::array<unsigned char,136> type{};
    std::array<unsigned char,40> list{};
    std::array<std::uintptr_t,2> objects{1,0x1234};
    const auto pointer=[](auto& value) {return reinterpret_cast<std::uintptr_t>(value.data());};
    const auto store=[](auto& buffer,unsigned offset,auto value) {std::memcpy(buffer.data()+offset,&value,sizeof(value));};
    store(directory,104,pointer(list));store(type,128,std::int16_t{1});
    store(list,12,std::uint32_t{2});store(list,32,pointer(objects));
    check(TrapTeamProbe::service(pointer(directory),pointer(type))==0x1234);
    store(type,128,std::int16_t{-1});check(!TrapTeamProbe::service(pointer(directory),pointer(type)));
    store(type,128,std::int16_t{2});check(!TrapTeamProbe::service(pointer(directory),pointer(type)));
    store(list,12,std::uint32_t{4097});check(!TrapTeamProbe::service(pointer(directory),pointer(type)));
    check(!TrapTeamProbe::service(1,1));
    std::array<unsigned char,72> core{};
    std::array<unsigned char,24> updater{};
    std::array<unsigned char,88> manager{};
    std::array<unsigned char,40> updater_list{},groups{},placements{};
    std::array<unsigned char,116> player_one{},player_two{};
    std::array<std::uintptr_t,1> updater_entries{pointer(manager)},group_entries{pointer(placements)};
    std::array<std::uintptr_t,2> placement_entries{pointer(player_one),pointer(player_two)};
    const auto make_list=[&](auto& data,auto& entries) {
        store(data,12,std::uint32_t(entries.size()));store(data,16,std::uint32_t(entries.size()));
        store(data,32,pointer(entries));
    };
    make_list(updater_list,updater_entries);make_list(groups,group_entries);make_list(placements,placement_entries);
    store(core,64,pointer(updater));store(updater,16,pointer(updater_list));
    store(manager,0,std::uintptr_t{0xf36e00});store(manager,16,pointer(groups));
    store(player_one,112,std::uint32_t{0});store(player_two,112,std::uint32_t{1});
    check(TrapTeamProbe::activity_manager(pointer(core))==pointer(manager));
    auto player=TrapTeamProbe::players(pointer(manager));check(player.valid && player.count==1);
    store(player_two,112,std::uint32_t{0});
    player=TrapTeamProbe::players(pointer(manager));check(player.valid && player.count==2);
    store(player_one,112,std::uint32_t{1});store(player_two,112,std::uint32_t{1});
    player=TrapTeamProbe::players(pointer(manager));check(player.valid && player.count==0);
    store(placements,12,std::uint32_t{4097});check(!TrapTeamProbe::players(pointer(manager)).valid);
    store(manager,0,std::uintptr_t{0xf36e08});check(!TrapTeamProbe::activity_manager(pointer(core)));
    check(!TrapTeamProbe::activity_manager(1));check(!TrapTeamProbe::players(1).valid);

}

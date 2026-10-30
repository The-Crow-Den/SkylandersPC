// SPDX-License-Identifier: MPL-2.0
#include "runtime/cemu_portal.hpp"
#include <iostream>
#include <filesystem>
#include <fstream>
#include <chrono>
int main() {
  if(!trapteam::cemu_portal_self_test()) {
    std::cerr<<"Cemu portal core regression failed\n";return 1;
  }
  namespace fs=std::filesystem;
  const auto previous=fs::current_path();
  const auto root=fs::temp_directory_path()/("trapteam-figure-test-"+
      std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
  if(!fs::create_directory(root)) return 1;
  struct Cleanup {
    fs::path root,previous;unsigned slot=16;
    ~Cleanup() {if(slot<16) trapteam::cemu_portal_remove_figure(slot);std::error_code ec;fs::current_path(previous,ec);fs::remove_all(root,ec);}
  } cleanup{root,previous};
  fs::current_path(root);
  const auto source=root/"synthetic.sky";
  std::array<std::uint8_t,1024> original{};original[0]=0x42;
  {std::ofstream output(source,std::ios::binary);output.write(reinterpret_cast<const char*>(original.data()),original.size());}
  trapteam::PortalFigure figure;std::string error;
  auto load=[&] {
    if(!trapteam::cemu_portal_load_figure(source,&figure,&error)) {std::cerr<<error<<'\n';return false;}
    cleanup.slot=figure.slot;return true;
  };
  if(!load() || figure.working_copy==source) return 1;
  std::array<std::uint8_t,19> write{'W',static_cast<std::uint8_t>(figure.slot),1};
  std::fill(write.begin()+3,write.end(),0x5a);
  if(!trapteam::cemu_portal_command(write) || trapteam::cemu_portal_read()[0]!='W' ||
      !trapteam::cemu_portal_remove_figure(figure.slot)) return 1;
  cleanup.slot=16;
  std::array<std::uint8_t,1024> source_after{};
  {std::ifstream input(source,std::ios::binary);input.read(reinterpret_cast<char*>(source_after.data()),source_after.size());}
  if(source_after!=original || !load()) return 1;
  const std::array<std::uint8_t,3> query{'Q',static_cast<std::uint8_t>(figure.slot),1};
  if(!trapteam::cemu_portal_command(query)) return 1;
  const auto reply=trapteam::cemu_portal_read();
  if(reply[0]!='Q' || reply[1]!=(0x10|figure.slot) || reply[3]!=0x5a) return 1;
  trapteam::cemu_portal_remove_figure(figure.slot);cleanup.slot=16;
  // Neither a link to the original nor a corrupt source may become writable.
  const auto backup=root/"private-backup.sky";
  fs::rename(figure.working_copy,backup);fs::create_symlink(source,figure.working_copy);
  if(trapteam::cemu_portal_load_figure(source,&figure,&error)) return 1;
  fs::remove(figure.working_copy);fs::create_hard_link(source,figure.working_copy);
  if(trapteam::cemu_portal_load_figure(source,&figure,&error)) return 1;
  fs::remove(figure.working_copy);fs::rename(backup,figure.working_copy);
  {std::ofstream invalid(root/"invalid.sky");invalid<<"not a figure";}
  if(trapteam::cemu_portal_load_figure(root/"invalid.sky",&figure,&error)) return 1;
  std::cout<<"Cemu portal protocol, protected figure import and progress persistence passed\n";
}

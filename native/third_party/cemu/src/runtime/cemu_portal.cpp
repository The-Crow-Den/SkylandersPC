// SPDX-License-Identifier: MPL-2.0
// Host adapter for the supplied Cemu SkylanderUSB implementation.
#include "runtime/cemu_portal.hpp"
#include <algorithm>
#include <fstream>
#include <sstream>
#include <iomanip>
#include "Cafe/OS/libs/nsyshid/Skylander.h"

namespace trapteam {
namespace {unsigned queued_replies=0;}
bool cemu_portal_load_figure(const std::filesystem::path& source,PortalFigure* figure,std::string* error) {
  namespace fs=std::filesystem;
  auto fail=[&](const char* message){if(error) *error=message;return false;};
  std::error_code ec;
  if(!figure || !fs::is_regular_file(source,ec) || ec || fs::file_size(source,ec)!=nsyshid::SKY_FIGURE_SIZE || ec)
    return fail("Figure must be a regular 1024-byte .sky file");
  std::array<std::uint8_t,nsyshid::SKY_FIGURE_SIZE> bytes{};
  std::ifstream original(source,std::ios::binary);
  if(!original.read(reinterpret_cast<char*>(bytes.data()),bytes.size())) return fail("Cannot read figure source");
  // Stable non-security import ID: preserve progress in an existing working
  // copy without overwriting it on each launch or relying on the source name.
  std::uint64_t fingerprint=14695981039346656037ULL;
  for(auto byte:bytes) {fingerprint^=byte;fingerprint*=1099511628211ULL;}
  std::ostringstream name;name<<"import-"<<std::hex<<std::setw(16)<<std::setfill('0')<<fingerprint<<".sky";
  const auto root=fs::current_path(ec)/"out/figures";
  if(ec || fs::weakly_canonical(root,ec)!=root || ec) return fail("Figure directory must not redirect outside the project");
  fs::create_directories(root,ec);if(ec) return fail("Cannot create private figure directory");
  const auto working=root/name.str();
  if(fs::is_symlink(working,ec)) return fail("Refusing a symlinked figure working copy");
  ec.clear();fs::copy_file(source,working,fs::copy_options::skip_existing,ec);
  if(ec || fs::hard_link_count(working,ec)!=1 || ec || fs::file_size(working,ec)!=bytes.size() || ec)
    return fail("Invalid figure working copy");
  fs::permissions(working,fs::perms::owner_read|fs::perms::owner_write,fs::perm_options::add,ec);
  if(ec) return fail("Cannot make the private figure copy writable");
  std::unique_ptr<FileStream> file(FileStream::openFile2(working,true));
  if(!file || file->GetSize()!=bytes.size() || file->readData(bytes.data(),bytes.size())!=bytes.size())
    return fail("Cannot open the figure working copy");
  const auto slot=nsyshid::g_skyportal.LoadSkylander(bytes.data(),std::move(file));
  if(slot>=16) return fail("Cemu virtual portal has no free figure slot");
  *figure={working,slot};return true;
}
bool cemu_portal_remove_figure(unsigned slot) {return slot<16 && nsyshid::g_skyportal.RemoveSkylander(slot);}
bool cemu_portal_command(std::span<const std::uint8_t> bytes) {
  if(bytes.empty() || bytes.size()>64) return false;
  unsigned required=1;bool reply=false;
  switch(bytes[0]) {
    case 'A':case 'M':required=2;reply=true;break;
    case 'C':required=4;break;
    case 'J':required=5;reply=true;break;
    case 'L':required=5;break;
    case 'Q':required=3;reply=true;break;
    case 'W':required=19;reply=true;break;
    case 'R':reply=true;break;
    case 'S':case 'V':break;
    default:return false;
  }
  if(bytes.size()<required || (reply && queued_replies>=256) ||
     ((bytes[0]=='Q' || bytes[0]=='W') && bytes[2]>=nsyshid::SKY_BLOCK_COUNT)) return false;
  std::array<std::uint8_t,64> packet{};
  std::copy(bytes.begin(),bytes.end(),packet.begin());
  nsyshid::g_skyportal.ControlTransfer(packet.data(),bytes.size());
  if(reply) ++queued_replies;
  return true;
}
std::array<std::uint8_t,64> cemu_portal_read() {
  auto result=nsyshid::g_skyportal.GetStatus();
  if(queued_replies) --queued_replies;
  return result;
}
bool cemu_portal_descriptor(unsigned type,unsigned index,unsigned language,std::span<std::uint8_t> output) {
  if(output.empty() || output.size()>4096) return false;
  return nsyshid::SkylanderPortalDescriptor(type,index,language,output.data(),output.size());
}
bool cemu_portal_self_test() {
  const std::array<std::uint8_t,1> reset{'R'},bad{'Q'};
  if(cemu_portal_command(bad) || !cemu_portal_command(reset)) return false;
  const auto response=cemu_portal_read();
  const auto status=cemu_portal_read();
  const std::array<std::uint8_t,3> invalid_block{'Q',0,64};
  std::array<std::uint8_t,41> descriptor{};
  return response[0]=='R' && response[1]==2 && response[2]==0x1b &&
      status[0]=='S' && status[1]==0 && status[2]==0 && status[6]==1 &&
      cemu_portal_descriptor(2,0,0,descriptor) && descriptor[0]==9 && descriptor[3]==41 && descriptor[29]==0x81 &&
      !cemu_portal_command(invalid_block);
}
}

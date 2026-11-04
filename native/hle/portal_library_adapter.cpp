// SPDX-License-Identifier: MPL-2.0
// Adapter to the separately supplied MPL Cemu portal implementation.
#include "Cafe/OS/libs/nsyshid/Skylander.h"
#include <algorithm>
#include <filesystem>
#include <string_view>
#include <vector>
#include "../platform/host_files.hpp"

namespace {
struct Choice {unsigned id,variant;const char* name;};
const std::vector<Choice>& choices() {
    static const auto value=[] {
        std::vector<Choice> result;
        for(const auto& [identity,name]:nsyshid::g_skyportal.GetListSkylanders()) {
            const auto [id,variant]=identity;
            // Characters, Swap Force swapper halves (bottoms 1000-1015, tops
            // 2000-2015) and magic/adventure items through Trap Team. Traps have
            // a separate collection; vehicles require additional placement support.
            const bool character=id<=32 || (id>=100 && id<=115) ||
                id==404 || id==416 || id==419 || id==430 ||
                (id>=450 && id<=485) || (id>=502 && id<=543) ||
                (id>=1000 && id<=1015) || (id>=2000 && id<=2015) || (id>=3000 && id<=3015);
            const bool item=(id>=200 && id<=209) || (id>=230 && id<=233) || (id>=300 && id<=308);
            // SuperChargers vehicles keep their variant decos (0x44xx) as real figures do.
            const bool vehicle=id>=3220 && id<=3299;
            if(((character || item) && variant<0x4000) || vehicle)result.push_back({id,variant,name});
        }
        std::sort(result.begin(),result.end(),[](const Choice& a,const Choice& b) {
            return std::string_view(a.name)<std::string_view(b.name);
        });
        return result;
    }();
    return value;
}
}
extern "C" unsigned sky_portal_creation_count_adapter() {return static_cast<unsigned>(choices().size());}
extern "C" const char* sky_portal_creation_name_adapter(unsigned index) {
    return index<choices().size()?choices()[index].name:"";
}
extern "C" bool sky_portal_creation_identity_adapter(unsigned index,unsigned* id,unsigned* variant) {
    if(index>=choices().size() || !id || !variant)return false;
    *id=choices()[index].id;*variant=choices()[index].variant;return true;
}
extern "C" bool sky_portal_blank_adapter(const char* path,unsigned id,unsigned variant) {
    if(!path || id>65535 || variant>65535)return false;
    // Cemu's factory creates/truncates its output. Keep that operation in a
    // private temporary directory; publish with a hard link, which never overwrites.
    namespace fs=std::filesystem;
    fs::path destination;
    try { destination=SkyHost::path_from_utf8(path); }
    catch(const fs::filesystem_error&) { return false; }
    const auto parent=destination.has_parent_path()?destination.parent_path():fs::path(".");
    fs::path directory;
    if(!SkyHost::create_private_temp_directory(parent,".sky-create-",directory))return false;
    const auto temporary=directory/"figure.sky";
    bool success=false;
    try {
        success=nsyshid::g_skyportal.CreateSkylander(temporary,static_cast<uint16>(id),static_cast<uint16>(variant)) &&
            fs::file_size(temporary)==1024;
        if(success) {
            std::error_code ec;
            fs::create_hard_link(temporary,destination,ec); // Native no-replace publication on either OS.
            success=!ec;
        }
    }catch(...) {success=false;}
    std::error_code ec;fs::remove_all(directory,ec);
    return success;
}
extern "C" const char* sky_portal_name_adapter(unsigned id,unsigned variant) {
    thread_local std::string name;
    name=nsyshid::g_skyportal.FindSkylander(static_cast<uint16>(id),static_cast<uint16>(variant));
    return name.c_str();
}

// SPDX-License-Identifier: MPL-2.0
// Adapter to the separately supplied MPL Cemu portal implementation.
#include "Cafe/OS/libs/nsyshid/Skylander.h"
#include <algorithm>
#include <filesystem>
#include <string_view>
#include <vector>
#include <unistd.h>

namespace {
struct Choice {unsigned id,variant;const char* name;};
const std::vector<Choice>& choices() {
    static const auto value=[] {
        std::vector<Choice> result;
        for(const auto& [identity,name]:nsyshid::g_skyportal.GetListSkylanders()) {
            const auto [id,variant]=identity;
            // Single-tag characters plus magic/adventure items through Trap Team.
            // Traps have a separate collection; swappable halves and vehicles
            // require additional placement support.
            const bool character=id<=32 || (id>=100 && id<=115) ||
                id==404 || id==416 || id==419 || id==430 ||
                (id>=450 && id<=485) || (id>=502 && id<=543) ||
                (id>=3000 && id<=3015);
            const bool item=(id>=200 && id<=209) || (id>=230 && id<=233) || (id>=300 && id<=308);
            if((character || item) && variant<0x4000)result.push_back({id,variant,name});
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
    // private temporary directory; publish with link(), which never overwrites.
    namespace fs=std::filesystem;
    const fs::path destination(path);
    const auto parent=destination.has_parent_path()?destination.parent_path():fs::path(".");
    auto pattern=(parent/".sky-create-XXXXXX").string();
    std::vector<char> writable(pattern.begin(),pattern.end());writable.push_back(0);
    const auto* directory=mkdtemp(writable.data());if(!directory)return false;
    const auto temporary=fs::path(directory)/"figure.sky";
    bool success=false;
    try {
        success=nsyshid::g_skyportal.CreateSkylander(temporary,static_cast<uint16>(id),static_cast<uint16>(variant)) &&
            fs::file_size(temporary)==1024 && ::link(temporary.c_str(),destination.c_str())==0;
    }catch(...) {success=false;}
    std::error_code ec;fs::remove_all(directory,ec);
    return success;
}
extern "C" const char* sky_portal_name_adapter(unsigned id,unsigned variant) {
    thread_local std::string name;
    name=nsyshid::g_skyportal.FindSkylander(static_cast<uint16>(id),static_cast<uint16>(variant));
    return name.c_str();
}

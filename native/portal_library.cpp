// SPDX-License-Identifier: GPL-3.0-or-later
#include "portal_library.hpp"
#include "portal_catalog.hpp"
#include "portal_portraits.hpp"
#include "trap_metadata.hpp"
#include "hle/virtual_portal.hpp"
#include <filesystem>
#include <fstream>
#include <array>
#include <mutex>
#include <vector>
#include <sstream>
#include <iomanip>
#include <unistd.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>

namespace {
namespace fs=std::filesystem;
std::mutex library_mutex;
struct Character {fs::path file;std::string name;unsigned id,variant;};
std::vector<Character> characters,items;
bool is_item(unsigned id) {return (id>=200 && id<=209) || (id>=230 && id<=233) || (id>=300 && id<=308);}
fs::path root;
int selected_character=-1,selected_second=-1,selected_item=-1,selected_trap=-1;
// Bottom swapper halves paired under each player's top half (kinds 0 and 3).
std::array<int,2> selected_bottom{-1,-1};
VirtualPortal::SwapperHalf half_of(int index) {
    return index>=0 && static_cast<unsigned>(index)<characters.size()?VirtualPortal::swapper_half(characters[static_cast<unsigned>(index)].id):VirtualPortal::SwapperHalf::none;
}
struct Trap {fs::path file;unsigned id,variant;int element,capture=-1;bool exists=false;std::array<unsigned char,1024> snapshot{};bool cached=false;};
std::vector<Trap> traps;
struct Element {const char* name;unsigned id,variant;};
constexpr std::array<Element,11> elements{{{"Water",211,12289},{"Life",217,12291},{"Air",212,12291},{"Earth",216,12288},{"Fire",215,12293},{"Undead",213,12292},{"Magic",210,12290},{"Tech",214,12288},{"Light",219,12288},{"Dark",218,12288},{"Kaos",220,12318}}};
int element_for(unsigned id){for(unsigned i=0;i<elements.size();++i)if(elements[i].id==id)return static_cast<int>(i);return -1;}
std::string metadata_seed() {static const auto seed=[] {std::ifstream file(fs::current_path()/".local/portal-assets/trap-metadata.seed",std::ios::binary);std::string value(257,'\0');file.read(value.data(),257);value.resize(static_cast<std::size_t>(file.gcount()));return value.size()<=256?value:std::string{};}();return seed;}

const PortalPortraits::Index& portrait_index() {
    static const auto value=[] {PortalPortraits::Index result;std::ifstream file(fs::current_path()/".local/portal-assets/portrait-index.txt");result.load(file);return result;}();
    return value;
}
std::string feedback="Choose an element to place an empty trap, or select a saved capture.";
bool read_figure(const fs::path& path,std::array<unsigned char,1024>& bytes) {
    std::error_code ec;
    if(fs::is_symlink(path,ec)||!fs::is_regular_file(path,ec)||fs::file_size(path,ec)!=bytes.size())return false;
    std::ifstream file(path,std::ios::binary);
    return bool(file.read(reinterpret_cast<char*>(bytes.data()),bytes.size()));
}
unsigned word(const std::array<unsigned char,1024>& b,unsigned offset) {return b[offset]|(unsigned(b[offset+1])<<8);}
void add_character(const fs::path& path) {
    std::array<unsigned char,1024> bytes{};
    if(!read_figure(path,bytes))return;
    const auto id=word(bytes,0x10),variant=word(bytes,0x1c);
    if(id>=210 && id<=220)return;
    (is_item(id)?items:characters).push_back({path,VirtualPortal::figure_name(id,variant),id,variant});
}
// Mirrors the virtual portal's start-up placement of SKY_PORTAL_FIGURE and
// SKY_PORTAL_FIGURE_BOTTOM: a bottom half is only placed under a top half.
void mark_starting(int kind,int index) {
    if(kind==2){selected_item=index;return;}
    if(half_of(index)!=VirtualPortal::SwapperHalf::bottom)selected_character=index;
    else if(half_of(selected_character)==VirtualPortal::SwapperHalf::top)selected_bottom[0]=index;
}
fs::path trap_path(int index) {return traps[static_cast<unsigned>(index)].file;}
// The Cemu safety adapter preserves writes in a content-addressed private
// working copy. Metadata must follow that copy, never the original template.
bool read_trap_progress(const Trap& trap,std::array<unsigned char,1024>& bytes) {
    if(!read_figure(trap.file,bytes))return false;
    std::uint64_t hash=14695981039346656037ull;for(auto byte:bytes){hash^=byte;hash*=1099511628211ull;}
    std::ostringstream name;name<<"import-"<<std::hex<<std::setw(16)<<std::setfill('0')<<hash<<".sky";
    const auto directory=fs::current_path()/"out/figures";std::error_code ec;
    if(fs::weakly_canonical(directory,ec)!=directory||ec)return false;
    const auto working=directory/name.str();
    const auto status=fs::symlink_status(working,ec);
    if(status.type()==fs::file_type::not_found)return true;
    return !ec&&!fs::is_symlink(status)&&read_figure(working,bytes);
}

void refresh_traps(bool force=false) {
    static auto last=std::chrono::steady_clock::time_point{};const auto now=std::chrono::steady_clock::now();
    if(!force&&now-last<std::chrono::milliseconds(500))return;
    last=now;
    for(auto& trap:traps){
        std::array<unsigned char,1024> bytes{};std::error_code ec;trap.exists=fs::is_regular_file(trap.file,ec);
        if(!trap.exists||!read_trap_progress(trap,bytes)||word(bytes,0x10)!=trap.id||word(bytes,0x1c)!=trap.variant){trap.capture=-1;trap.cached=false;continue;}
        if(trap.cached&&trap.snapshot==bytes)continue;
        trap.snapshot=bytes;trap.cached=true;trap.capture=TrapMetadata::capture(bytes,metadata_seed());
        if(trap.capture>0){const auto portrait=TrapMetadata::portrait_by_id[static_cast<unsigned>(trap.capture)];if(PortalCatalog::villains[static_cast<unsigned>(portrait)].id!=trap.id)trap.capture=-1;}
    }
}
bool ready() {
    if(root.empty())return false;
    std::error_code ec;
    return fs::weakly_canonical(root,ec)==root && !ec && !fs::is_symlink(root/"traps",ec) && !fs::is_symlink(root/"characters",ec);
}
}
namespace PortalLibrary {
void initialize(const char* initial,const char* initial_bottom) {
    {
        std::lock_guard lock(library_mutex);
        root=fs::current_path()/"out/portal-library";
        std::error_code ec;
        if(fs::weakly_canonical(root,ec)!=root || ec){root.clear();feedback="Portal library path is unavailable.";return;}
        fs::create_directories(root/"characters",ec);fs::create_directories(root/"traps",ec);
        if(ec || !ready()){root.clear();feedback="Cannot open the portal library.";return;}
        traps.clear();characters.clear();items.clear();
        for(const auto& villain:PortalCatalog::villains)traps.push_back({root/"traps"/(std::string(villain.key)+".sky"),villain.id,villain.variant,element_for(villain.id)});
        for(const auto& entry:fs::directory_iterator(root/"traps")) {
            if(!entry.path().filename().string().starts_with("element-")||traps.size()>=1024)continue;
            std::array<unsigned char,1024> bytes{};if(!read_figure(entry.path(),bytes))continue;const auto id=word(bytes,0x10);const auto element=element_for(id);
            if(element>=0)traps.push_back({entry.path(),id,word(bytes,0x1c),element});
        }
        refresh_traps(true);
        for(const auto& entry:fs::directory_iterator(root/"characters"))if(characters.size()+items.size()<512)add_character(entry.path());
    }
    if(initial && *initial)import_character(initial,false);
    if(initial_bottom && *initial_bottom)import_character(initial_bottom,false);
}
bool import_character(const char* path,bool select_after,unsigned player) {
    if(player>=2)return false;
    int index=-1,kind=0;
    {
        std::lock_guard lock(library_mutex);
        std::array<unsigned char,1024> bytes{};
        if(!path || !ready() || !read_figure(path,bytes)){feedback="Choose a regular 1024-byte Skylander dump.";return false;}
        const auto id=word(bytes,0x10);
        kind=is_item(id)?2:0;
        auto& collection=kind==2?items:characters;
        if(id>=210&&id<=220){feedback="This is a trap. Use the villain collection for dedicated traps.";return false;}
        // A tag already in the collection (e.g. a created figure chosen as the
        // starting Skylander) is used in place, never imported a second time.
        std::error_code source_error;const auto source=fs::weakly_canonical(path,source_error);
        if(!source_error&&source.parent_path()==root/"characters")
            for(unsigned i=0;i<collection.size();++i)if(collection[i].file==source)index=static_cast<int>(i);
        if(index>=0){if(!select_after){mark_starting(kind,index);return true;}}
        else {
        std::uint64_t hash=14695981039346656037ull;
        for(auto b:bytes){hash^=b;hash*=1099511628211ull;}
        std::ostringstream filename;filename<<std::hex<<std::setw(16)<<std::setfill('0')<<hash<<".sky";
        const auto destination=root/"characters"/filename.str();
        std::error_code ec;
        if(fs::is_symlink(destination,ec)){feedback="Cannot import into a redirected library file.";return false;}
        ec.clear();fs::copy_file(path,destination,fs::copy_options::skip_existing,ec);
        if(ec){feedback="Could not import this Skylander.";return false;}
        for(unsigned i=0;i<collection.size();++i)if(collection[i].file==destination)index=static_cast<int>(i);
        if(index<0){if(characters.size()+items.size()>=512)return false;add_character(destination);index=static_cast<int>(collection.size())-1;}
        if(!select_after){mark_starting(kind,index);return true;}
        }
    }
    return select(kind==0 && player==1?3:kind,index);
}
bool create_character(int choice,bool select_after,unsigned player) {
    if(player>=2)return false;
    int index=-1,kind=0;
    {
        std::lock_guard lock(library_mutex);
        unsigned id=0,variant=0;
        if(!ready() || characters.size()+items.size()>=512 || choice<0 ||
           !VirtualPortal::creation_identity(static_cast<unsigned>(choice),id,variant)) {
            feedback="Choose a supported Skylander to create.";return false;
        }
        kind=is_item(id)?2:0;
        auto& collection=kind==2?items:characters;
        auto pattern=(root/"characters/.new-XXXXXX").string();
        std::vector<char> writable(pattern.begin(),pattern.end());writable.push_back(0);
        const auto* directory=mkdtemp(writable.data());
        if(!directory){feedback="Could not prepare a new Skylander.";return false;}
        const fs::path temporary=fs::path(directory)/"figure.sky";
        const auto destination=root/"characters"/(std::string("created-")+fs::path(directory).filename().string().substr(5)+".sky");
        std::error_code ec;
        bool made=VirtualPortal::create_blank(temporary.c_str(),id,variant);
        if(made){fs::create_hard_link(temporary,destination,ec);made=!ec;}
        fs::remove_all(directory,ec);
        if(!made){feedback="Could not create this Skylander. Existing figures are unchanged.";return false;}
        const auto before=collection.size();add_character(destination);
        if(collection.size()!=before+1){feedback="New Skylander failed validation.";return false;}
        index=static_cast<int>(before);
        feedback=collection.back().name+" created. Its progress will be kept in your collection.";
    }
    return !select_after || select(kind==0 && player==1?3:kind,index);
}
bool select(int kind,int index) {
    const auto started=std::chrono::steady_clock::now();
    std::lock_guard lock(library_mutex);
    if(!ready()||index<0)return false;
    if(kind==2) {
        if(static_cast<unsigned>(index)>=items.size())return false;
        if(selected_item==index)return true;
        if(!VirtualPortal::replace_item(items[static_cast<unsigned>(index)].file.c_str()))return false;
        selected_item=index;feedback=items[static_cast<unsigned>(index)].name+" placed in the item slot.";return true;
    }
    if(kind==0 || kind==3) {
        if(static_cast<unsigned>(index)>=characters.size())return false;
        const unsigned player=kind==3?1:0;
        auto& selected=player?selected_second:selected_character;
        auto& bottom=selected_bottom[player];
        const auto other=player?selected_character:selected_second;
        if(other==index || selected_bottom[1-player]==index){feedback="This figure is already placed for the other player. Create another copy to use two of the same Skylander.";return false;}
        const auto half=half_of(index);
        if(selected==index || bottom==index){feedback=characters[static_cast<unsigned>(index)].name+" is on the portal.";return true;}
        if(!VirtualPortal::replace_player(characters[static_cast<unsigned>(index)].file.c_str(),player)){feedback="Could not place this Skylander.";return false;}
        const auto& name=characters[static_cast<unsigned>(index)].name;
        if(half==VirtualPortal::SwapperHalf::bottom) {
            bottom=index;
            if(half_of(selected)!=VirtualPortal::SwapperHalf::top)selected=-1;
            feedback=selected<0?name+" placed. Add a top half to complete the swapper.":characters[static_cast<unsigned>(selected)].name+" + "+name+" swapped together.";
            return true;
        }
        selected=index;
        if(half==VirtualPortal::SwapperHalf::none)bottom=-1;
        feedback=half==VirtualPortal::SwapperHalf::top && bottom>=0?name+" + "+characters[static_cast<unsigned>(bottom)].name+" swapped together.":
            half==VirtualPortal::SwapperHalf::top?name+" placed. Add a bottom half to complete the swapper.":name+" placed on the portal.";
        return true;
    }
    if(kind!=1 || static_cast<unsigned>(index)>=traps.size())return false;
    auto& trap=traps[static_cast<unsigned>(index)];
    if(selected_trap==index){feedback="This trap is already inserted.";return true;}
    const auto file=trap_path(index);std::error_code ec;
    if(!fs::exists(file,ec)) {
        const auto temporary=file.string()+".new-"+std::to_string(getpid());
        if(fs::exists(temporary,ec)||fs::is_symlink(temporary,ec)||!VirtualPortal::create_blank(temporary.c_str(),trap.id,trap.variant)){feedback="Could not create this empty trap.";return false;}
        fs::create_hard_link(temporary,file,ec);fs::remove(temporary);if(ec){feedback="Could not store this trap.";return false;}
    }
    std::array<unsigned char,1024> bytes{};
    if(!read_figure(file,bytes)||word(bytes,0x10)!=trap.id||word(bytes,0x1c)!=trap.variant){feedback="This saved trap has unexpected identity data.";return false;}
    if(!VirtualPortal::load_trap(file.c_str())){feedback="Could not insert the selected trap.";return false;}
    selected_trap=index;refresh_traps(true);
    const auto elapsed=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-started).count();
    std::printf("{\"event\":\"portal-trap-selected\",\"index\":%d,\"host_time_us\":%lld}\n",index,static_cast<long long>(elapsed));
    feedback=std::string(elements[static_cast<unsigned>(trap.element)].name)+" trap inserted. Capture progress is preserved.";
    return true;
}
bool select_empty_trap(int element) {
    if(element<0||static_cast<unsigned>(element)>=elements.size())return false;
    int choice=-1;
    {
        std::lock_guard lock(library_mutex);if(!ready())return false;refresh_traps(true);
        for(unsigned i=46;i<traps.size();++i)if(traps[i].element==element&&traps[i].exists&&traps[i].capture==0){choice=static_cast<int>(i);break;}
        if(choice<0){if(traps.size()>=1024)return false;const auto& type=elements[static_cast<unsigned>(element)];
            auto pattern=(root/"traps"/".element-XXXXXX").string();std::vector<char> buffer(pattern.begin(),pattern.end());buffer.push_back(0);const auto* temp=mkdtemp(buffer.data());if(!temp)return false;
            const fs::path temporary=fs::path(temp)/"trap.sky";const auto destination=root/"traps"/(std::string("element-")+std::to_string(type.id)+"-"+fs::path(temp).filename().string().substr(9)+".sky");std::error_code ec;
            bool made=VirtualPortal::create_blank(temporary.c_str(),type.id,type.variant);if(made){fs::create_hard_link(temporary,destination,ec);made=!ec;}fs::remove_all(temp,ec);
            if(!made){feedback="Could not prepare an empty trap. Existing captures were kept.";return false;}
            choice=static_cast<int>(traps.size());traps.push_back({destination,type.id,type.variant,element,0,true});
        }
    }
    return select(1,choice);
}
void remove(int kind) {
    std::lock_guard lock(library_mutex);
    if(kind==0 || kind==3){VirtualPortal::remove_player(kind==3?1:0);(kind==3?selected_second:selected_character)=-1;selected_bottom[kind==3?1:0]=-1;feedback="Skylander removed. Other portal slots preserved.";}
    // Kinds 4/5 lift only a player's bottom swapper half, 6/7 only its top half.
    if(kind==4 || kind==5){VirtualPortal::remove_swapper_half(kind-4,true);selected_bottom[static_cast<unsigned>(kind-4)]=-1;feedback="Bottom half removed. The top half stays on the portal.";}
    if(kind==6 || kind==7) {
        auto& selected=kind==7?selected_second:selected_character;
        if(half_of(selected)==VirtualPortal::SwapperHalf::top){VirtualPortal::remove_swapper_half(kind-6,false);selected=-1;feedback="Top half removed. The bottom half stays on the portal.";}
    }
    if(kind==2){VirtualPortal::remove_item();selected_item=-1;feedback="Item removed. Characters and trap preserved.";}
    if(kind==1){VirtualPortal::remove_trap();selected_trap=-1;feedback="Trap removed. Its progress is kept.";}
}
std::string status(){std::lock_guard lock(library_mutex);return feedback;}
}
extern "C" int sky_portal_count(int kind){std::lock_guard lock(library_mutex);refresh_traps();return kind==1?static_cast<int>(traps.size()):(kind==0 || kind==3)?static_cast<int>(characters.size()):kind==2?static_cast<int>(items.size()):0;}
extern "C" const char* sky_portal_name(int kind,int index){
    thread_local std::string text;std::lock_guard lock(library_mutex);text.clear();
    if(index>=0&&kind==1&&static_cast<unsigned>(index)<traps.size()){
        refresh_traps();const auto& trap=traps[static_cast<unsigned>(index)];
        if(trap.capture>0)text=PortalCatalog::villains[static_cast<unsigned>(TrapMetadata::portrait_by_id[static_cast<unsigned>(trap.capture)])].name;
        else text=std::string(elements[static_cast<unsigned>(trap.element)].name)+(trap.capture==0?" empty trap":" trap (unidentified capture)");
    }
    if(index>=0&&(kind==0 || kind==3)&&static_cast<unsigned>(index)<characters.size())text=characters[static_cast<unsigned>(index)].name;
    if(index>=0&&kind==2&&static_cast<unsigned>(index)<items.size())text=items[static_cast<unsigned>(index)].name;
    return text.c_str();
}
extern "C" const char* sky_portal_detail(int kind,int index){
    std::lock_guard lock(library_mutex);if(kind==1&&index>=0&&static_cast<unsigned>(index)<traps.size())return elements[static_cast<unsigned>(traps[static_cast<unsigned>(index)].element)].name;
    if((kind==0 || kind==3)&&index>=0) {
        const auto half=half_of(index);
        if(half==VirtualPortal::SwapperHalf::top)return "Swapper top half";
        if(half==VirtualPortal::SwapperHalf::bottom)return "Swapper bottom half";
    }
    return kind==2?"Magic / adventure item":"Skylander";
}
extern "C" int sky_portal_state(int kind,int index){
    std::lock_guard lock(library_mutex);
    if(index<0)return 0;
    // Bit 2: placed for this player; bit 4: placed as its bottom swapper half.
    if((kind==0 || kind==3)&&static_cast<unsigned>(index)<characters.size()) {
        const auto player=kind==3?1u:0u;const auto main=player?selected_second:selected_character;
        return 1|(main==index?2:0)|(selected_bottom[player]==index?6:0);
    }
    if(kind==2&&static_cast<unsigned>(index)<items.size())return 1|(selected_item==index?2:0);
    if(kind==1&&static_cast<unsigned>(index)<traps.size()&&!root.empty())return (traps[static_cast<unsigned>(index)].exists?1:0)|(selected_trap==index?2:0);
    return 0;
}
extern "C" int sky_portal_portrait(int kind,int index){
    std::lock_guard lock(library_mutex);
    if(kind==1&&index>=0&&static_cast<unsigned>(index)<traps.size()){const auto capture=traps[static_cast<unsigned>(index)].capture;return capture>0?TrapMetadata::portrait_by_id[static_cast<unsigned>(capture)]:-1;}
    const auto* collection=(kind==0 || kind==3)?&characters:kind==2?&items:nullptr;
    if(collection && index>=0 && static_cast<unsigned>(index)<collection->size()) {
        const auto& figure=(*collection)[static_cast<unsigned>(index)];
        return portrait_index().find(figure.id,figure.variant);
    }
    return -1;
}
extern "C" const char* sky_portal_status(){thread_local std::string text;text=PortalLibrary::status();return text.c_str();}
extern "C" const char* sky_portal_atlas(){static const auto path=(fs::current_path()/".local/portal-assets/portraits.rgba").string();return path.c_str();}
extern "C" int sky_portal_creation_count(){return static_cast<int>(VirtualPortal::creation_count());}
extern "C" const char* sky_portal_creation_name(int index){return index<0?"":VirtualPortal::creation_name(static_cast<unsigned>(index));}

extern "C" int sky_portal_creation_kind(int index) {
    unsigned id=0,variant=0;
    return index>=0 && VirtualPortal::creation_identity(static_cast<unsigned>(index),id,variant)?(is_item(id)?2:0):-1;
}

extern "C" int sky_portal_creation_portrait(int index) {
    unsigned id=0,variant=0;
    return index>=0 && VirtualPortal::creation_identity(static_cast<unsigned>(index),id,variant)?portrait_index().find(id,variant):-1;
}

extern "C" int sky_portal_trap_element_count(){return static_cast<int>(elements.size());}
extern "C" const char* sky_portal_trap_element_name(int index){return index>=0&&static_cast<unsigned>(index)<elements.size()?elements[static_cast<unsigned>(index)].name:"";}
extern "C" int sky_portal_trap_element(int index){std::lock_guard lock(library_mutex);return index>=0&&static_cast<unsigned>(index)<traps.size()?traps[static_cast<unsigned>(index)].element:-1;}
extern "C" int sky_portal_trap_capture(int index){std::lock_guard lock(library_mutex);refresh_traps();return index>=0&&static_cast<unsigned>(index)<traps.size()?traps[static_cast<unsigned>(index)].capture:-1;}

extern "C" int sky_portal_element_portrait(int index){
    static const auto cells=[] {std::array<int,11> value{};value.fill(-1);std::ifstream file(fs::current_path()/".local/portal-assets/element-index.txt");int element=0,cell=0;while(file>>element>>cell)if(element>=0&&element<11&&cell>=0&&cell<2048)value[static_cast<unsigned>(element)]=cell;return value;}();
    return index>=0&&index<11?cells[static_cast<unsigned>(index)]:-1;
}

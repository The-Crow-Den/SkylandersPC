// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/host_files.hpp"
#include "../hle/kernel_file.hpp"
#include "../hle/save_data.hpp"
#include "../pc_menu_frame.hpp"
#include <array>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <source_location>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
namespace {
void require(bool value, const std::source_location where = std::source_location::current()) {
    if (!value) throw std::runtime_error(std::string("file assertion at ") + where.file_name() + ":" +
        std::to_string(where.line()) + " errno=" + std::to_string(errno));
}
std::filesystem::path decode_path(std::string_view hex) {
    require(hex.size() % 2 == 0);
    std::u8string value;
    auto digit = [](char c) -> unsigned {
        if (c >= '0' && c <= '9') return static_cast<unsigned>(c-'0');
        if (c >= 'a' && c <= 'f') return static_cast<unsigned>(c-'a'+10);
        throw std::runtime_error("invalid test path encoding");
    };
    for (std::size_t i = 0; i < hex.size(); i += 2)
        value.push_back(static_cast<char8_t>(16 * digit(hex[i]) + digit(hex[i+1])));
    return std::filesystem::path(value);
}
std::string frame_path(const std::filesystem::path& path) {
    const auto bytes = path.u8string();
    return {reinterpret_cast<const char*>(bytes.data()),bytes.size()};
}
void frame_tests(const std::filesystem::path& root) {
    constexpr std::size_t size = 64+3840*2160*4;
    const auto unicode_name = root/std::filesystem::path(u8"unicode_\u03bb.bin");
    const auto encoded = SkyHost::path_to_utf8(unicode_name);
    require(encoded.ends_with("unicode_\xce\xbb.bin") && SkyHost::path_from_utf8(encoded) == unicode_name);
    require(SkyHost::private_directory(root/"private-ipc"));
    require(!SkyHost::private_directory(root/"public-ipc"));
    require(!SkyHost::private_directory(root/"ipc-alias"));
    require(!SkyHost::private_directory(root/"private-ipc"/".."));
    require(!SkyHost::private_directory(root/"missing-ipc"));
    require(!SkyHost::private_directory(root/"frame.rgba"));
    SkyHost::PrivateFileMapping mapping;
    require(mapping.open(root/"frame.rgba",size) && mapping.data());
    const auto* address = mapping.data();
    require(!mapping.open(root/"frame.rgba",size-1) && mapping.data() == address);
    require(!mapping.open(root/"frame.rgba",0) && mapping.data() == address);
    auto invalid_path = (root/"frame.rgba").native();
    invalid_path.push_back(0);
    invalid_path += std::filesystem::path("suffix").native();
    require(!mapping.open(std::filesystem::path(invalid_path),size) && mapping.data() == address);
    require(!mapping.open(root/"frame-public.rgba",size) && mapping.data() == address);
    require(!mapping.open(root/"frame-link.rgba",size) && mapping.data() == address);
    require(!mapping.open(root/"outside",size) && mapping.data() == address);
    require(!mapping.open(root/"frame-short.rgba",size) && mapping.data() == address);
    PcOverlay::FrameReader reader(frame_path(root/"frame.rgba").c_str());
    std::array<char,8> pixels{};
    int width = 0, height = 0;
    unsigned generation = 0;
    require(reader.copy(pixels.data(),8,&width,&height,&generation));
    require(width == 2 && height == 1 && generation == 2 && std::string(pixels.data(),8) == "RGBAdata");
    require(!reader.copy(pixels.data(),8,&width,&height,&generation));
    generation = 0;
    require(!reader.copy(pixels.data(),7,&width,&height,&generation) && generation == 0);
    require(!reader.copy(pixels.data(),-1,&width,&height,&generation));
    require(!reader.copy(nullptr,8,&width,&height,&generation));
    require(!reader.copy(pixels.data(),8,nullptr,&height,&generation));
    require(!reader.copy(pixels.data(),8,&width,nullptr,&generation));
    require(!reader.copy(pixels.data(),8,&width,&height,nullptr));
    for (const auto* name : {"frame-public.rgba","frame-link.rgba","frame-short.rgba","frame-odd.rgba","frame-bad.rgba"}) {
        PcOverlay::FrameReader denied(frame_path(root/name).c_str());
        require(!denied.copy(pixels.data(),8,&width,&height,&generation));
    }
#ifndef _WIN32
    // Preserve the old Linux policy: parent symlinks are allowed, leaf links
    // are not; privacy is checked on the opened file.
    PcOverlay::FrameReader parent_link(frame_path(root/"frame-parent"/"frame.rgba").c_str());
    require(parent_link.copy(pixels.data(),8,&width,&height,&generation));
#else
    SkyHost::PrivateFileMapping denied;
    require(!denied.open(root/"frame-parent"/"frame.rgba",size));
    require(!denied.open(root/"frame-null-dacl.rgba",size));
#endif
}
void private_state_tests(const std::filesystem::path& root) {
    using namespace SkyHost;
    File directory;
    require(directory.open_private_directory(root/"private-ipc"));
    for (const auto* name : {"public-ipc","ipc-alias","missing-ipc","frame.rgba"})
        require(!directory.open_private_directory(root/name) && directory.valid());
    require(!directory.open_private_directory(root/"private-ipc"/"..") && directory.valid());
    require(directory.write_atomic("state.json","first",5,false));
    File old;
    require(directory.open_child("state.json",{},true,old));
    require(directory.write_atomic("state.json","second",6,false));
    std::array<char,8> data{};
    require(old.read(data.data(),data.size()) == 5 && std::string(data.data(),5) == "first");
    require(old.close() == 0);
    File latest;
    require(directory.open_child("state.json",{},true,latest));
    require(latest.read(data.data(),data.size()) == 6 && std::string(data.data(),6) == "second");
    require(latest.close() == 0);
    require(!directory.write_atomic("../outside.bin","BAD",3,false));
    require(!directory.write_atomic("state.json",nullptr,1,false));
    std::filesystem::rename(root/"private-ipc",root/"held-ipc");
    std::filesystem::rename(root/"publish-escape",root/"private-ipc");
    require(!directory.open_private_directory(root/"private-ipc") && directory.valid());
    require(directory.write_atomic("state.json","held",4,false));
    require(!std::filesystem::exists(root/"outside"/"state.json"));
    require(std::filesystem::file_size(root/"held-ipc"/"state.json") == 4);
    for (const auto& item : std::filesystem::directory_iterator(root/"held-ipc"))
        require(!item.path().filename().string().starts_with(".pending-"));
}
void live_frame_test(const std::filesystem::path& root) {
    PcOverlay::FrameReader reader(frame_path(root/"frame.rgba").c_str());
    unsigned generation = 0;
    std::array<char,8> pixels{};
    int width = 0, height = 0;
    std::cout << "ready" << std::endl;
    for (std::string command; std::getline(std::cin,command) && command != "quit";) {
        require(command == "read");
        const bool copied = reader.copy(pixels.data(),8,&width,&height,&generation);
        std::cout << copied << ' ' << generation << ' ' << width << ' ' << height << ' ';
        for (const char byte : pixels) {
            const auto value = static_cast<unsigned char>(byte);
            constexpr char hex[] = "0123456789abcdef";
            std::cout << hex[value >> 4] << hex[value & 15];
        }
        std::cout << std::endl;
    }
}
void capability_tests(const std::filesystem::path& root) {
    using namespace SkyHost;
    File game, file, duplicate;
    require(game.open_directory(root/"game",true) && game.valid());
    require(game.duplicate_directory(duplicate));
    require(!game.duplicate_directory(game) && errno == EINVAL && game.valid());
    require(game.open_child("data.bin",{},false,file));
    require(!file.duplicate_directory(duplicate) && errno == ENOTDIR);
    FileInfo info{};
    require(duplicate.stat(info) && info.directory);
    std::array<char,16> data{};
    require(file.read(data.data(),3) == 3 && std::string(data.data(),3) == "abc");
    require(file.read_at(data.data(),3,1) == 3 && std::string(data.data(),3) == "bcd");
    require(file.seek(0,1) == 3);
    require(file.read_at(data.data(),1,-1) < 0 && errno == EINVAL && file.seek(0,1) == 3);
    require(file.stat(info) && info.regular && !info.directory && info.size == 6 && info.links == 1 && info.block_size);
    require(file.write("x",1) < 0 && errno == EBADF);
    File moved(std::move(file));
    require(!file.valid() && moved.valid() && moved.seek(0,1) == 3);
    require(moved.close() == 0 && moved.close() < 0 && errno == EBADF);
    for (const auto* name : {"..", ".", "../outside.bin", "/outside.bin", "DATA.bin"}) {
        File denied;
        require(!game.open_child(name,{},false,denied) && !denied.valid());
    }
    File denied;
    require(!game.open_child(std::string_view("data.bin\0suffix",15),{},false,denied));
    require(!game.open_child("data.bin",{},false,game) && errno == EINVAL && game.valid());
#ifdef _WIN32
    for (const auto* name : {"..\\outside.bin", "C:\\outside.bin", "data.bin:stream"})
        require(!game.open_child(name,{},false,denied));
#else
    require(!game.open_child("link.bin",{},false,denied));
#endif
    FileOpen directory;
    directory.directory = true;
    require(!game.open_child("escape",directory,false,denied));
    File strict_root;
    require(!strict_root.open_directory(root/"game_alias"));
#ifdef _WIN32
    require(!strict_root.open_directory(root/"game_alias",true));
#else
    require(strict_root.open_directory(root/"game_alias",true)); // Existing trusted Linux game-root policy.
#endif
    File unicode;
    require(game.open_child("unicode_\xce\xbb.bin",{},false,unicode));
    require(unicode.read(data.data(),4) == 4 && std::string(data.data(),4) == "utf8");
    File saves, progress;
    require(saves.open_directory(root/"save"));
    FileOpen writable;
    writable.access = FileAccess::ReadWrite;
    writable.create = true;
    writable.truncate = true;
    require(!saves.open_child("hardlink",writable,true,denied));
    require(saves.open_child("progress",writable,true,progress));
    require(progress.write("progress",8) == 8 && progress.seek(0,1) == 8);
    require(progress.write_at("X",1,3) == 1 && progress.seek(0,1) == 8);
    require(progress.read_at(data.data(),8,0) == 8 && std::string(data.data(),8) == "proXress");
    require(progress.sync() == 0);
    require(progress.truncate(4) == 0 && progress.seek(0,1) == 8);
    require(progress.stat(info) && info.size == 4);
    require(progress.close() == 0);
    FileOpen append;
    append.access = FileAccess::ReadWrite;
    append.append = true;
    require(saves.open_child("progress",append,true,progress));
    require(progress.seek(0,0) == 0 && progress.write("end",3) == 3 && progress.seek(0,1) == 7);
    // Linux pwrite on O_APPEND appends but preserves the shared file position.
    require(progress.write_at("z",1,0) == 1 && progress.seek(0,1) == 7);
    require(progress.read_at(data.data(),8,0) == 8 && std::string(data.data(),8) == "proXendz");
    require(progress.sync() == 0 && progress.close() == 0);
    writable.exclusive = true;
    require(!saves.open_child("progress",writable,true,denied) && errno == EEXIST);
}
void directory_tests(const std::filesystem::path& root) {
    using namespace SkyHost;
    File parent, child, nested;
    require(parent.open_directory(root/"created"/"nested",false,true));
    require(parent.ensure_directory("slot",child));
    require(parent.ensure_directory("slot",nested)); // Existing directory is retained.
    FileInfo info{};
    bool exists = false;
    require(parent.child_info("slot",info,exists) && exists && info.directory);
    info.size = 12345;
    exists = true;
    require(parent.child_info("missing",info,exists) && !exists && info.size == 12345);
    require(!parent.ensure_directory("slot",parent) && errno == EINVAL && parent.valid());
    require(!parent.ensure_directory("..",nested) && nested.valid());
    require(!parent.child_info("../outside",info,exists));
    File invalid;
    require(!invalid.child_info("missing",info,exists) && errno == EBADF);
    require(!invalid.ensure_directory("missing",nested) && errno == EBADF && nested.valid());
    File conflict;
    require(!conflict.open_directory(root/"save"/"hardlink"/"child",false,true));
    require(!conflict.open_directory(root/"created",true,true) && errno == EINVAL);
    File game;
    require(game.open_directory(root/"game"));
    require(!game.ensure_directory("data.bin",nested) && nested.valid());
    exists = true;
    info.size = 12345;
    require(!game.child_info("escape",info,exists) && exists && info.size == 12345);
    require(!game.ensure_directory("escape",nested) && nested.valid());
    require(!conflict.open_directory(root/"game_alias"/"new",false,true));
    require(!std::filesystem::exists(root/"game"/"new"));
    File saves;
    require(saves.open_directory(root/"save"));
    require(saves.child_info("hardlink",info,exists) && exists && info.regular && info.links >= 2);
#ifndef _WIN32
    require(game.child_info("fifo",info,exists) && exists && !info.regular && !info.directory);
    require(!game.child_info("link.bin",info,exists));
#endif
    // Keep a directory capability, then put a real junction/symlink at its
    // original name. Operations on the held directory must stay on its inode.
    std::filesystem::rename(root/"created"/"nested"/"slot",root/"created"/"nested"/"held");
    std::filesystem::rename(root/"create_escape",root/"created"/"nested"/"slot");
    require(!parent.ensure_directory("slot",nested));
    require(!parent.child_info("slot",info,exists));
    require(child.ensure_directory("inside",nested));
    File marker;
    FileOpen writable;
    writable.access = FileAccess::Write;
    writable.create = writable.exclusive = true;
    require(nested.open_child("marker",writable,true,marker));
    require(marker.write("held",4) == 4 && marker.sync() == 0 && marker.close() == 0);
    require(!std::filesystem::exists(root/"outside"/"inside"));
    KernelFile files;
    require(files.mount_save("/savedata0",child,false));
    require(!files.mount_save("/savedata0",child,false));
    File invalid_mount;
    require(!files.mount_save("/savedata1",invalid_mount,false));
    const std::array<std::uint64_t,6> args{
        reinterpret_cast<std::uintptr_t>("/savedata0/inside/marker"),0};
    const auto fd = files.call("1G3lF1Gg1k8#libkernel#libkernel",args.data());
    require(fd >= 3 && fd < 1024);
    std::array<char,4> bytes{};
    const std::array<std::uint64_t,6> read{fd,reinterpret_cast<std::uintptr_t>(bytes.data()),bytes.size()};
    require(files.call("Cg4srZ6TKbU#libkernel#libkernel",read.data()) == 4 && std::string(bytes.data(),4) == "held");
    const std::array<std::uint64_t,6> close{fd};
    require(files.call("UK2Tl2DWUns#libkernel#libkernel",close.data()) == 0);
    require(files.unmount_save("/savedata0"));
}
void move_tests(const std::filesystem::path& root) {
    using namespace SkyHost;
    File parent, trash, slot, existing;
    require(parent.open_directory(root/"moves",false,true));
    require(parent.ensure_directory("trash",trash));
    require(parent.ensure_directory("slot",slot));
    require(slot.write_atomic("marker","retained",8));
    require(slot.close() == 0);
    require(trash.ensure_directory("existing",existing));
    require(existing.write_atomic("marker","untouched",9));
    require(existing.close() == 0);
    require(!parent.move_directory("slot",trash,"existing") && errno == EEXIST);
    require(parent.move_directory("slot",trash,"moved"));
    require(!parent.move_directory("slot",trash,"missing") && errno == ENOENT);
    require(trash.move_directory("moved",trash,"renamed")); // Same parent capability.
    require(!trash.move_directory("renamed",trash,"renamed") && errno == EEXIST);
    require(!trash.move_directory("../outside",trash,"denied"));
    require(!trash.move_directory("renamed",trash,"../denied"));
    std::filesystem::rename(root/"move_escape",root/"moves"/"escape");
    require(!parent.move_directory("escape",trash,"denied"));
    File wrong;
    require(!wrong.move_directory("missing",trash,"denied"));
    require(!trash.move_directory("renamed",wrong,"denied"));
    File directory, marker;
    FileOpen options;
    options.directory = true;
    require(trash.open_child("renamed",options,false,directory));
    require(directory.open_child("marker",{},true,marker));
    std::array<char,8> data{};
    require(marker.read(data.data(),data.size()) == 8 && std::string(data.data(),8) == "retained");
}
void atomic_tests(const std::filesystem::path& root) {
    using namespace SkyHost;
    File directory;
    require(directory.open_directory(root/"save"));
    require(directory.write_atomic("metadata","first",5));
    require(directory.write_atomic("metadata","second",6));
    File read;
    require(directory.open_child("metadata",{},true,read));
    std::array<char,8> data{};
    require(read.read(data.data(),data.size()) == 6 && std::string(data.data(),6) == "second");
    require(read.close() == 0);
    require(!directory.write_atomic("hardlink","BAD",3));
    require(!directory.write_atomic("hardlink","BAD",3,false));
#ifdef _WIN32
    // Python holds the destination without delete sharing: publication must
    // fail, remove the owned sibling, and preserve the previous contents.
    require(!directory.write_atomic("locked","BAD",3) && errno == EACCES);
    require(!directory.write_atomic("locked","BAD",3,false) && errno == EACCES);
#endif
    require(!directory.write_atomic("../outside.bin","BAD",3));
    require(!directory.write_atomic("progress",nullptr,1) && errno == EINVAL);
    require(directory.write_atomic("empty",nullptr,0));
    FileInfo info{};
    bool exists = false;
    require(directory.child_info("empty",info,exists) && exists && info.size == 0);
    File game;
    require(game.open_directory(root/"game"));
    require(!game.write_atomic("escape","BAD",3));
#ifndef _WIN32
    require(!game.write_atomic("fifo","BAD",3));
    File fifo;
    require(!game.open_child("fifo",{},true,fifo));
    require(!game.write_atomic("link.bin","BAD",3));
#endif
    for (const auto& item : std::filesystem::directory_iterator(root/"save"))
        require(!item.path().filename().string().starts_with(".pending-"));
}
void save_metadata_tests(const std::filesystem::path& root) {
    using U = std::uint64_t;
    const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
    KernelFile files;
    SaveData saves(files);
    saves.configure(root/"metadata-saves","CUSA00697");
    auto save = [&](const char* nid, std::array<U,6> args = {}) {
        return saves.call(std::string(nid)+"#libSceSaveData#libSceSaveData",args.data());
    };
    struct Mount {std::int32_t user,pad;U title,dir,fingerprint,blocks;std::uint32_t mode;unsigned char reserved[32];};
    Mount mount{0x1000,0,0,pointer("synthetic"),0,96,34,{}};
    alignas(8) std::array<char,64> result{};
    require(save("ZkZhskCPXFw") == 0);
    require(save("32HQAQdwM2o",{pointer(&mount),pointer(result.data())}) == 0);
    std::array<char,128> title{};
    require(save("XgvSuIdnMlw",{pointer(result.data()),1,pointer(title.data()),title.size()}) == 0 && title[0] == 0);
    const char initial[] = "held directory";
    require(save("85zul--eGXs",{pointer(result.data()),1,pointer(initial),sizeof(initial)}) == 0);
    require(save("XgvSuIdnMlw",{pointer(result.data()),1,pointer(title.data()),title.size()}) == 0 && std::string(title.data()) == initial);
    const auto parent = root/"metadata-saves"/"CUSA00697"/"user-4096";
    const auto metadata = parent/"synthetic.sce_sys";
    std::filesystem::rename(metadata,parent/"held");
    std::filesystem::rename(root/"metadata_escape",metadata);
    const char updated[] = "updated held directory";
    require(save("85zul--eGXs",{pointer(result.data()),1,pointer(updated),sizeof(updated)}) == 0);
    require(save("XgvSuIdnMlw",{pointer(result.data()),1,pointer(title.data()),title.size()}) == 0 && std::string(title.data()) == updated);
    // A hard-linked metadata entry must neither disclose nor replace outside data.
    std::filesystem::remove(parent/"held"/"param.bin");
    std::filesystem::create_hard_link(root/"outside.bin",parent/"held"/"param.bin");
    require(save("XgvSuIdnMlw",{pointer(result.data()),1,pointer(title.data()),title.size()}) == 0x809f000b);
    require(save("85zul--eGXs",{pointer(result.data()),1,pointer(initial),sizeof(initial)}) == 0x809f000b);
    std::filesystem::remove(parent/"held"/"param.bin");
    // Truncated metadata is reported as corrupt, and never silently reset.
    SkyHost::File meta;
    require(meta.open_directory(parent/"held"));
    require(meta.write_atomic("param.bin","short",5));
    require(save("XgvSuIdnMlw",{pointer(result.data()),1,pointer(title.data()),title.size()}) == 0x809f000f);
    struct Icon {U buffer,capacity,size;unsigned char reserved[32];};
    Icon icon{pointer("icon"),4,4,{}};
    require(save("c88Yy54Mx0w",{pointer(result.data()),pointer(&icon)}) == 0);
    std::filesystem::remove(parent/"held"/"param.bin");
    std::filesystem::rename(root/"metadata_file_escape",parent/"held"/"param.bin");
    require(save("XgvSuIdnMlw",{pointer(result.data()),1,pointer(title.data()),title.size()}) == 0x809f000b);
    require(save("85zul--eGXs",{pointer(result.data()),1,pointer(initial),sizeof(initial)}) == 0x809f000b);
    require(save("S1GkePI17zQ",{pointer(&mount)}) == 0x809f0003);
    require(save("BMR4F-Uek3E",{pointer(result.data())}) == 0);
    require(save("S1GkePI17zQ",{pointer(&mount)}) == 0x809f000b); // Redirected metadata directory.
    require(std::filesystem::is_directory(parent/"synthetic"));
    require(meta.close() == 0);
    std::filesystem::remove(metadata); // Unlink the fixture junction itself.
    std::filesystem::rename(parent/"held",metadata);
    require(save("S1GkePI17zQ",{pointer(&mount)}) == 0);
    require(!std::filesystem::exists(parent/"synthetic"));
    require(!std::filesystem::exists(metadata));
    require(save("S1GkePI17zQ",{pointer(&mount)}) == 0x809f0008);
    unsigned quarantined = 0;
    for (const auto& entry : std::filesystem::directory_iterator(parent/".deleted")) {
        require(entry.is_directory());
        ++quarantined;
    }
    require(quarantined == 2);
    require(!std::filesystem::exists(root/"outside"/"param.bin"));
    require(!std::filesystem::exists(root/"outside"/"icon0.png"));
}
void guest_tests(const std::filesystem::path& root) {
    using U = std::uint64_t;
    const auto pointer = [](auto* value) { return reinterpret_cast<std::uintptr_t>(value); };
    KernelFile files;
    files.configure(root/"game");
    require(files.mount_save("/savedata0",root/"save",false));
    auto call = [&](const char* nid, std::array<U,6> args = {}) {
        return files.call(std::string(nid) + "#libkernel#libkernel",args.data());
    };
    const auto game = call("1G3lF1Gg1k8",{pointer("/app0/data.bin"),0});
    require(game >= 3 && game < 1024);
    std::array<char,8> data{};
    require(call("Cg4srZ6TKbU",{game,pointer(data.data()),3}) == 3 && std::string(data.data(),3) == "abc");
    require(call("+r3rMFwItV4",{game,pointer(data.data()),3,1}) == 3 && std::string(data.data(),3) == "bcd");
    require(call("oib76F-12fk",{game,0,1}) == 3);
    alignas(8) std::array<unsigned char,120> stat{};
    require(call("kBwCPsYX-m4",{game,pointer(stat.data())}) == 0);
    std::int64_t size = 0;
    std::memcpy(&size,stat.data()+72,sizeof(size));
    require(size == 6);
    require(static_cast<std::int64_t>(call("4wSze92BhLI",{game,pointer("x"),1})) < 0);
    require(call("UK2Tl2DWUns",{game}) == 0);
    for (const auto* path : {"/app0/../outside.bin", "/etc/passwd", "/app0/escape/secret.bin"})
        require(static_cast<std::int64_t>(call("1G3lF1Gg1k8",{pointer(path),0})) < 0);
    require(static_cast<std::int64_t>(call("1G3lF1Gg1k8",{pointer("/savedata0/hardlink"),0x401})) < 0);
    const auto save = call("1G3lF1Gg1k8",{pointer("/savedata0/guest.bin"),0x602});
    require(save >= 3 && save < 1024);
    require(call("4wSze92BhLI",{save,pointer("progress"),8}) == 8);
    require(call("nKWi-N2HBV4",{save,pointer("X"),1,3}) == 1);
    require(call("oib76F-12fk",{save,0,1}) == 8);
    require(call("fTx66l5iWIA",{save}) == 0);
    require(!files.unmount_save("/savedata0"));
    require(call("UK2Tl2DWUns",{save}) == 0 && files.unmount_save("/savedata0"));
    require(files.mount_save("/savedata0",root/"save",true));
    require(static_cast<std::int64_t>(call("1G3lF1Gg1k8",{pointer("/savedata0/guest.bin"),0x401})) < 0);
    const auto read = call("1G3lF1Gg1k8",{pointer("/savedata0/guest.bin"),0});
    require(read >= 3 && read < 1024);
    require(call("Cg4srZ6TKbU",{read,pointer(data.data()),8}) == 8 && std::string(data.data(),8) == "proXress");
    require(call("UK2Tl2DWUns",{read}) == 0 && files.unmount_save("/savedata0"));
}
void race_tests(const std::filesystem::path& root) {
    using namespace SkyHost;
    File game;
    require(game.open_directory(root/"game",true));
    FileOpen directory;
    directory.directory = true;
    auto control = [&] {
        File stable, file;
        require(game.open_child("stable",directory,false,stable));
        require(stable.open_child("secret.bin",{},false,file));
        std::array<char,8> data{};
        require(file.read(data.data(),data.size()) == 6 && std::string(data.data(),6) == "inside");
    };
    control();
    unsigned reads = 0;
    for (unsigned i = 0; i < 2000; ++i) {
        File selected, file;
        if (!game.open_child("switch",directory,false,selected)) continue;
        if (!selected.open_child("secret.bin",{},false,file)) continue;
        std::array<char,16> data{};
        const auto count = file.read(data.data(),data.size());
        require(count == 6 && std::string(data.data(),6) == "inside");
        ++reads;
    }
    control();
    std::cout << "confined reads=" << reads << '\n';
}
}
int main(int argc, char** argv) {
    try {
        require(argc == 2 || argc == 3);
        const auto root = decode_path(argv[1]);
        if (argc == 3 && std::string_view(argv[2]) == "race") race_tests(root);
        else if (argc == 3 && std::string_view(argv[2]) == "frame") live_frame_test(root);
        else { frame_tests(root); private_state_tests(root); capability_tests(root); directory_tests(root); move_tests(root); atomic_tests(root); save_metadata_tests(root); guest_tests(root); }
        std::cout << "file capability tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

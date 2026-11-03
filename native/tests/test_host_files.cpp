// SPDX-License-Identifier: GPL-3.0-or-later
#include "../platform/host_files.hpp"
#include "../hle/kernel_file.hpp"
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
        else { capability_tests(root); directory_tests(root); guest_tests(root); }
        std::cout << "file capability tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

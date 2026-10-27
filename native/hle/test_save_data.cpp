// SPDX-License-Identifier: GPL-3.0-or-later
#include "save_data.hpp"
#include "kernel_file.hpp"
#include "local_players.hpp"
#include <array>
#include <csignal>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
int main(){
    std::filesystem::path root;
    try{
        using U=std::uint64_t;
        const auto check=[](bool ok){if(!ok)throw std::runtime_error("SaveData round-trip contract failed");};
        const auto ptr=[](auto* p){return reinterpret_cast<U>(p);};
        char pattern[]="/tmp/sky-save-XXXXXX";auto* path=mkdtemp(pattern);check(path);root=path;
        std::filesystem::create_directory(root/"game");
        std::ofstream(root/"game/original")<<"unchanged";
        KernelFile files;files.configure((root/"game").string());
        SaveData saves(files);saves.configure((root/"saves").string(),"CUSA00697");
        const auto save=[&](const char* nid,std::array<U,6> args={}){return saves.call(std::string(nid)+"#libSceSaveData#libSceSaveData",args.data());};
        const auto file=[&](const char* nid,std::array<U,6> args={}){return files.call(std::string(nid)+"#libkernel#libkernel",args.data());};
        struct Mount{std::int32_t user,pad;U title,dir,fingerprint,blocks;std::uint32_t mode;unsigned char reserved[32];};
        static_assert(sizeof(Mount)==80);
        const char name[]="synthetic";Mount mount{0x1000,0,0,ptr(name),0,96,2,{}};
        alignas(8) std::array<char,64> result{};
        check(save("ZkZhskCPXFw")==0);
        check(save("32HQAQdwM2o",{ptr(&mount),ptr(result.data())})==0x809f0008);
        mount.mode=6;
        check(save("32HQAQdwM2o",{ptr(&mount),ptr(result.data())})==0);
        check(std::string(result.data())=="/savedata0");
        const char original_title[]="Original title";
        check(save("85zul--eGXs",{ptr(result.data()),1,ptr(original_title),sizeof(original_title)})==0);
        // Simulate a write that runs out of file space after a partial write.
        // The replacement fails, but the previously committed title survives.
        const auto child=fork();check(child>=0);
        if(child==0){
            signal(SIGXFSZ,SIG_IGN);const rlimit limit{64,64};
            if(setrlimit(RLIMIT_FSIZE,&limit)!=0)_exit(2);
            const char replacement[]="Replacement";
            _exit(save("85zul--eGXs",{ptr(result.data()),1,ptr(replacement),sizeof(replacement)})==0x809f000b?0:3);
        }
        int status=0;check(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
        std::array<char,128> saved_title{};
        check(save("XgvSuIdnMlw",{ptr(result.data()),1,ptr(saved_title.data()),saved_title.size()})==0);
        check(std::string(saved_title.data())==original_title);
        for(const auto& entry:std::filesystem::directory_iterator(root/"saves/CUSA00697/user-4096/synthetic.sce_sys"))
            check(entry.path().filename()=="param.bin");

        const auto fd=file("1G3lF1Gg1k8",{ptr("/savedata0/data"),0x602});check(fd<1024);
        check(file("4wSze92BhLI",{fd,ptr("progress"),8})==8);
        check(file("nKWi-N2HBV4",{fd,ptr("X"),1,3})==1);
        check(file("oib76F-12fk",{fd,0,1})==8); // pwrite preserves file position.
        check(file("fTx66l5iWIA",{fd})==0);
        check(file("VW3TVZiM4-E",{fd,8})==0);
        const auto save_root=root/"saves/CUSA00697/user-4096/synthetic";
        std::filesystem::create_hard_link(root/"game/original",save_root/"hardlink");
        std::filesystem::create_symlink(root/"game/original",save_root/"symlink");
        check(static_cast<std::int64_t>(file("1G3lF1Gg1k8",{ptr("/savedata0/hardlink"),0x401}))<0);
        check(static_cast<std::int64_t>(file("1G3lF1Gg1k8",{ptr("/savedata0/symlink"),0x401}))<0);
        check(std::filesystem::file_size(root/"game/original")==9);
        check(save("BMR4F-Uek3E",{ptr(result.data())})==0x809f0003);
        check(file("UK2Tl2DWUns",{fd})==0);
        check(save("BMR4F-Uek3E",{ptr(result.data())})==0);
        mount.mode=1;
        check(save("32HQAQdwM2o",{ptr(&mount),ptr(result.data())})==0);
        check(static_cast<std::int64_t>(file("1G3lF1Gg1k8",{ptr("/savedata0/data"),0x401}))<0);
        const auto read=file("1G3lF1Gg1k8",{ptr("/savedata0/data")});
        std::array<char,8> bytes{};check(file("Cg4srZ6TKbU",{read,ptr(bytes.data()),8})==8);
        check(std::string(bytes.data(),8)=="proXress");check(file("UK2Tl2DWUns",{read})==0);
        check(static_cast<std::int64_t>(file("1G3lF1Gg1k8",{ptr("/savedata0/../escape"),0x602}))<0);
        check(static_cast<std::int64_t>(file("1G3lF1Gg1k8",{ptr("/app0/original"),0x602}))<0);
        check(save("BMR4F-Uek3E",{ptr(result.data())})==0);
        check(std::filesystem::file_size(root/"game/original")==9);
        check(save("S1GkePI17zQ",{ptr(&mount)})==0);
        check(!std::filesystem::exists(root/"saves/CUSA00697/user-4096/synthetic"));
        check(std::filesystem::is_directory(root/"saves/CUSA00697/user-4096/.deleted"));
        check(save("32HQAQdwM2o",{ptr(&mount),ptr(result.data())})==0x809f0008);
        // Both local users may use the same logical save name without
        // reading, deleting or overwriting the other player's data.
        mount.mode=6;
        check(save("32HQAQdwM2o",{ptr(&mount),ptr(result.data())})==0);
        const auto first_fd=file("1G3lF1Gg1k8",{ptr("/savedata0/data"),0x602});
        check(file("4wSze92BhLI",{first_fd,ptr("P1"),2})==2 && file("UK2Tl2DWUns",{first_fd})==0);
        Mount second=mount;second.user=0x1001;
        alignas(8) std::array<char,64> second_result{};
        check(save("32HQAQdwM2o",{ptr(&second),ptr(second_result.data())})==0x809f0011);
        LocalPlayers::second_connected=true;
        check(save("32HQAQdwM2o",{ptr(&second),ptr(second_result.data())})==0);
        check(std::string(second_result.data())=="/savedata1");
        const auto second_fd=file("1G3lF1Gg1k8",{ptr("/savedata1/data"),0x602});
        check(file("4wSze92BhLI",{second_fd,ptr("P2"),2})==2 && file("UK2Tl2DWUns",{second_fd})==0);
        check(save("BMR4F-Uek3E",{ptr(second_result.data())})==0);
        LocalPlayers::second_connected=false;
        std::ifstream p1(root/"saves/CUSA00697/user-4096/synthetic/data"),p2(root/"saves/CUSA00697/user-4097/synthetic/data");
        std::string a,b;p1>>a;p2>>b;check(a=="P1" && b=="P2");
        check(save("S1GkePI17zQ",{ptr(&second)})==0x809f0011);
        check(save("BMR4F-Uek3E",{ptr(result.data())})==0);
        check(save("yKDy8S5yLA0")==0);
        std::filesystem::remove_all(root);
        std::cout<<"SaveData isolated mount, write, remount, read-only and confinement passed\n";
    }catch(const std::exception& e){if(!root.empty())std::filesystem::remove_all(root);std::cerr<<e.what()<<'\n';return 1;}
}

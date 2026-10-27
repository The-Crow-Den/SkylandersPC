// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
class KernelFile;
class SaveData {
public:
    explicit SaveData(KernelFile& files);
    ~SaveData();
    void configure(const std::string& root,const std::string& title);
    static bool supports(std::string_view identity);
    std::uint64_t call(std::string_view identity,const std::uint64_t* args);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

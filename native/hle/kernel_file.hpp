// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
class KernelFile {
public:
    KernelFile();
    ~KernelFile();
    void configure(const std::string& game_root);
    bool mount_save(const std::string& guest, const std::string& host, bool read_only);
    bool unmount_save(const std::string& guest);
    static bool supports(std::string_view identity) noexcept;
    std::uint64_t call(std::string_view identity, const std::uint64_t* arguments);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

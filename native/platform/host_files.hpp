// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string_view>
namespace SkyHost {
enum class FileAccess { Read, Write, ReadWrite };
struct FileOpen {
    FileAccess access = FileAccess::Read;
    bool append = false, create = false, truncate = false, exclusive = false, directory = false;
};
struct FileTime { std::int64_t seconds = 0, nanoseconds = 0; };
struct FileInfo {
    std::uint32_t device = 0, inode = 0;
    std::uint16_t mode = 0;
    std::uint64_t links = 0;
    std::int64_t size = 0, blocks = 0;
    std::uint32_t block_size = 0;
    FileTime atime, mtime, ctime, birthtime;
    bool regular = false, directory = false;
};
// Owning, non-inheritable file/directory capability. Child opens take exactly
// one name, relative to the held directory, and never follow symlinks/reparse
// points. Failures set native CRT errno; unknown Windows failures are diagnosed
// with an exception rather than reported as a successful/guessed operation.
class File {
public:
    File();
    ~File();
    File(File&&) noexcept;
    File& operator=(File&&) noexcept;
    File(const File&) = delete;
    File& operator=(const File&) = delete;
    bool valid() const noexcept;
    // allow_root_links preserves the trusted, user-selected Linux game-root
    // policy only. Windows refuses reparse points even in the selected root;
    // currently only local volume drive roots are supported (not UNC/SUBST).
    // Output arguments to child/duplicate operations must not alias this File.
    // create walks/creates missing components through held parents. It cannot
    // be combined with the trusted-root link exception.
    bool open_directory(const std::filesystem::path& path, bool allow_root_links = false, bool create = false);
    bool duplicate_directory(File& output) const;
    bool ensure_directory(std::string_view name, File& output) const;
    // Missing entries succeed with exists=false; unsafe links are failures.
    // Does not open file data (and therefore cannot block on a FIFO).
    bool child_info(std::string_view name, FileInfo& output, bool& exists) const;
    // Replace one regular, single-link child with a fully written/flushed
    // sibling. A failure after publication may leave the new file installed;
    // it never rolls back by deleting that installed file. POSIX also fsyncs
    // the parent; Windows flushes the renamed file, without claiming directory
    // fsync/power-loss equivalence.
    bool write_atomic(std::string_view name, const void* data, std::size_t size) const;
    // single_link requires a directory or regular file with exactly one link;
    // validate that before truncation so save hard links cannot modify outside data.
    bool open_child(std::string_view name, const FileOpen& options, bool single_link, File& output) const;
    bool stat(FileInfo& output) const;
    std::int64_t read(void* data, std::size_t size);
    std::int64_t read_at(void* data, std::size_t size, std::int64_t offset);
    std::int64_t write(const void* data, std::size_t size);
    std::int64_t write_at(const void* data, std::size_t size, std::int64_t offset);
    std::int64_t seek(std::int64_t offset, int origin);
    int sync();
    int truncate(std::int64_t size);
    int close();
private:
    bool create_temporary(std::string_view name, File& output) const;
    bool publish_temporary(File& temporary, std::string_view source, std::string_view target, bool& published) const;
    bool discard_temporary(File& temporary, std::string_view name) const;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}

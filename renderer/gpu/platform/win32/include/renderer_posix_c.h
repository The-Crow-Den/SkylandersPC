// SPDX-License-Identifier: GPL-2.0-or-later
// renderer Windows: the POSIX file and time calls of the runtime (src/, C) with Linux semantics
// (posix_win32.cpp): struct stat with st_mtim/st_blocks, dirent with d_type, directory fds
// (O_DIRECTORY, openat, fstatat, fdopendir, dirfd), pread/pwrite at an offset without moving
// the file position, rename over an existing file, binary mode always. Paths are UTF-8 (the
// executable's manifest sets the UTF-8 code page). Macros rename the calls: C only, after the
// UCRT headers that declare the originals.
#pragma once
#ifndef __cplusplus

#include <limits.h>
#include <stdlib.h>
#include <direct.h>
#include <fcntl.h>
#include <io.h>
#include <process.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#include <dirent.h>
#include <pthread.h>

#ifndef PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP
#define PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP PTHREAD_RECURSIVE_MUTEX_INITIALIZER
#endif

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#ifndef O_NONBLOCK
#define O_NONBLOCK 0
#endif
#ifndef O_SYNC
#define O_SYNC 0
#endif
#ifndef O_DIRECTORY
#define O_DIRECTORY 0x200000
#endif
#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif
#define AT_FDCWD (-100)
#define AT_SYMLINK_NOFOLLOW 0x100
#define AT_REMOVEDIR 0x200

struct sky_stat {
    uint64_t st_dev, st_ino;
    uint32_t st_mode, st_nlink, st_uid, st_gid;
    uint64_t st_rdev;
    int64_t st_size, st_blksize, st_blocks;
    struct timespec st_atim, st_mtim, st_ctim;
};
int sky_stat(const char* path, struct sky_stat* out);
int sky_fstat(int fd, struct sky_stat* out);
int sky_fstatat(int dir, const char* path, struct sky_stat* out, int flags);
#define stat sky_stat
#define lstat sky_stat
#define fstat sky_fstat
#define fstatat sky_fstatat

int sky_open(const char* path, int flags, ...);
int sky_openat(int dir, const char* path, int flags, ...);
int sky_close(int fd);
ssize_t sky_pread(int fd, void* buffer, size_t size, int64_t offset);
ssize_t sky_pwrite(int fd, const void* buffer, size_t size, int64_t offset);
int sky_fsync(int fd);
int sky_ftruncate(int fd, int64_t size);
int sky_rename(const char* from, const char* to);
int sky_mkdir(const char* path, int mode);
int sky_unlinkat(int dir, const char* path, int flags);
int sky_mkdirat(int dir, const char* path, int mode);
int sky_renameat(int from_dir, const char* from, int to_dir, const char* to);
ssize_t sky_readlink(const char* path, char* out, size_t size);
#define open sky_open
#define openat sky_openat
#define close sky_close
#define pread sky_pread
#define pwrite sky_pwrite
#define fsync sky_fsync
#define ftruncate sky_ftruncate
#define rename sky_rename
#define mkdir(path, mode) sky_mkdir(path, mode)
#define unlinkat sky_unlinkat
#define mkdirat sky_mkdirat
#define renameat sky_renameat
#define readlink sky_readlink

#define DT_UNKNOWN 0
#define DT_DIR 4
#define DT_REG 8
#define DT_LNK 10
struct sky_dirent {
    uint64_t d_ino;
    unsigned char d_type;
    char d_name[1024];
};
typedef struct sky_DIR sky_DIR;
sky_DIR* sky_opendir(const char* path);
sky_DIR* sky_fdopendir(int fd);
struct sky_dirent* sky_readdir(sky_DIR* dir);
int sky_closedir(sky_DIR* dir);
int sky_dirfd(sky_DIR* dir);
void sky_rewinddir(sky_DIR* dir);
#define dirent sky_dirent
#define DIR sky_DIR
#define opendir sky_opendir
#define fdopendir sky_fdopendir
#define readdir sky_readdir
#define closedir sky_closedir
#define dirfd sky_dirfd
#define rewinddir sky_rewinddir

static inline struct tm* localtime_r(const time_t* t, struct tm* out) {
    return localtime_s(out, t) == 0 ? out : NULL;
}
static inline struct tm* gmtime_r(const time_t* t, struct tm* out) {
    return gmtime_s(out, t) == 0 ? out : NULL;
}
/// tm_gmtoff (east of UTC, seconds) of a local time.
long sky_gmtoff(const struct tm* local);

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif
static inline char* realpath(const char* path, char* out) {
    return _fullpath(out, path, PATH_MAX);
}

/// An anonymous file (a temporary one, deleted when closed).
#define MFD_CLOEXEC 1
int memfd_create(const char* name, unsigned flags);

/// The calling thread's stack [low, high) (pthread_getattr_np's use here).
void sky_thread_stack(uintptr_t* low, uintptr_t* high);

/// C11 aligned_alloc: the UCRT has none. Its blocks are released with _aligned_free (the
/// runtime's are never released: guest threads' TLS).
#define aligned_alloc(alignment, size) _aligned_malloc(size, alignment)

/// Guest TLS (runtime_thread.c): the loader rewrote the game's `mov r64, fs:[0]` to read a TEB
/// TLS slot (gs:[0x1480 + 8 * slot]); each guest thread stores its TCB there.
int sky_guest_tls_slot(void);
void sky_guest_tls_set(void* tcb);

/// getrandom (sys/random.h): from the system's generator.
ssize_t getrandom(void* buffer, size_t size, unsigned flags);

#endif // !__cplusplus

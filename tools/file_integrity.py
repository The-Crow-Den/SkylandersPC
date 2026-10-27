# SPDX-License-Identifier: GPL-3.0-or-later
"""Operation-scoped file verification; no persistent trust in filesystem metadata."""
import stat


class VerifiedDigests:
    """Share a verified hash between unchanged hard-link names during one operation.

    Every use checks device/inode, size, mtime and ctime. A new operation must
    create a new instance, so an ordinary launch always hashes its input files.
    """
    def __init__(self, reader):
        self.reader=reader
        self.verified={}

    @staticmethod
    def stamp(path):
        info=path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):raise ValueError('file verification requires a regular file')
        return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)

    def remember(self,path,before,digest):
        if self.stamp(path)!=before:raise ValueError('asset changed while hashing or reading')
        self.verified[before]=digest

    def __call__(self,path):
        before=self.stamp(path)
        if before in self.verified:return self.verified[before]
        result=self.reader(path)
        self.remember(path,before,result)
        return result

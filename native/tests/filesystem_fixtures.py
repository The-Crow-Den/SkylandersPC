# SPDX-License-Identifier: GPL-3.0-or-later
"""Real directory symlinks/junctions for native confinement tests."""
import ctypes
from ctypes import wintypes
import os
import struct

def directory_link(link, target):
    if os.name != 'nt':
        link.symlink_to(target, target_is_directory=True)
        return
    # A real mount-point reparse buffer, not a mocked reparse query. Junctions
    # do not need the developer-mode privilege required by file symlinks.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    control = kernel.DeviceIoControl
    control.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                        wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    control.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    link.mkdir()
    handle = create(str(link), 0x40000000, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    substitute = ('\\??\\' + str(target.resolve())).encode('utf-16-le')
    display = str(target.resolve()).encode('utf-16-le')
    names = substitute + b'\0\0' + display + b'\0\0'
    record = struct.pack('<I6H', 0xa0000003, 8 + len(names), 0,
                         0, len(substitute), len(substitute) + 2, len(display)) + names
    data = ctypes.create_string_buffer(record)
    returned = wintypes.DWORD()
    try:
        if not control(handle, 0x900a4, data, len(record), None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close(handle)

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


def frame_permissions(path, public=False, null_dacl=False):
    if os.name != 'nt':
        path.chmod((0o755 if public else 0o700) if path.is_dir() else (0o644 if public else 0o600))
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    current = kernel.GetCurrentProcess
    current.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    free = kernel.LocalFree
    free.argtypes = [wintypes.LPVOID]
    free.restype = wintypes.LPVOID
    open_token = security.OpenProcessToken
    open_token.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    open_token.restype = wintypes.BOOL
    get_token = security.GetTokenInformation
    get_token.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get_token.restype = wintypes.BOOL
    sid_string = security.ConvertSidToStringSidW
    sid_string.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    sid_string.restype = wintypes.BOOL
    convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    assign = security.SetFileSecurityW
    assign.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID]
    assign.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not open_token(current(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    name = wintypes.LPWSTR()
    descriptor = wintypes.LPVOID()
    try:
        data = ctypes.create_string_buffer(512)
        used = wintypes.DWORD()
        if not get_token(token, 1, data, len(data), ctypes.byref(used)):
            raise ctypes.WinError(ctypes.get_last_error())
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first member is PSID.
        sid = ctypes.cast(data, ctypes.POINTER(wintypes.LPVOID))[0]
        if not sid_string(sid, ctypes.byref(name)):
            raise ctypes.WinError(ctypes.get_last_error())
        acl = f'D:P(A;;FA;;;{name.value})(A;;FA;;;SY)(A;;FA;;;BA)'
        if public:
            acl += '(A;;FR;;;WD)'
        if null_dacl:
            acl = 'D:NO_ACCESS_CONTROL'
        if not convert(f'O:{name.value}' + acl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not assign(str(path), 0x80000005, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if descriptor:
            free(descriptor)
        if name:
            free(ctypes.cast(name, wintypes.LPVOID))
        close(token)

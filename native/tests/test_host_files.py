# SPDX-License-Identifier: GPL-3.0-or-later
"""Real filesystem confinement and I/O, including Windows junctions."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
import mmap
import queue
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

from filesystem_fixtures import directory_link

BINARY = Path(sys.argv.pop(1)).resolve()


def frame_permissions(path, public=False, null_dacl=False):
    if os.name != 'nt':
        path.chmod(0o644 if public else 0o600)
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


def frame_file(path, *, public=False, null_dacl=False, generation=2, magic=0x534b594d, size=64+3840*2160*4):
    with path.open('x+b') as file:
        file.truncate(size)
        file.write(struct.pack('<5I', magic, generation, 2, 1, 8))
        file.seek(64)
        file.write(b'RGBAdata')
    frame_permissions(path, public=public, null_dacl=null_dacl)


@contextmanager
def deny_delete(path):
    if os.name != 'nt':
        yield
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not close(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class HostFilesTests(unittest.TestCase):
    def prepare(self, parent):
        root = parent / 'sandbox_λ'
        (root / 'game').mkdir(parents=True)
        (root / 'save').mkdir()
        (root / 'outside').mkdir()
        (root / 'game/data.bin').write_bytes(b'abcdef')
        (root / 'game/unicode_λ.bin').write_bytes(b'utf8')
        (root / 'outside.bin').write_bytes(b'outside')
        (root / 'save/locked').write_bytes(b'original')
        (root / 'outside/secret.bin').write_bytes(b'outside')
        os.link(root / 'outside.bin', root / 'save/hardlink')
        if os.name != 'nt':
            (root / 'game/link.bin').symlink_to(root / 'outside.bin')
            os.mkfifo(root / 'game/fifo')
        directory_link(root / 'game/escape', root / 'outside')
        directory_link(root / 'game_alias', root / 'game')
        directory_link(root / 'create_escape', root / 'outside')
        directory_link(root / 'metadata_escape', root / 'outside')
        directory_link(root / 'metadata_file_escape', root / 'outside')
        directory_link(root / 'move_escape', root / 'outside')
        frame_file(root / 'frame.rgba')
        frame_file(root / 'frame-public.rgba', public=True)
        frame_file(root / 'frame-short.rgba', size=128)
        frame_file(root / 'frame-odd.rgba', generation=3)
        frame_file(root / 'frame-bad.rgba', magic=0)
        if os.name == 'nt':
            frame_file(root / 'frame-null-dacl.rgba', null_dacl=True)
            directory_link(root / 'frame-link.rgba', root / 'outside')
        else:
            (root / 'frame-link.rgba').symlink_to(root / 'frame.rgba')
        directory_link(root / 'frame-parent', root)
        return root

    def run_native(self, root, *args):
        return subprocess.run([str(BINARY), str(root).encode('utf-8').hex(), *args],
                              capture_output=True, encoding='utf-8', timeout=30)

    def test_handles_and_guest_file_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.prepare(Path(temporary))
            with deny_delete(root / 'save/locked'):
                result = self.run_native(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('file capability tests passed', result.stdout)
            self.assertEqual((root / 'outside.bin').read_bytes(), b'outside')
            self.assertEqual((root / 'outside/secret.bin').read_bytes(), b'outside')
            self.assertEqual((root / 'game/data.bin').read_bytes(), b'abcdef')
            self.assertEqual((root / 'save/progress').read_bytes(), b'proXendz')
            self.assertEqual((root / 'save/locked').read_bytes(), b'original')
            self.assertEqual((root / 'save/guest.bin').read_bytes(), b'proXress')
            self.assertEqual((root / 'created/nested/held/inside/marker').read_bytes(), b'held')
            self.assertFalse((root / 'outside/inside').exists())
            self.assertFalse((root / 'outside/param.bin').exists())
            quarantined = list((root / 'metadata-saves/CUSA00697/user-4096/.deleted').glob('*.sce_sys'))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual((quarantined[0] / 'icon0.png').read_bytes(), b'icon')
            self.assertEqual((root / 'moves/trash/renamed/marker').read_bytes(), b'retained')
            self.assertEqual((root / 'moves/trash/existing/marker').read_bytes(), b'untouched')

    def test_live_frame_mapping_observes_only_completed_generations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'mailbox_λ'
            root.mkdir()
            frame_file(root / 'frame.rgba')
            with (root / 'frame.rgba').open('r+b') as file, mmap.mmap(file.fileno(), 0) as memory:
                with subprocess.Popen([str(BINARY), str(root).encode('utf-8').hex(), 'frame'],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, encoding='utf-8') as process:
                    lines = queue.Queue()
                    def read_lines():
                        for line in process.stdout:
                            lines.put(line.rstrip())
                    reader = threading.Thread(target=read_lines)
                    reader.start()
                    try:
                        self.assertEqual(lines.get(timeout=15), 'ready')
                        def read():
                            process.stdin.write('read\n')
                            process.stdin.flush()
                            return lines.get(timeout=15)
                        self.assertEqual(read(), '1 2 2 1 5247424164617461')
                        self.assertEqual(read(), '0 2 2 1 5247424164617461')
                        # Writer advertises an incomplete generation before changing bytes.
                        struct.pack_into('<I', memory, 4, 3)
                        memory[64:72] = b'newFRAME'
                        self.assertEqual(read(), '0 2 2 1 5247424164617461')
                        struct.pack_into('<I', memory, 4, 4)
                        self.assertEqual(read(), '1 4 2 1 6e65774652414d45')
                        struct.pack_into('<I', memory, 4, 5)
                        struct.pack_into('<I', memory, 8, 3841)
                        struct.pack_into('<I', memory, 4, 6)
                        self.assertEqual(read(), '0 4 2 1 6e65774652414d45')
                        struct.pack_into('<I', memory, 4, 7)
                        struct.pack_into('<I', memory, 8, 2)
                        struct.pack_into('<I', memory, 4, 8)
                        self.assertEqual(read(), '1 8 2 1 6e65774652414d45')
                        process.stdin.write('quit\n')
                        process.stdin.flush()
                        self.assertEqual(process.wait(timeout=15), 0, process.stderr.read())
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=15)
                        reader.join(15)
                        self.assertFalse(reader.is_alive())

    def test_directory_replacement_never_reaches_outside_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.prepare(Path(temporary))
            (root / 'game/stable').mkdir()
            (root / 'game/stable/secret.bin').write_bytes(b'inside')
            (root / 'game/switch').mkdir()
            (root / 'game/switch/secret.bin').write_bytes(b'inside')
            directory_link(root / 'game/attack', root / 'outside')
            stop = threading.Event()
            errors = []
            swaps = []

            def replace():
                try:
                    game = root / 'game'
                    while not stop.is_set():
                        (game / 'switch').rename(game / 'held')
                        (game / 'attack').rename(game / 'switch')
                        (game / 'switch').rename(game / 'attack')
                        (game / 'held').rename(game / 'switch')
                        swaps.append(1)
                except BaseException as error:
                    errors.append(error)

            attacker = threading.Thread(target=replace)
            attacker.start()
            try:
                result = self.run_native(root, 'race')
            finally:
                stop.set()
                attacker.join(15)
            self.assertFalse(attacker.is_alive())
            self.assertFalse(errors, errors)
            self.assertTrue(swaps, 'replacement did not run')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('confined reads=', result.stdout)
            self.assertEqual((root / 'outside/secret.bin').read_bytes(), b'outside')


if __name__ == '__main__':
    unittest.main()

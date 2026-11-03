# SPDX-License-Identifier: GPL-3.0-or-later
"""Real filesystem confinement and I/O, including Windows junctions."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()


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

# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded RGBA mailbox for the menu drawn into the game's Vulkan frame."""
import mmap
import struct

try:
    from .overlay_protocol import private_directory
except ImportError:
    from overlay_protocol import private_directory

MAGIC = 0x534B594D
WIDTH, HEIGHT, HEADER = 3840, 2160, 64
SIZE = HEADER + WIDTH * HEIGHT * 4


class Frames:
    def __init__(self, directory):
        self.path = private_directory(directory) / 'frame.rgba'
        self.file = self.path.open('x+b')
        self.path.chmod(0o600)
        self.file.truncate(SIZE)
        self.memory = mmap.mmap(self.file.fileno(), SIZE)
        self.sequence = 0
        struct.pack_into('<IIIII', self.memory, 0, MAGIC, 0, 0, 0, 0)

    def write(self, width, height, pixels):
        if not (0 < width <= WIDTH and 0 < height <= HEIGHT and len(pixels) == width * height * 4):
            raise ValueError('invalid menu frame')
        # Odd means a write is in progress. The reader accepts only matching even
        # generations before and after copying, so partial frames are never drawn.
        self.sequence = (self.sequence + 2) & 0xfffffffe or 2
        struct.pack_into('<I', self.memory, 4, self.sequence - 1)
        struct.pack_into('<III', self.memory, 8, width, height, len(pixels))
        self.memory[HEADER:HEADER + len(pixels)] = pixels
        struct.pack_into('<I', self.memory, 4, self.sequence)

    def close(self):
        self.memory.close()
        self.file.close()

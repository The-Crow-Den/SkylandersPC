# SPDX-License-Identifier: GPL-3.0-or-later
import struct
import tempfile
import unittest
from pathlib import Path

from tools.overlay_frames import Frames, HEADER, MAGIC, SIZE


class OverlayFrameTests(unittest.TestCase):
    def test_rgba_frames_publish_complete_even_generations(self):
        with tempfile.TemporaryDirectory() as directory:
            frames=Frames(directory)
            try:
                self.assertEqual(frames.path.stat().st_mode&0o777,0o600)
                self.assertEqual(frames.path.stat().st_size,SIZE)
                frames.write(2,1,b'\xff\0\0\xff\0\0\0\0')
                magic,generation,width,height,size=struct.unpack_from('<5I',frames.memory)
                self.assertEqual((magic,generation,width,height,size),(MAGIC,2,2,1,8))
                self.assertEqual(frames.memory[HEADER:HEADER+8],b'\xff\0\0\xff\0\0\0\0')
                frames.write(1,1,b'\0\xff\0\xff')
                self.assertEqual(struct.unpack_from('<I',frames.memory,4)[0],4)
            finally:frames.close()

    def test_rejects_invalid_dimensions_lengths_and_existing_mailbox(self):
        with tempfile.TemporaryDirectory() as directory:
            frames=Frames(directory)
            try:
                for width,height,pixels in [(0,1,b''),(3841,1,b''),(1,2161,b''),(1,1,b'bad')]:
                    with self.assertRaises(ValueError):frames.write(width,height,pixels)
                with self.assertRaises(FileExistsError):Frames(directory)
            finally:frames.close()


if __name__=='__main__':unittest.main()

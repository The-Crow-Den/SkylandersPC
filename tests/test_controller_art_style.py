# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from tools import controller_art


class DarkButtonTests(unittest.TestCase):
    def test_coloured_disc_becomes_dark_with_coloured_letter(self):
        green=(80,190,70,255);white=(255,255,255,255);clear=(0,0,0,0)
        pixels=bytes(sum([green,white,green,clear],()))
        out=controller_art.dark_button(pixels,4,1)
        self.assertEqual(tuple(out[0:3]),controller_art.BUTTON)
        self.assertEqual(tuple(out[4:7]),green[:3])
        self.assertEqual(out[12:16],bytes(clear))


if __name__=='__main__':
    unittest.main()

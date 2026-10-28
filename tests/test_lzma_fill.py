# SPDX-License-Identifier: GPL-3.0-or-later
import lzma
import random
import unittest

from tools import lzma_fill


def decode(stream, size):
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[dict(
        id=lzma.FILTER_LZMA1, dict_size=32768, lc=3, lp=0, pb=2)])
    return decoder.decompress(stream, max_length=size)


class LzmaFillTests(unittest.TestCase):
    def test_round_trip_for_greedy_and_noisy_parses(self):
        rng = random.Random(7)
        data = bytes(rng.randrange(6) for _ in range(6000)) + rng.randbytes(500) + bytes(1500)
        for noise in (0.0, 0.3, 1.0):
            with self.subTest(noise=noise):
                self.assertEqual(decode(lzma_fill.encode(data, 32768, noise), len(data)), data)

    def test_noise_lengthens_and_is_deterministic(self):
        data = bytes(random.Random(8).randrange(4) for _ in range(8000))
        self.assertGreater(len(lzma_fill.encode(data, 32768, 1.0)), len(lzma_fill.encode(data, 32768)))
        self.assertEqual(lzma_fill.encode(data, 32768, 0.5), lzma_fill.encode(data, 32768, 0.5))

    def test_fill_lands_in_window(self):
        data = bytes(random.Random(9).randrange(4) for _ in range(8000))
        base = len(lzma_fill.encode(data, 32768))
        stream = lzma_fill.fill(data, 32768, base + 400, base + 700)
        self.assertTrue(base + 400 <= len(stream) <= base + 700)
        self.assertEqual(decode(stream, len(data)), data)

    def test_impossible_windows_are_refused(self):
        data = bytes(4000)
        with self.assertRaisesRegex(ValueError, 'large enough'):
            lzma_fill.fill(data, 32768, 50000, 60000)
        with self.assertRaisesRegex(ValueError, 'fit'):
            lzma_fill.fill(random.Random(1).randbytes(4000), 32768, 10, 100)


if __name__ == '__main__':
    unittest.main()

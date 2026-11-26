# SPDX-License-Identifier: GPL-3.0-or-later
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from process_text import utf8_reader


class Process:
    pass


class ProcessTextTest(unittest.TestCase):
    def test_character_split_between_reads(self):
        process = Process();data = 'Installing game… We’ll'.encode()
        cut = data.index('…'.encode()) + 1
        text = utf8_reader(None, process).decode(data[:cut]) + utf8_reader(None, process).decode(data[cut:])
        self.assertEqual(text, 'Installing game… We’ll')

    def test_each_process_has_its_own_decoder(self):
        a, b = Process(), Process()
        self.assertIsNot(utf8_reader(None, a), utf8_reader(None, b))


if __name__ == '__main__':
    unittest.main()

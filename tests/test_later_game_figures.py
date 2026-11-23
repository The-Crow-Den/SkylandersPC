# SPDX-License-Identifier: GPL-3.0-or-later
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import figure_collection


class LaterGameFigures(unittest.TestCase):
    def test_creatable_and_labelled(self):
        self.assertTrue(figure_collection.creatable(625, 0))
        self.assertEqual(figure_collection.later_game(625), 'Imaginators')
        self.assertEqual(figure_collection.later_game(3400), 'SuperChargers')
        self.assertIsNone(figure_collection.later_game(1))


if __name__ == '__main__':
    unittest.main()

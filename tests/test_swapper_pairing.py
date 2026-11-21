# SPDX-License-Identifier: GPL-3.0-or-later
import sys, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from launcher_portal import pair_swappers, Swapper
import figure_data


def entry(name, identity):
    figure = SimpleNamespace(identity=identity, variant=0, half=figure_data.swapper_half(identity), kind='character', nickname='')
    return SimpleNamespace(name=name, figure=figure, path=Path(f'/{name}.sky'), created=True, working=None)


class SwapperPairingTest(unittest.TestCase):
    def test_halves_of_one_swapper_become_one_figure(self):
        figures = pair_swappers([entry('Spyro', 1), entry('Blast Zone (Top)', 2000), entry('Blast Zone (Bottom)', 1000),
                                 entry('Boom Jet (Bottom)', 1005)])
        self.assertEqual(figures[0].name, 'Spyro')
        swappers = [f for f in figures if isinstance(f, Swapper)]
        self.assertEqual([s.name for s in swappers], ['Blast Zone', 'Boom Jet'])
        self.assertTrue(swappers[0].top and swappers[0].bottom)
        self.assertIsNone(swappers[1].top)
        self.assertTrue(swappers[0].has('/Blast Zone (Bottom).sky'))


if __name__ == '__main__':
    unittest.main()

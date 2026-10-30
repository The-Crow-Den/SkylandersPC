# SPDX-License-Identifier: GPL-3.0-or-later
"""Swap Force swapper halves through the launcher, with synthetic tags only."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import figure_collection as fc
from tools import figure_data as fd
from tools import launcher_library
from tools import launcher_model as model
from tests.test_figure_data import SEED, played


class SwapperFigureTests(unittest.TestCase):
    def test_halves_are_identified_and_creatable(self):
        self.assertEqual((fd.swapper_half(1000), fd.swapper_half(1015)), ('bottom', 'bottom'))
        self.assertEqual((fd.swapper_half(2000), fd.swapper_half(2015)), ('top', 'top'))
        for identity in (14, 999, 1016, 1999, 2016, 3000):
            self.assertIsNone(fd.swapper_half(identity))
        self.assertTrue(fc.creatable(1010, 0) and fc.creatable(2010, 0x2402))
        self.assertFalse(fc.creatable(1500, 0) or fc.creatable(2010, 0x4000))

    def test_superchargers_vehicles_are_creatable_and_read_only(self):
        self.assertEqual(fd.kind(3224), 'vehicle')
        self.assertTrue(fc.creatable(3224, 0) and fc.creatable(3224, 0x4402))
        self.assertFalse(fd.Figure(played(identity=3224), SEED).editable)

    def test_played_halves_stay_read_only(self):
        top = fd.Figure(played(identity=2010), SEED)
        self.assertEqual((top.kind, top.half), ('character', 'top'))
        self.assertFalse(top.editable)
        self.assertTrue(fd.Figure(played(identity=14), SEED).editable)

    def test_starting_bottom_half_is_forwarded_after_the_top(self):
        value = dict(model.DEFAULTS, figure='/figures/top.sky', figure_bottom='/figures/bottom half.sky')
        argv = model.command('/checkout', '/python', value)
        self.assertEqual(argv[argv.index('--figure-bottom') + 1], value['figure_bottom'])
        self.assertLess(argv.index('--figure'), argv.index('--figure-bottom'))
        alone = dict(model.DEFAULTS, figure_bottom='/figures/bottom.sky')
        self.assertNotIn('--figure-bottom', model.command('/checkout', '/python', alone))

    def test_preferences_without_a_bottom_half_still_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.json'
            old = dict(model.DEFAULTS); old.pop('figure_bottom')
            path.write_text(json.dumps(old))
            self.assertEqual(model.load(path)['figure_bottom'], '')
        with self.assertRaises(ValueError):
            model.validate(dict(model.DEFAULTS, figure_bottom='bad\0path'))

    def test_library_forgets_a_bottom_half_without_a_top(self):
        with tempfile.TemporaryDirectory() as directory:
            top = Path(directory) / 'top.sky'; bottom = Path(directory) / 'bottom.sky'
            top.write_bytes(b'\0' * 1024); bottom.write_bytes(b'\0' * 1024)
            path = Path(directory) / 'library.json'
            value = launcher_library.defaults()
            value.update(portal=str(top), portal_bottom=str(bottom))
            path.write_text(json.dumps(value))
            self.assertEqual(launcher_library.load(path)['portal_bottom'], str(bottom))
            value.update(portal=None); path.write_text(json.dumps(value))
            self.assertIsNone(launcher_library.load(path)['portal_bottom'])


if __name__ == '__main__':
    unittest.main()

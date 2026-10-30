# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic checks of launcher controller navigation and the controller file picker.

No controller, game or SDL is needed: pad events are injected as SDL-shaped tuples."""
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from tools import launcher_files as files
from tools import launcher_gamepad as gamepad
try:
    from PyQt6.QtWidgets import QApplication, QLineEdit
    from tools.launcher import Launcher
    QT = True
except ImportError:
    QT = False

ROOT = Path(__file__).resolve().parents[1]


class PureTests(unittest.TestCase):
    def test_buttons_map_to_actions(self):
        self.assertEqual([gamepad.button_action(b) for b in (0, 1, 9, 10, 11, 14, 7)],
                         ['accept', 'back', 'prev_page', 'next_page', 'up', 'right', None])

    def test_stick_uses_hysteresis(self):
        stick = gamepad.Stick()
        self.assertIsNone(stick.update(1, 15000))
        self.assertEqual(stick.update(1, 25000), ('press', 'down'))
        self.assertIsNone(stick.update(1, 15000))           # still held between thresholds
        self.assertEqual(stick.update(1, 2000), ('release', 'down'))
        self.assertEqual(stick.update(0, -30000), ('press', 'left'))
        self.assertIsNone(stick.update(4, 32767))            # triggers are not directions

    def test_repeat_timing(self):
        repeat = gamepad.Repeater(); repeat.press('up', 10.0)
        self.assertIsNone(repeat.tick(10.2))
        self.assertEqual(repeat.tick(10.41), 'up')
        self.assertIsNone(repeat.tick(10.45))
        self.assertEqual(repeat.tick(10.53), 'up')
        repeat.release('up'); self.assertIsNone(repeat.tick(20))

    def test_nearest_prefers_aligned_controls(self):
        origin = (100, 100, 80, 30)
        below = [(100, 200, 80, 30), (600, 140, 80, 30), (100, 400, 80, 30)]
        self.assertEqual(gamepad.nearest(origin, below, 'down'), 0)
        # A row's switch far to the right is still reachable moving down...
        self.assertEqual(gamepad.nearest(origin, [(900, 160, 40, 30)], 'down'), 0)
        # ...but a far corner button does not steal a sideways press.
        self.assertIsNone(gamepad.nearest(origin, [(220, 700, 40, 30)], 'right'))
        self.assertIsNone(gamepad.nearest(origin, below, 'up'))

    def test_game_mode_detection(self):
        self.assertTrue(gamepad.game_mode({'SteamGamepadUI': '1'}))
        self.assertTrue(gamepad.game_mode({'XDG_CURRENT_DESKTOP': 'gamescope'}))
        self.assertFalse(gamepad.game_mode({'XDG_CURRENT_DESKTOP': 'KDE'}))


class PickerHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        (self.home / 'Downloads/deep/er').mkdir(parents=True); (self.home / '.hidden').mkdir()
        for name in ('Downloads/Game.PKG', 'Downloads/deep/er/update.pkg', 'Downloads/notes.txt', '.hidden/x.pkg'):
            (self.home / name).write_bytes(b'x')

    def tearDown(self): self.temp.cleanup()

    def test_places_and_listing(self):
        labels = [label for label, _ in files.places(self.home, {'USER': 'nobody-here'})]
        self.assertEqual(labels[:2], ['Downloads', 'Home'])
        folders, found = files.listing(self.home / 'Downloads', ('.pkg',))
        self.assertEqual([p.name for p in folders], ['deep']); self.assertEqual([p.name for p in found], ['Game.PKG'])
        self.assertEqual(files.listing(self.home, folders_only=True)[0], [self.home / 'Downloads'])

    def test_scan_finds_nested_files_but_not_hidden(self):
        found = files.scan([self.home], ('.pkg',))
        self.assertEqual(sorted(p.name for p in found), ['Game.PKG', 'update.pkg'])
        self.assertEqual(files.scan([self.home], ('.pkg',), depth=1), [self.home / 'Downloads/Game.PKG'])
        self.assertEqual(len(files.scan([self.home], ('.pkg',), limit=1)), 1)

    def test_size_text(self):
        self.assertEqual(files.size_text(512), '512 B'); self.assertEqual(files.size_text(3 * 1024 ** 3), '3.0 GB')


class FakePads:
    def __init__(self): self.queue = []
    def poll(self):
        queue, self.queue = self.queue, []; return queue
    def press(self, button): self.queue += [('down', button, 0), ('up', button, 0)]


@unittest.skipUnless(QT, 'optional PyQt6 is not installed')
class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = Launcher(Path(self.temp.name)); self.window.resize(1280, 800); self.window.show()
        self.pads = FakePads(); self.window.gamepad.source = self.pads; self.window.primary.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.window.gamepad.clock.stop(); self.window.close(); self.temp.cleanup()

    def press(self, *buttons):
        for button in buttons:
            self.pads.press(button); self.window.gamepad.tick()
            for _ in range(3): self.app.processEvents()

    def test_library_fits_steam_deck_and_moves_focus(self):
        self.assertLessEqual(self.window.minimumSize().width(), 1280); self.assertLessEqual(self.window.minimumSize().height(), 800)
        self.press(14)  # D-pad right: INSTALL → game menu
        self.assertEqual(self.window.focusWidget().text(), '•••')
        ring = self.window.gamepad.rings[self.window]
        self.assertTrue(ring.isVisible()); self.assertTrue(ring.geometry().contains(self.window.focusWidget().geometry().center()))

    def test_settings_page_tabs_and_back(self):
        self.window.game_settings(); self.app.processEvents(); self.window.settings_page.nav[0].setFocus()
        self.press(10)  # RB
        self.assertEqual(self.window.settings_page.pages.currentIndex(), 1)
        self.press(9, 9)  # LB twice wraps to the log
        self.assertEqual(self.window.settings_page.pages.currentIndex(), len(self.window.settings_page.nav) - 1)
        self.press(1)  # B
        self.assertIs(self.window.views.currentWidget(), self.window.canvas)

    def test_on_screen_keyboard_edits_line(self):
        field = QLineEdit(self.window); field.setText('ab')
        keyboard = gamepad.OnScreenKeyboard(field); keyboard.type('c')
        self.assertTrue(keyboard.gamepad_action('x')); self.assertTrue(keyboard.gamepad_action('menu'))
        keyboard.accept(); self.assertEqual(field.text(), 'ab ')

    def test_controller_picker_chooses_file(self):
        downloads = Path(self.temp.name) / 'Downloads'; downloads.mkdir(); (downloads / 'game.pkg').write_bytes(b'x')
        picker = files.Picker(self.window, 'Choose', ('.pkg',), str(downloads))
        rows = [picker.list.item(i).text() for i in range(picker.list.count())]
        self.assertTrue(rows[0].startswith('‹')); self.assertTrue(any('game.pkg' in row for row in rows))
        picker.open_item(next(picker.list.item(i) for i in range(picker.list.count()) if 'game.pkg' in picker.list.item(i).text()))
        self.assertEqual(picker.chosen, str(downloads / 'game.pkg'))

    def test_running_game_keeps_the_controller(self):
        self.window.process = object()
        try: self.assertIsNone(self.window.gamepad.target())
        finally: self.window.process = None


class PcMenuQuitTests(unittest.TestCase):
    def test_menu_offers_quit_to_launcher(self):
        html = (ROOT / 'tools/pc_menu/index.html').read_text(); script = (ROOT / 'tools/pc_menu/menu.js').read_text()
        bridge = (ROOT / 'native/pc_overlay_bridge.cpp').read_text()
        self.assertIn('data-quit', html); self.assertIn("send('quit')", script)
        self.assertIn('verb=="quit"', bridge)


if __name__ == '__main__':
    unittest.main()

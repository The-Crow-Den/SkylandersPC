# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
import unittest
from tools import launcher_menu_tip


class MenuTipTests(unittest.TestCase):
    def test_shown_once_per_user(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(launcher_menu_tip.seen(root))
            launcher_menu_tip.mark(root)
            self.assertTrue(launcher_menu_tip.seen(root))

    def test_unreadable_record_shows_the_card_again(self):
        with tempfile.TemporaryDirectory() as root:
            path=launcher_menu_tip.path(root);path.parent.mkdir(parents=True);path.write_text('not json', encoding='utf-8')
            self.assertFalse(launcher_menu_tip.seen(root))
            launcher_menu_tip.mark(root);self.assertTrue(launcher_menu_tip.seen(root))


if __name__=='__main__':
    unittest.main()

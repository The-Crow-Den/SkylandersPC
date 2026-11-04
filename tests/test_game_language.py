# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest

from tools import game_language, launcher_model

ROOT = Path(__file__).resolve().parents[1]


class GameLanguageTests(unittest.TestCase):
    def test_title_profiles_choose_or_fall_back(self):
        self.assertEqual(game_language.choose(ROOT, 'trap-team', 'fr-CA'), ('fr-CA', None))
        language, note = game_language.choose(ROOT, 'swap-force', 'fr-FR')
        self.assertEqual(language, 'en-US')
        self.assertIn('not offered', note)
        with self.assertRaises(ValueError):
            game_language.choose(ROOT, 'trap-team', 'xx-YY')
        self.assertEqual(game_language.narration('en-GB'), 'English')
        self.assertEqual(game_language.narration('es-419'), 'Spanish')
        self.assertIsNone(game_language.narration('ja-JP'))

    def test_invalid_profile_list_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'profiles').mkdir()
            (root / 'profiles/game.json').write_text(json.dumps({'languages': ['en-US', 'klingon']}))
            with self.assertRaises(ValueError):
                game_language.offered(root, 'game')
            self.assertEqual(launcher_model.languages(root), ['en-US'])

    def test_launcher_passes_language(self):
        value = dict(launcher_model.DEFAULTS, language='de-DE')
        argv = launcher_model.command('/project', 'python', value)
        self.assertEqual(argv[argv.index('--language') + 1], 'de-DE')
        with self.assertRaises(ValueError):
            launcher_model.validate(dict(value, language='xx'))
        self.assertEqual(launcher_model.languages(ROOT)[0], 'en-US')
        self.assertIn('fr-CA', launcher_model.languages(ROOT))


if __name__ == '__main__':
    unittest.main()

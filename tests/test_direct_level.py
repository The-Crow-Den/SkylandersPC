# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from tools import direct_level


class DirectLevelTests(unittest.TestCase):
    def test_private_hardlink_copy_is_replaced_without_touching_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.xml'
            original=b'<Tfb\r\n startLevel = "Title"\r\n />\r\n'
            source.write_bytes(original)
            session=root/'session';game=session/'game';game.mkdir(parents=True)
            os.link(source,game/'alchemy.xml')
            report=direct_level.prepare(game,session,expected_sha256=hashlib.sha256(original).hexdigest())
            self.assertEqual(source.read_bytes(),original)
            self.assertIn(direct_level.CHAPTER_ONE,(game/'alchemy.xml').read_bytes())
            self.assertNotIn(direct_level.TITLE,(game/'alchemy.xml').read_bytes())
            self.assertEqual(report['session_sha256'],hashlib.sha256((game/'alchemy.xml').read_bytes()).hexdigest())
            self.assertFalse((game/'alchemy.xml.fps-direct.tmp').exists())

    def test_foreign_hash_and_external_or_symlinked_paths_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);session=root/'session';game=session/'game';game.mkdir(parents=True)
            config=game/'alchemy.xml';config.write_bytes(direct_level.TITLE)
            with self.assertRaisesRegex(ValueError,'unknown alchemy'):
                direct_level.prepare(game,session)
            with self.assertRaisesRegex(ValueError,'private session'):
                direct_level.prepare(game,root/'other',expected_sha256=hashlib.sha256(config.read_bytes()).hexdigest())
            external=root/'external.xml';external.write_bytes(direct_level.TITLE)
            config.unlink();config.symlink_to(external)
            with self.assertRaisesRegex(ValueError,'symlinked'):
                direct_level.prepare(game,session,expected_sha256=hashlib.sha256(external.read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()

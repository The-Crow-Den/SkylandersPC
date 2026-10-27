# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from tools import controller_art as art
from tools import import_controller_glyphs as importer


class ControllerArtTests(unittest.TestCase):
    def test_cached_pixels_require_matching_dimensions_and_digest(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(art,'ROOT',Path(folder).resolve()):
            root=Path(folder);data=struct.pack('<II',2,3)+bytes(range(24))
            name='xbox-0.rgba';(root/name).write_bytes(data)
            (root/'manifest.json').write_text(json.dumps(dict(schema_version=1,provider='Steam client',files={name:hashlib.sha256(data).hexdigest()})))
            self.assertEqual(art.glyph('xbox',0,2,3),data[8:])
            with self.assertRaises(ValueError):art.glyph('xbox',0,3,2)
            (root/name).write_bytes(data[:-1]+b'x')
            with self.assertRaises(ValueError):art.glyph('xbox',0,2,3)
            self.assertFalse(art.available())

    def test_absent_artwork_and_redirected_cache_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'target';target.mkdir();link=root/'link';link.symlink_to(target,target_is_directory=True)
            with patch.object(art,'ROOT',link):
                self.assertFalse(art.available())
                with self.assertRaises(ValueError):art.glyph('xbox',0,84,84)
            with patch.object(art,'ROOT',root/'missing'):
                self.assertFalse(art.available())
            with self.assertRaises(ValueError):art.glyph('unknown',0,84,84)

    @unittest.skipUnless(importlib.util.find_spec('PIL'),'Pillow needed only for artwork import')
    def test_import_preserves_aspect_ratio_and_runs_without_original_source(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'api/dark';source.mkdir(parents=True)
            light=root/'api/light';light.mkdir()
            # Deliberately tall synthetic glyphs catch the old stretched text
            # failure. No vendor artwork is used by these tests.
            fixture=Image.new('RGBA',(256,256),(0,0,0,0))
            for y in range(50,200):
                for x in range(105,155):fixture.putpixel((x,y),(255,255,255,255))
            for names in importer.NAMES.values():
                for name in names:
                    fixture.save(source/(name+'_lg.png'));fixture.save(light/(name+'_lg.png'))
            cache=root/'cache';result=importer.prepare(source,cache)
            self.assertEqual(result['sources'],24)
            with patch.object(art,'ROOT',cache):
                pixels=art.glyph('xbox',0,84,84);bounds=Image.frombytes('RGBA',(84,84),pixels).getbbox()
                self.assertLessEqual(abs((bounds[2]-bounds[0])*3-(bounds[3]-bounds[1])),3)
                self.assertLessEqual(abs(bounds[0]+bounds[2]-84),1)
                self.assertTrue(art.available())
                mask=art.letter('xbox',0,48,48);self.assertEqual(len(mask),48*48)
                # Runtime reading uses only verified cache bytes, not Steam.
                import shutil
                shutil.rmtree(root/'api')
                self.assertEqual(art.glyph('xbox',0,84,84),pixels)
            with self.assertRaises(ValueError):importer.prepare(source,cache)

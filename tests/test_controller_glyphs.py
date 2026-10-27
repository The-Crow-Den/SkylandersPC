# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import copy
import lzma
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import controller_glyphs as glyph,asset_mod


class ControllerGlyphTests(unittest.TestCase):
    def setUp(self):
        # Synthetic cache payloads keep CI independent of Steam/proprietary art.
        def image(mode,index,width,height):
            color=(20,190,70,255) if mode=='xbox' else (220,220,220,255)
            return b''.join(bytes(color if 5<=x<width-5 and 5<=y<height-5 else (0,0,0,0))
                            for y in range(height) for x in range(width))
        self.image=image
        self.enterContext(patch.object(glyph.controller_art,'glyph',side_effect=image))

    def test_family_positions_are_consistent_with_existing_controls(self):
        self.assertEqual([glyph.label('xbox',i) for i in range(4)],['A','X','B','Y'])
        self.assertEqual([glyph.label('nintendo',i) for i in range(4)],['B','Y','A','X'])
        self.assertEqual(glyph.label('xbox',6),'RT')
        self.assertEqual(glyph.label('nintendo',6),'ZR')
        for invalid in ('auto','unknown','playstation'):
            with self.assertRaises(ValueError):glyph.raster(invalid,0)
        with self.assertRaises(ValueError):glyph.raster('xbox',10)

    def test_imported_art_is_used_without_redrawing_or_distortion(self):
        xbox=glyph.raster('xbox',0);nintendo=glyph.raster('nintendo',0)
        self.assertEqual(xbox,self.image('xbox',0,84,84))
        self.assertEqual(len(xbox),84*84*4)
        self.assertNotEqual(xbox,nintendo)
        self.assertEqual(xbox[3],0)
        self.assertEqual(xbox[(42*84+42)*4+3],255)
        self.assertTrue(any(xbox[i+1]>xbox[i]+30 for i in range(0,len(xbox),4)))

    def test_verified_pack_changes_only_selected_font_cells(self):
        # Synthetic tiled texture, not a game asset. Enumerate all source
        # addresses to ensure padding and untouched icons survive the patch.
        source=bytes(range(256))*(1024*192*4//256)
        profile=dict(asset='permanent/bootstrap.bld',texture_offset=0,
                     source_sha256=asset_mod.digest(source),chunks=[])
        for at in range(0,len(source),32768):
            profile['chunks'].append(dict(plain_offset=at,offset=at,allocation=32768,
                decoded_size=32768,decoded_sha256=asset_mod.digest(source[at:at+32768]),encoding='raw'))
        generated=glyph.recipe(source,profile,'xbox')
        result,_=asset_mod.patch_asset(source,generated)
        selected=set()
        for _,left,top,w,h in glyph.CELLS:
            for y in range(top,top+h):
                for x in range(left,left+w):
                    at=glyph.tiled_offset(x,y);selected.update(range(at,at+4))
        self.assertTrue(any(a!=b for a,b in zip(source,result)))
        self.assertTrue(all(a==b or i in selected for i,(a,b) in enumerate(zip(source,result))))
        before=source[:]
        profile['chunks'][0]['decoded_sha256']='0'*64
        with self.assertRaises(ValueError):glyph.recipe(source,profile,'xbox')
        self.assertEqual(source,before)
        with self.assertRaises(ValueError):glyph.recipe(b'unknown',profile,'xbox')

    def test_raw_lzma_uses_external_decoded_size_and_checks_block_bounds(self):
        plain=b'a'*32768
        encoded=lzma.compress(plain+b'padding',format=lzma.FORMAT_RAW,
            filters=[dict(id=lzma.FILTER_LZMA1,dict_size=32768,lc=3,lp=0,pb=2)])
        source=len(encoded).to_bytes(2,'little')+bytes.fromhex('5d00800000')+encoded
        row=dict(offset=0,allocation=len(source),plain_offset=0,decoded_size=len(plain),
                 decoded_sha256=asset_mod.digest(plain),encoding='raw-lzma',encoded_size=len(encoded),properties_hex='5d00800000')
        profile=dict(source_sha256=asset_mod.digest(source),chunks=[row])
        self.assertEqual(glyph._read_blocks(source,profile)[0][1],plain)
        for key,value in [('decoded_size',32769),('allocation',len(source)+1),('plain_offset',1)]:
            changed=copy.deepcopy(profile);changed['chunks'][0][key]=value
            with self.assertRaises(ValueError):glyph._read_blocks(source,changed)
        profile['chunks'].append(row)
        with self.assertRaises(ValueError):glyph._read_blocks(source,profile)

    def test_shipped_animated_pack_uses_correct_action_and_bounded_regions(self):
        path=Path(__file__).resolve().parents[1]/'profiles/patches/trap-team-us-01.01-controller-glyphs.json'
        profile=json.loads(path.read_text());images=profile['prompts']['textures']
        self.assertEqual(len(images),37)
        self.assertEqual(len({image['texture_offset'] for image in images}),37)
        for image in images:
            expected=0 if '/a_mash/' in image['name'] else 1 if '/square_mash/' in image['name'] else 6
            self.assertEqual(image['glyph_index'],expected)
            self.assertEqual(image['texture_size'],16384)

    def test_unavailable_sdl_keeps_original_prompts(self):
        with patch('ctypes.util.find_library',return_value=None):
            self.assertEqual(glyph.detect()[0],'playstation')

    def test_unknown_executable_is_rejected_before_reading_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'profile.json'
            path.write_text('{"executable_sha256":"verified"}')
            with self.assertRaises(ValueError):
                glyph.prepare(folder,folder,folder,path,'xbox','other')

# SPDX-License-Identifier: GPL-3.0-or-later
import struct
from unittest.mock import patch
import unittest
from tools import block_texture as bc,controller_glyphs as glyph,asset_mod


def letter_mask(width,height):
    return bytes(255 if width//3<=x<width*2//3 and height//4<=y<height*3//4 else 0
                 for y in range(height) for x in range(width))


class BlockTextureTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(glyph.controller_art,'letter',side_effect=lambda mode,index,w,h:letter_mask(w,h)))

    def test_color_decode_uses_spec_endpoint_order_and_index_bits(self):
        # RGB565 red/blue endpoints and indices 0,1,2,3 repeated.
        block=struct.pack('<HHI',0xf800,0x001f,0xe4e4e4e4)
        self.assertEqual(bc.decode_color(block)[:4],[(255,0,0),(0,0,255),(170,0,85),(85,0,170)])
        self.assertEqual(bc.decode_color(bytes(8)),[(0,0,0)]*16)
        with self.assertRaises(ValueError):bc.decode_color(bytes(7))

    def test_color_encoding_round_trips_solid_and_mixed_endpoints(self):
        for pixels in [[(255,0,0)]*16,[(0,255,0)]*8+[(0,0,255)]*8,[(0,0,0)]*16]:
            self.assertEqual(bc.decode_color(bc.encode_color(pixels)),pixels)
        with self.assertRaises(ValueError):bc.encode_color([(0,0,300)]*16)

    def test_prompt_patch_preserves_encoded_alpha_and_all_external_blocks(self):
        color=bc.encode_color([(64,64,64)]*16)
        raw=b''.join(bytes([i%256])*8+color for i in range(1024))
        rect=(40,40,48,48)
        result=bc.patch_prompt(raw,letter_mask(48,48),rect,(80,220,80))
        self.assertNotEqual(result,raw)
        for y in range(32):
            for x in range(32):
                at=bc.block_offset(x,y)
                self.assertEqual(result[at:at+8],raw[at:at+8])
                if not 10<=x<22 or not 10<=y<22:
                    self.assertEqual(result[at:at+16],raw[at:at+16])
        self.assertEqual(len({bc.block_offset(x,y) for y in range(32) for x in range(32)}),1024)
        with self.assertRaises(ValueError):bc.patch_prompt(raw,letter_mask(48,48),(41,40,48,48),(0,0,0))
        with self.assertRaises(ValueError):bc.patch_prompt(raw[:-1],letter_mask(48,48),rect,(0,0,0))

    def test_prompt_transport_edits_cross_block_boundaries_without_other_writes(self):
        # Offset the texture so it spans two archive blocks, as real IGZ memory
        # entries do. Every byte around it must survive transport preparation.
        raw=b'\xff\x00'+bytes(6)+bc.encode_color([(70,70,70)]*16)
        source=bytearray(bytes(65536));start=32768-8192;source[start:start+16384]=raw*1024;source=bytes(source)
        profile=dict(asset='permanent/global.bld',source_sha256=asset_mod.digest(source),chunks=[],
                     textures=[dict(texture_offset=start,texture_size=16384,glyph_index=0,rectangle=[40,40,48,48])])
        for at in (0,32768):
            profile['chunks'].append(dict(offset=at,plain_offset=at,allocation=32768,decoded_size=32768,
                decoded_sha256=asset_mod.digest(source[at:at+32768]),encoding='raw'))
        modified,_=asset_mod.patch_asset(source,glyph.prompt_recipe(source,profile,'nintendo'))
        self.assertEqual(modified[:start],source[:start]);self.assertEqual(modified[start+16384:],source[start+16384:])
        self.assertNotEqual(modified,source)

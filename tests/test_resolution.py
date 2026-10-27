# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import struct
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from tools import prepare_native
from tools.resolution import patch_pack, PRESETS, renderer_options, prepare_assets


class ResolutionTests(unittest.TestCase):
    RENDERER = b'''<igx><object refname="mainScene" type="igRenderTarget">
<var name="_height" value="1080" /><var name="_width" value="1920" /></object>
<object refname="cascadeShadowsDepth" type="igRenderTarget">
<var name="_width" value="1024" /><var name="_height" value="4096" /></object>
<object refname="half"><var name="_parentTarget" ref="this.mainScene" />
<var name="_widthScale" value="0.5" /></object></igx>'''

    def test_scene_and_shadow_sizes_are_independent(self):
        result = renderer_options(self.RENDERER, (2560,1440), 'low')
        for value in (b'2560', b'1440', b'512', b'2048', b'ref="this.mainScene"', b'value="0.5"'):
            self.assertIn(value, result)
        self.assertEqual(renderer_options(self.RENDERER), self.RENDERER)
        with self.assertRaises(ValueError):
            renderer_options(self.RENDERER.replace(b'1080', b'999'), (2560,1440))

    def test_disabling_blur_reconnects_fxaa_and_removes_only_its_two_bundles(self):
        graph = (b'<igx><object refname="defRenderer_igRenderPassList" count="49">'
                 b'<listitem ref="this.velocityBundle" /><listitem ref="this.motionBlurBundle" />'
                 + b'<listitem ref="this.water" />' * 47
                 + b'</object><object refname="fxaa_igRenderTargetInputDataList_igRenderTargetInputData">'
                 b'<var name="_renderTarget" ref="this.motionBlurredScene" /></object></igx>')
        result = renderer_options(graph,motion_blur=False)
        self.assertIn(b'count="47"',result)
        self.assertIn(b'ref="this.defocusedScene"',result)
        self.assertNotIn(b'ref="this.motionBlurredScene"',result)
        self.assertNotIn(b'ref="this.motionBlurBundle"',result)
        self.assertEqual(result.count(b'ref="this.water"'),47)
        with self.assertRaises(ValueError):
            renderer_options(graph.replace(b'this.motionBlurredScene',b'this.unknown'),motion_blur=False)

    def test_asset_copy_leaves_original_renderer_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root/'source'
            (game/'renderer').mkdir(parents=True)
            source = game/'renderer/tfbRenderer.igx'
            source.write_bytes(self.RENDERER)
            (game/'immutable').write_bytes(b'unchanged')
            session = root/'session'
            session.mkdir()
            profile = root/'profile.json'
            profile.write_text(json.dumps({'renderer_sha256': hashlib.sha256(self.RENDERER).hexdigest()}))
            with patch('tools.resolution.PROFILE', profile):
                output, metadata = prepare_assets(game, session, (2560,1440), 'low')
            self.assertEqual(source.read_bytes(), self.RENDERER)
            self.assertNotEqual(source.stat().st_ino, (output/'renderer/tfbRenderer.igx').stat().st_ino)
            self.assertEqual((game/'immutable').stat().st_ino, (output/'immutable').stat().st_ino)
            self.assertEqual(metadata['scene_size'], [2560,1440])

    def fixture(self):
        code = bytes.fromhex('c7459080070000c7459438040000')
        offset = prepare_native.HEADER.size + prepare_native.SEGMENT.size
        data = (prepare_native.HEADER.pack(prepare_native.MAGIC, 4096, 4096, 4096, 1, 0, 0)
                + prepare_native.SEGMENT.pack(4096, 4096, len(code), 5, offset) + code)
        profile = {'pack_sha256': {'original': hashlib.sha256(data).hexdigest()},
                   'virtual_address': 4096, 'expected_hex': code.hex()}
        return data, profile, offset

    def test_presets_patch_only_two_immediate_operands(self):
        data, profile, offset = self.fixture()
        for name, (width, height) in PRESETS.items():
            result = patch_pack(data, name, 'original', profile)
            self.assertEqual(len(data), len(result))
            self.assertEqual(result[:offset], data[:offset])
            self.assertEqual(struct.unpack_from('<I', result, offset + 3)[0], width)
            self.assertEqual(struct.unpack_from('<I', result, offset + 10)[0], height)
            self.assertEqual(result[offset:offset+3], data[offset:offset+3])
            self.assertEqual(result[offset+7:offset+10], data[offset+7:offset+10])

    def test_refuses_unknown_pack_and_variant(self):
        data, profile, _ = self.fixture()
        for value, variant in ((data + b'x', 'original'), (data, 'unknown')):
            with self.assertRaises(ValueError):
                patch_pack(value, '1440p', variant, profile)

    def test_expected_bytes_and_executable_mapping_are_required(self):
        data, profile, _ = self.fixture()
        profile['expected_hex'] = '00' * 14
        with self.assertRaises(ValueError):
            patch_pack(data, '1440p', 'original', profile)
        profile['virtual_address'] = 5000
        with self.assertRaises(ValueError):
            patch_pack(data, '1440p', 'original', profile)

# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import lzma
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import nightmare_mod as mod


def fixture():
    plain=bytearray(32768);plain[100:108]=bytes.fromhex('284e020000000000')
    props=bytes.fromhex('5d00800000')
    compressed=lzma.compress(bytes(plain),format=lzma.FORMAT_RAW,
        filters=[dict(id=lzma.FILTER_LZMA1,dict_size=32768,lc=3,lp=0,pb=2)])
    block=struct.pack('<H',len(compressed))+props+compressed
    data=b'IGA\x1a\x0b\0\0\0'+bytes(4088)+block+bytes(4096-len(block))+b'unchanged footer'
    profile=dict(asset='level/title.bld',asset_sha256=hashlib.sha256(data).hexdigest(),
                 chunk_offset=4096,allocation_size=4096,compressed_payload_size=len(compressed),
                 lzma_properties_hex=props.hex(),decoded_size=32768,
                 decoded_sha256=hashlib.sha256(plain).hexdigest(),patch_offset_in_chunk=100,
                 expected_hex='284e020000000000',replacement_hex='70c4060000000000',status='synthetic')
    return data,profile


class NightmareModTests(unittest.TestCase):
    def test_recompression_preserves_every_other_allocation(self):
        data,profile=fixture()
        result,metadata=mod.patch_asset(data,profile)
        self.assertEqual(len(result),len(data))
        self.assertEqual(result[:4096],data[:4096])
        self.assertEqual(result[8192:],data[8192:])
        self.assertEqual(metadata['decoded_changed_bytes'],3)
        self.assertNotEqual(result,data)

    def test_wrong_build_or_eligibility_bytes_are_rejected(self):
        data,profile=fixture()
        with self.assertRaisesRegex(ValueError,'unknown title asset'):
            mod.patch_asset(data+b'x',profile)
        profile['expected_hex']='00'*8
        with self.assertRaisesRegex(ValueError,'eligibility bytes mismatch'):
            mod.patch_asset(data,profile)
        data,profile=fixture();profile['decoded_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'decoded chunk mismatch'):
            mod.patch_asset(data,profile)

    def test_private_overlay_breaks_hardlink_before_writing(self):
        data,profile=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);original=root/'original';session=root/'session';game=session/'game'
            (original/'level').mkdir(parents=True);(game/'level').mkdir(parents=True)
            (original/'eboot.bin').write_bytes(b'synthetic executable')
            profile['executable_sha256']=hashlib.sha256(b'synthetic executable').hexdigest()
            source=original/'level/title.bld';destination=game/'level/title.bld'
            source.write_bytes(data);os.link(source,destination)
            manifest=root/'profile.json';manifest.write_text(json.dumps(profile))
            with patch.object(mod,'PROFILE',manifest):
                mod.prepare(original,game,session)
                self.assertEqual(source.read_bytes(),data)
                self.assertNotEqual(source.stat().st_ino,destination.stat().st_ino)
                with self.assertRaisesRegex(ValueError,'private session'):
                    mod.prepare(original,original,session)

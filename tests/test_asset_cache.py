# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
from pathlib import Path
import tempfile
import unittest
from tools import asset_cache

class AssetCacheTests(unittest.TestCase):
    def test_hit_validates_output_and_skips_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=b'original';recipe={'source_sha256':hashlib.sha256(source).hexdigest(),'edits':[1]};calls=[]
            def patch(data,plan):
                calls.append(plan);output=data+b'patched'
                return output,{'output_sha256':hashlib.sha256(output).hexdigest()}
            self.assertEqual(asset_cache.stage(root/'cache',source,recipe,root/'one',patch)['cache'],'miss')
            self.assertEqual(asset_cache.stage(root/'cache',source,recipe,root/'two',patch)['cache'],'hit')
            self.assertEqual(len(calls),1);self.assertEqual((root/'one').read_bytes(),(root/'two').read_bytes())
            cached=next((root/'cache').glob('*/asset'));cached.write_bytes(b'corrupt')
            self.assertEqual(asset_cache.stage(root/'cache',source,recipe,root/'three',patch)['cache'],'miss')
            self.assertEqual((root/'three').read_bytes(),source+b'patched');self.assertEqual(source,b'original')
            with self.assertRaises(ValueError):asset_cache.stage(root/'cache',b'wrong',recipe,root/'four',patch)
            self.assertEqual(len(calls),2)
    def test_recipe_changes_and_redirected_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=b'x';recipe={'source_sha256':hashlib.sha256(data).hexdigest()}
            def patch(data,plan):return data,{'output_sha256':hashlib.sha256(data).hexdigest()}
            asset_cache.stage(root/'cache',data,recipe,root/'one',patch)
            self.assertEqual(asset_cache.stage(root/'cache',data,dict(recipe,revision=2),root/'two',patch)['cache'],'miss')
            (root/'link').symlink_to(root/'cache',target_is_directory=True)
            with self.assertRaises(ValueError):asset_cache.stage(root/'link',data,recipe,root/'three',patch)

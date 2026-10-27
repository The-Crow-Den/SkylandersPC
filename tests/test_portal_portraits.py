# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from tools import fetch_portal_portraits as portraits

class PortalPortraitTests(unittest.TestCase):
    def test_identity_filter_and_bounds(self):
        tree={'tree':[{'path':'data/images/00000e-0000/thumb.png','sha':'x'},
                      {'path':'data/images/0003e9-0000/thumb.png'},
                      {'path':'data/images/00000e-4000/thumb.png'},
                      {'path':'data/images/../../thumb.png'}]}
        self.assertEqual([(r['id'],r['variant']) for r in portraits.image_entries(tree)],[(14,0)])
        with self.assertRaises(ValueError):portraits.image_entries({'truncated':True})

    def test_atlas_identity_and_element_mapping_without_network(self):
        picture=io.BytesIO();Image.new('RGBA',(24,32),(40,120,200,255)).save(picture,format='PNG');data=picture.getvalue()
        blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'profiles').mkdir()
            (root/'profiles/trap-team-portal.json').write_text(json.dumps({'villains':[{'portrait_url':'https://example.invalid/'+str(i)} for i in range(46)]}))
            tree=root/'tree.json';tree.write_text(json.dumps({'tree':[{'path':'data/images/00000e-0000/thumb.png','sha':blob}]}))
            cache=root/'cache'
            with patch.object(portraits,'ROOT',root),patch.object(portraits,'download',return_value=data):
                record=portraits.prepare(cache,tree)
            self.assertFalse(record['missing']);self.assertEqual(record['figure_portraits'],1)
            self.assertIn('14 0 46',(cache/'portrait-index.txt').read_text())
            elements=[tuple(map(int,line.split())) for line in (cache/'element-index.txt').read_text().splitlines()]
            self.assertEqual(elements,[(i,47+i) for i in range(11)])
            width,height=struct.unpack('<II',(cache/'portraits.rgba').read_bytes()[:8])
            self.assertEqual((width,height),(1536,384))
            self.assertEqual((cache/'portraits.rgba').stat().st_size,8+width*height*4)
            # A redirected output is rejected before writing cache content.
            redirected=root/'redirected';redirected.symlink_to(cache,target_is_directory=True)
            with self.assertRaises(ValueError):portraits.prepare(redirected,tree)

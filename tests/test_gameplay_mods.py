# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
from tools import gameplay_mods


class GameplayModTests(unittest.TestCase):
    def test_title_profile_overrides_and_unsupported_build_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            profile=root/'out/mod-profiles/CUSA00626.json';profile.parent.mkdir(parents=True)
            self.assertEqual(gameplay_mods.selection(root,'CUSA00626'),dict.fromkeys(gameplay_mods.NAMES,False))
            profile.write_text(json.dumps(dict(schema_version=1,title_id='CUSA00626',enabled={'element-gates':True,'traptanium':False})))
            self.assertEqual(gameplay_mods.selection(root,'CUSA00626',{'element-gates':False,'traptanium':True}),{'element-gates':False,'traptanium':True,'unlock-expansions':False})
            self.assertTrue(gameplay_mods.selection(root,'CUSA00626',{'unlock-expansions':True})['unlock-expansions'])
            self.assertFalse(any(gameplay_mods.selection(root,'CUSA00697').values()))
            self.assertEqual(gameplay_mods.recipes(root,'CUSA00697','01.00',dict.fromkeys(gameplay_mods.NAMES,False)),[])
            with self.assertRaises(ValueError):gameplay_mods.recipes(root,'CUSA00697','01.00',{'traptanium':True})
            with self.assertRaises(ValueError):gameplay_mods.selection(root,'../bad')
            with self.assertRaises(ValueError):gameplay_mods.selection(root,'CUSA00626',{'unknown':True})

    def test_withheld_recipe_reports_unavailable_without_disabling_other_mods(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);selected=dict.fromkeys(gameplay_mods.NAMES,False)
            selected['traptanium']=True
            with self.assertRaisesRegex(ValueError,'recipe is unavailable'):
                gameplay_mods.recipes(root,'CUSA00626','01.01',selected)
            selected['traptanium']=False;selected['element-gates']=True
            path=root/'profiles/patches/trap-team-us-01.01-element-gates.experimental.json'
            path.parent.mkdir(parents=True);path.write_text('{"name":"synthetic gate recipe"}')
            self.assertEqual(gameplay_mods.recipes(root,'CUSA00626','01.01',selected),[{'name':'synthetic gate recipe'}])

    def test_invalid_profile_and_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();profile=root/'out/mod-profiles/CUSA00626.json';profile.parent.mkdir(parents=True)
            for record in ({'schema_version':True,'title_id':'CUSA00626','enabled':dict.fromkeys(gameplay_mods.NAMES,True)},
                           {'schema_version':1,'title_id':'CUSA00000','enabled':dict.fromkeys(gameplay_mods.NAMES,True)},
                           {'schema_version':1,'title_id':'CUSA00626','enabled':{'element-gates':1,'traptanium':False}}):
                profile.write_text(json.dumps(record))
                with self.assertRaises(ValueError):gameplay_mods.selection(root,'CUSA00626')
            profile.unlink();profile.symlink_to(root/'elsewhere')
            (root/'elsewhere').write_text('{}')
            with self.assertRaises(ValueError):gameplay_mods.selection(root,'CUSA00626')

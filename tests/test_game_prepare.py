# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic ELF preparation only; no real game files, builds or GPU required."""
import contextlib
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import game_prepare as prepare, game_library, game_build, link_native, run_session
from test_game_install import sfo
from test_prepare_native import native_fixture


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        host,renderer=prepare.runtime_paths(self.root)
        for path in (host,renderer):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'\x7fELFsynthetic-runtime');path.chmod(0o755)
        self.commands=patch.object(prepare.subprocess,'run',side_effect=self.command);self.commands.start();self.addCleanup(self.commands.stop)
        self.entry=self.game('CUSA11111')

    def tearDown(self):self.temporary.cleanup()

    def command(self,argv,**kwargs):
        self.assertEqual(argv[0],'ldd') # Existing synthetic runtime; no compiler may run.
        return subprocess.CompletedProcess(argv,0,stdout='synthetic dependencies\n',stderr='')

    def game(self,title):
        data=native_fixture();instruction=b'\xc7\x45\x90'+struct.pack('<I',1920)+b'\xc7\x45\x94'+struct.pack('<I',1080)
        data[0x180:0x180+len(instruction)]=instruction
        digest=hashlib.sha256(data).hexdigest()
        incoming=self.root/('incoming-'+title);(incoming/'sce_sys').mkdir(parents=True)
        (incoming/'sce_sys/param.sfo').write_bytes(sfo(dict(TITLE_ID=title,APP_VER='01.00',CATEGORY='gd',CONTENT_ID=title)))
        (incoming/'eboot.bin').write_bytes(data)
        (incoming/'renderer').mkdir();(incoming/'renderer/tfbRenderer.igx').write_bytes(b'synthetic graphics asset')
        entry=game_library.publish(game_library.directory(self.root),incoming)
        profiles=self.root/'profiles';profiles.mkdir(exist_ok=True)
        recipe=profiles/(title+'-resolution.json');patch_path=profiles/(title+'-timing.json')
        changed=bytearray(data);changed[0x190]=1
        hashes={variant:hashlib.sha256(link_native.link_images([('eboot.bin',payload)])[0]).hexdigest()
                for variant,payload in [('original',data),('60-delta',changed)]}
        patch_path.write_text(json.dumps(dict(schema_version=1,title_id=title,app_version='01.00',executable_sha256=digest,
            patches=[dict(id='synthetic-timing',kind='enhancement',reason='Synthetic test',file_offset=0x190,expected_hex='00',replacement_hex='01')])))
        recipe.write_text(json.dumps(dict(title_id=title,app_version='01.00',executable_sha256=digest,pack_sha256=hashes,
            renderer_sha256=hashlib.sha256(b'synthetic graphics asset').hexdigest(),expected_hex=instruction.hex(),virtual_address=0x400180)))
        prep=dict(modules=[],variants={'original':dict(pack='unused-original'),'60-delta':dict(pack='unused-delta',patch=str(patch_path.relative_to(self.root)))},
                  recipes={'resolution':str(recipe.relative_to(self.root))},optional_recipes={'glyphs':'profiles/unavailable.json'})
        (profiles/(title+'.json')).write_text(json.dumps(dict(id=title.lower(),title='Synthetic game',validated_builds=[
            dict(title_id=title,app_version='01.00',executable_sha256=digest,preparation=prep)])))
        return entry

    def run_prepare(self,entry=None):
        events=[];result=prepare.prepare(self.root,entry or self.entry,progress=events.append)
        return result,events

    def test_complete_pipeline_links_all_allowed_variants_and_skips_unchanged_inputs(self):
        first,events=self.run_prepare()
        self.assertEqual(events[-1]['name'],'ready')
        for variant in ('original','60-delta'):
            install=game_library.discover(self.entry)
            config=game_build.configuration(self.root,install,variant)
            self.assertTrue((config['pack']/'boot.plan').is_file())
            self.assertEqual(prepare.file_hash(config['pack']/'image.pack'),json.loads((self.root/'profiles/CUSA11111-resolution.json').read_text())['pack_sha256'][variant])
            prepare.require_ready(self.root,self.entry,variant)
        before={k:v['outputs'] for k,v in first['steps'].items()}
        second,events=self.run_prepare()
        self.assertTrue(all(e['state']=='skipped' for e in events if e['name'] in second['steps'] and e['state']!='running'))
        self.assertEqual({k:v['outputs'] for k,v in second['steps'].items()},before)
        self.assertTrue(any(e['state']=='optional' for e in events))

    def test_changed_input_reruns_only_affected_steps_and_keeps_old_outputs(self):
        first,_=self.run_prepare();old=dict(first['steps']['pack.original']['outputs'])
        graphics=Path(self.entry['base_path'])/'renderer/tfbRenderer.igx';graphics.write_bytes(b'changed synthetic graphics')
        recipe=self.root/'profiles/CUSA11111-resolution.json';record=json.loads(recipe.read_text());record['renderer_sha256']=prepare.file_hash(graphics);recipe.write_text(json.dumps(record))
        second,events=self.run_prepare()
        self.assertTrue(any(e['name']=='recipes' and e['state']=='complete' for e in events))
        self.assertTrue(any(e['name']=='verify-executable' and e['state']=='skipped' for e in events))
        self.assertTrue(all((self.root/path).is_file() for path in old))
        self.assertNotEqual(second['steps']['pack.original']['outputs'],old)

    def test_pack_tampering_is_refused_and_repair_publishes_a_new_copy(self):
        first,_=self.run_prepare();marker=first['steps']['pack.60-delta']
        image=next(self.root/p for p in marker['outputs'] if p.endswith('/image.pack'));image.write_bytes(b'corrupt')
        with self.assertRaisesRegex(prepare.PreparationError,'pack.60-delta.*Repair'):prepare.require_ready(self.root,self.entry)
        second,_=self.run_prepare()
        self.assertEqual(image.read_bytes(),b'corrupt')
        self.assertNotEqual(second['steps']['pack.60-delta']['outputs'],marker['outputs'])
        prepare.require_ready(self.root,self.entry)

    def test_failure_keeps_earlier_steps_and_resumes_after_fix(self):
        first,_=self.run_prepare();original=dict(first['steps']['pack.original']['outputs'])
        patch_path=self.root/'profiles/CUSA11111-timing.json';record=json.loads(patch_path.read_text());record['patches'][0]['expected_hex']='ff';patch_path.write_text(json.dumps(record))
        events=[]
        with self.assertRaisesRegex(prepare.PreparationError,'pack.60-delta'):
            prepare.prepare(self.root,self.entry,progress=events.append)
        self.assertEqual(events[-1]['state'],'failed')
        state=prepare.read_state(self.root,self.entry)
        self.assertEqual(state['steps']['pack.original']['outputs'],original)
        self.assertTrue(all(prepare.file_hash(self.root/p)==digest for p,digest in original.items()))
        record['patches'][0]['expected_hex']='00';patch_path.write_text(json.dumps(record))
        self.run_prepare();prepare.require_ready(self.root,self.entry)

    def test_progress_is_json_lines_and_runner_names_missing_step_before_creating_a_session(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(prepare.main(['--root',str(self.root),'--game','CUSA11111']),0)
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(all(set(e)=={'name','state','fraction','message'} for e in events))
        self.assertEqual(events[-1]['name'],'ready')
        fresh=self.game('CUSA22222');error=io.StringIO()
        with patch.object(run_session,'ROOT',self.root),contextlib.redirect_stderr(error),self.assertRaises(SystemExit):
            run_session.main(['--game','CUSA22222','--variant','60-delta'])
        self.assertIn('verify-executable',error.getvalue());self.assertIn('Repair',error.getvalue())
        self.assertFalse((self.root/'out/sessions').exists())

    def test_second_profile_uses_same_pipeline_without_title_specific_logic(self):
        self.run_prepare();second=self.game('CUSA22222');self.run_prepare(second)
        prepare.require_ready(self.root,second)
        install=game_library.discover(second)
        self.assertIn('CUSA22222',str(game_build.configuration(self.root,install,'60-delta')['pack']))
        with self.assertRaisesRegex(ValueError,'does not allow'):game_build.configuration(self.root,install,'60')

    def test_executable_mismatch_fails_closed_and_never_builds(self):
        Path(self.entry['base_path']).joinpath('eboot.bin').write_bytes(b'wrong build')
        events=[]
        with self.assertRaisesRegex(prepare.PreparationError,'verify-executable'):
            prepare.prepare(self.root,self.entry,progress=events.append)
        self.assertEqual(events[-1]['state'],'failed')
        self.assertFalse((self.root/'out/prepared-games').exists())

    def test_corrupt_preparation_marker_is_rebuilt_without_removing_old_packs(self):
        record,_=self.run_prepare();original=list(record['steps']['pack.original']['outputs'])
        path=prepare.state_path(self.root,self.entry)
        damaged=json.loads(path.read_text());damaged['steps']['pack.60-delta']['outputs']=['bad record']
        path.write_text(json.dumps(damaged))
        with self.assertRaisesRegex(prepare.PreparationError,'pack.60-delta'):prepare.require_ready(self.root,self.entry)
        self.run_prepare();prepare.require_ready(self.root,self.entry)
        self.assertTrue(all((self.root/p).exists() for p in original))

    def test_missing_runtime_and_renderer_use_build_commands_without_touching_game(self):
        host,renderer=prepare.runtime_paths(self.root);host.unlink();renderer.unlink()
        for folder in (self.root/'native',self.root/'.local/skyrender/gpu'):
            folder.mkdir(parents=True,exist_ok=True);(folder/'CMakeLists.txt').write_text('# synthetic build input')
        calls=[]
        def build(argv,**kwargs):
            calls.append([str(x) for x in argv])
            if argv[0]=='ldd':return subprocess.CompletedProcess(argv,0,stdout='ok',stderr='')
            self.assertEqual(argv[0],'cmake')
            if '--build' in argv:
                target=renderer if 'skyrender' in argv else host
                target.write_bytes(b'\x7fELFsynthetic build output');target.chmod(0o755)
            return subprocess.CompletedProcess(argv,0)
        executable=Path(self.entry['base_path'])/'eboot.bin';before=executable.read_bytes()
        with patch.object(prepare.subprocess,'run',side_effect=build):self.run_prepare()
        self.assertTrue(any('skyrender' in args for args in calls))
        self.assertTrue(any('skylanders-native-host' in args for args in calls))
        self.assertEqual(executable.read_bytes(),before)

    def test_optional_artwork_cache_has_independent_skippable_markers(self):
        self.run_prepare();destination=self.root/'.local/controller-glyphs';destination.mkdir()
        atlas=destination/'menu-atlas.rgba';atlas.write_bytes(b'synthetic cached artwork')
        (destination/'manifest.json').write_text(json.dumps({'files':{'menu-atlas.rgba':prepare.file_hash(atlas)}}))
        source=self.root/'steam';source.mkdir()
        with patch('tools.import_controller_glyphs.discover',return_value=source):
            events=[];prepare.prepare_optional(self.root,self.entry,'controller-art',events.append)
            self.assertEqual(events[-1]['state'],'complete')
            events=[];prepare.prepare_optional(self.root,self.entry,'controller-art',events.append)
            self.assertEqual(events[-1]['state'],'skipped')
        prepare.require_ready(self.root,self.entry)

    @unittest.skipUnless(shutil.which('true') and shutil.which('ldd'),'requires ordinary POSIX runtime tools')
    def test_real_cli_process_prepares_synthetic_game_with_json_only_stdout(self):
        # Use the system's no-op ELF solely for dependency inspection, never as a game host.
        host,_=prepare.runtime_paths(self.root);shutil.copy2(shutil.which('true'),host)
        process=subprocess.Popen([sys.executable,str(Path(prepare.__file__)), '--root',str(self.root),'--game','CUSA11111'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        output,error=process.communicate(timeout=15)
        self.assertEqual(process.returncode,0,error)
        events=[json.loads(line) for line in output.splitlines()]
        self.assertEqual(events[-1]['name'],'ready')
        self.assertTrue(any(e['name']=='pack.60-delta' and e['state']=='complete' for e in events))

    def test_hard_link_refreshes_readiness_stamp_but_content_change_fails(self):
        import os
        self.run_prepare();source=Path(self.entry['base_path'])/'eboot.bin'
        os.link(source,self.root/'session-link')
        prepare.require_ready(self.root,self.entry,deep=False)
        record=prepare.read_state(self.root,self.entry)
        key=str(source.relative_to(self.root))
        self.assertEqual(record['steps']['verify-executable']['stamps'][key],prepare.stamp(source))
        source.write_bytes(b'changed')
        with self.assertRaises(prepare.PreparationError):prepare.require_ready(self.root,self.entry,deep=False)

    def test_comment_only_engine_edit_does_not_invalidate_ready_markers(self):
        self.run_prepare();original=prepare.file_hash
        def changed(path):
            return 'comment-only-change' if Path(path)==Path(prepare.__file__) else original(path)
        with patch.object(prepare,'file_hash',side_effect=changed):
            prepare.require_ready(self.root,self.entry,deep=False)
            prepare.require_ready(self.root,self.entry,deep=True)
        with patch.object(prepare,'PREPARATION_VERSION',prepare.PREPARATION_VERSION+1):
            with self.assertRaises(prepare.PreparationError):prepare.require_ready(self.root,self.entry,deep=False)

    def test_optional_failure_does_not_block_ready(self):
        with patch('tools.import_controller_glyphs.discover',side_effect=ValueError('No optional artwork')):
            events=[];prepare.prepare(self.root,self.entry,progress=events.append,optional=('controller-art',))
        self.assertTrue(any(e['state']=='optional-failed' for e in events))
        prepare.require_ready(self.root,self.entry)

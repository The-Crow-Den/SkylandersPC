# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic versioned libraries, migration, publication and consumer selection."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import game_library as library, game_install, launcher_library, launcher_model
from tools import launcher_packages, launcher_trophies, run_session
from test_game_install import sfo


class GameLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.library = library.directory(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def dump(self, name, title='CUSA00626', ver='01.00', category='gd', content='content', executable=b'synthetic'):
        path = self.root / name
        (path/'sce_sys').mkdir(parents=True)
        (path/'sce_sys/param.sfo').write_bytes(sfo(dict(TITLE_ID=title, APP_VER=ver,
            CATEGORY=category, CONTENT_ID=content, TITLE='Synthetic '+title)))
        if executable is not None:
            (path/'eboot.bin').write_bytes(executable)
        return path

    def profile(self, title, profile_id, ver='01.00', executable=b'synthetic'):
        (self.root/'profiles').mkdir(exist_ok=True)
        path = self.root/'profiles'/f'{profile_id}.json'
        path.write_text(json.dumps(dict(id=profile_id,title='Synthetic profile',validated_builds=[dict(
            title_id=title,app_version=ver,executable_sha256=hashlib.sha256(executable).hexdigest())])))

    def test_manifest_discovery_and_versioned_layout(self):
        base=self.dump('incoming/base');update=self.dump('incoming/update',ver='01.01',category='gp',executable=b'patch')
        entry=library.publish(self.library,base,update,['/packages/base.pkg','update.pkg'])
        manifest=self.library/'CUSA00626/01.01/manifest.json'
        self.assertEqual(library.load_entry(manifest),entry)
        self.assertEqual(entry['source_packages'],['base.pkg','update.pkg'])
        self.assertEqual(entry['executable_sha256'],hashlib.sha256(b'patch').hexdigest())
        self.assertEqual(entry['base_version'],'01.00');self.assertEqual(entry['update_version'],'01.01')
        self.assertEqual(Path(entry['base_path']),self.library/'CUSA00626/01.00/base')
        self.assertEqual(Path(entry['update_path']),self.library/'CUSA00626/01.01/update')
        self.assertTrue(entry['install_date'])
        for source in (entry,manifest,manifest.parent):
            selected=game_install.discover(source)
            self.assertEqual(selected.source('eboot.bin').read_bytes(),b'patch')
        self.assertEqual(library.resolve(self.root,'CUSA00626@01.00').source('eboot.bin').read_bytes(),b'synthetic')
        self.assertEqual(library.resolve(self.root,'CUSA00626').app_version,'01.01')

    def test_attach_update_keeps_base_and_previous_versions(self):
        base=self.dump('incoming/base')
        initial=library.publish(self.library,base,source_packages=['base.pkg'])
        original=Path(initial['base_path']);inode=(original/'eboot.bin').stat().st_ino
        for ver in ('01.01','01.02'):
            update=self.dump('incoming/'+ver,ver=ver,category='gp',executable=None)
            entry=library.publish(self.library,update=update,source_packages=[ver+'.pkg'])
            self.assertEqual(entry['base_path'],str(original))
            self.assertEqual(entry['source_packages'],['base.pkg',ver+'.pkg'])
        self.assertEqual((original/'eboot.bin').stat().st_ino,inode)
        self.assertEqual(len(library.entries(self.root)),3)
        self.assertEqual(library.resolve(self.root).app_version,'01.02')

    def test_update_mismatch_old_version_and_missing_base_refused(self):
        library.publish(self.library,self.dump('base'))
        before=[p.read_bytes() for p in self.library.glob('*/*/manifest.json')]
        cases=[dict(title='CUSA99999',ver='01.01'),dict(content='wrong',ver='01.01'),dict(ver='01.00')]
        for index,options in enumerate(cases):
            update=self.dump('update'+str(index),category='gp',**options)
            with self.assertRaisesRegex(ValueError,'matching title/content'):
                library.publish(self.library,update=update)
            self.assertTrue(update.exists())
        self.assertEqual([p.read_bytes() for p in self.library.glob('*/*/manifest.json')],before)
        bad=self.dump('bad',ver='01.01',category='gp',content='wrong')
        with self.assertRaisesRegex(ValueError,'Update must match'):
            library.publish(self.library,self.dump('redundant'),bad)

    def test_migrate_legacy_in_place_idempotently_preserves_preferences(self):
        base=self.dump('Game/base');update=self.dump('Game/update',ver='01.01',category='gp')
        marker=self.root/'.local/launcher-library.json'
        marker.parent.mkdir(exist_ok=True)
        preferences=launcher_library.defaults();preferences['figures']=['/synthetic/figure.sky']
        preferences['games'][1]['settings']={'resolution':'2160p'}
        marker.write_text(json.dumps(preferences));before=marker.read_bytes()
        for name in ('saves/progress','out/sessions/research','figures/collection'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'keep')
        inode=(base/'eboot.bin').stat().st_ino
        library.register(self.root)
        manifests={p:p.read_bytes() for p in self.library.glob('*/*/manifest.json')}
        library.register(self.root)
        self.assertEqual(len(manifests),2)
        self.assertEqual({p:p.read_bytes() for p in manifests},manifests)
        self.assertEqual(library.resolve(self.root).base,base)
        self.assertEqual(library.resolve(self.root).update,update)
        self.assertEqual((base/'eboot.bin').stat().st_ino,inode)
        self.assertEqual(marker.read_bytes(),before)
        self.assertTrue(all((self.root/name).read_bytes()==b'keep' for name in ('saves/progress','out/sessions/research','figures/collection')))
        library.publish(self.library,update=self.dump('new-update',ver='01.02',category='gp'))
        self.assertEqual(library.resolve(self.root).base,base)

    def test_two_titles_and_unknown_title_coexist_and_use_profiles(self):
        self.profile('CUSA11111','swap-force')
        a=library.publish(self.library,self.dump('first',title='CUSA11111'))
        b=library.publish(self.library,self.dump('second',title='CUSA99999'))
        self.assertTrue(library.supported(self.root,a));self.assertFalse(library.supported(self.root,b))
        with self.assertRaisesRegex(ValueError,'Multiple titles'): library.resolve(self.root)
        self.assertEqual(library.resolve(self.root,'CUSA99999').title_id,'CUSA99999')
        value=launcher_library.defaults();value['games'][0]['settings']={'fullscreen':True}
        launcher_library.sync_installations(self.root,value)
        self.assertEqual(value['games'][0]['installation'],'CUSA11111@01.00')
        self.assertEqual(value['games'][0]['settings'],{'fullscreen':True})
        unknown=next(g for g in value['games'] if g.get('title_id')=='CUSA99999')
        self.assertEqual(unknown['installation'],'CUSA99999@01.00')
        self.assertEqual(library.resolve(self.root,game=unknown).title_id,'CUSA99999')
        # Change the profile metadata, not installation code, to recognize the second title.
        self.profile('CUSA99999','imaginators')
        self.assertTrue(library.supported(self.root,b))

    def test_cli_defaults_to_launcher_selection_and_explicit_choice_wins(self):
        self.profile('CUSA00626','trap-team')
        library.publish(self.library,self.dump('one'))
        library.publish(self.library,self.dump('two',title='CUSA99999'))
        value=launcher_library.defaults();launcher_library.sync_installations(self.root,value)
        value['selected']='trap-team';launcher_library.save(self.root/'.local/launcher-library.json',value)
        self.assertEqual(library.resolve(self.root).title_id,'CUSA00626')
        library.select(self.root,'CUSA99999@01.00')
        self.assertEqual(library.resolve(self.root).title_id,'CUSA99999')
        game=next(g for g in value['games'] if g['id']=='trap-team')
        argv=launcher_model.command(self.root,'python',launcher_model.DEFAULTS,game=game)
        self.assertEqual(argv[argv.index('--game')+1],'CUSA00626@01.00')
        error=io.StringIO()
        with patch.object(run_session,'ROOT',self.root),patch.object(run_session.game_build,'configuration',side_effect=ValueError('selected build')) as build:
            with contextlib.redirect_stderr(error),self.assertRaises(SystemExit):
                run_session.main(['--game','CUSA00626@01.00'])
            self.assertEqual(build.call_args.args[1].title_id,'CUSA00626')
        self.assertIn('selected build',error.getvalue())

    def test_corrupt_manifest_metadata_mismatch_and_symlinks_refused(self):
        entry=library.publish(self.library,self.dump('base'))
        path=library.manifest_path(self.library,entry)
        for values in ({'executable_sha256':'not-a-hash'},{'base_path':'../outside'},{'app_version':'../../escape'}, {'update_path':'/elsewhere'}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                library.validate_entry({**entry,**values})
        path.write_text(json.dumps({**entry,'content_id':'different'}))
        with self.assertRaisesRegex(ValueError,'base metadata'): library.resolve(self.root)
        linked=self.root/'linked';linked.symlink_to(Path(entry['base_path']),target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'): library.publish(self.library,linked)
        path.unlink();path.symlink_to(self.root/'elsewhere')
        with self.assertRaisesRegex(ValueError,'symlink'): library.read_entries(self.library)

    def test_previous_hidden_library_is_referenced_from_visible_games_folder(self):
        hidden=self.root/'.local/game-library'
        initial=library.publish(hidden,self.dump('base'))
        old_manifest=library.manifest_path(hidden,initial).read_bytes()
        inode=Path(initial['base_path']).joinpath('eboot.bin').stat().st_ino
        library.register(self.root);library.register(self.root)
        self.assertEqual(library.directory(self.root),self.root/'Games')
        self.assertEqual(library.manifest_path(hidden,initial).read_bytes(),old_manifest)
        entry=library.resolve_entry(self.root)
        self.assertEqual(entry['base_path'],initial['base_path'])
        self.assertEqual(Path(entry['base_path']).joinpath('eboot.bin').stat().st_ino,inode)
        self.assertTrue(library.manifest_path(self.root/'Games',entry).exists())
        patch=self.dump('update',category='gp',ver='01.01')
        updated=library.publish(library.directory(self.root),update=patch)
        self.assertTrue(Path(updated['update_path']).is_relative_to(self.root/'Games'))

    def test_publication_manifest_failure_rolls_back_only_new_data(self):
        base=self.dump('base');update=self.dump('update',ver='01.01',category='gp')
        original=library.write_json
        calls=[]
        def fail(path,value):
            calls.append(path)
            if len(calls)==2:raise OSError('synthetic manifest failure')
            original(path,value)
        with patch.object(library,'write_json',side_effect=fail):
            with self.assertRaisesRegex(OSError,'synthetic manifest'):
                library.publish(self.library,base,update)
        self.assertTrue(base.exists());self.assertTrue(update.exists())
        self.assertEqual(library.read_entries(self.library),[])

    def test_trophies_follow_selected_version_and_title(self):
        self.profile('CUSA00626','trap-team')
        base=self.dump('base');(base/'sce_sys/trophy').mkdir();(base/'sce_sys/trophy/base.trp').write_bytes(b'synthetic')
        entry=library.publish(self.library,base)
        update=self.dump('patch',category='gp',ver='01.01')
        (update/'sce_sys/trophy').mkdir();(update/'sce_sys/trophy/update.trp').write_bytes(b'patch')
        library.publish(self.library,update=update)
        game={'id':'trap-team','installation':'CUSA00626@01.00'}
        self.assertEqual(launcher_trophies.game_sources(self.root,game)[0].name,'base.trp')
        game['installation']='CUSA00626@01.01'
        self.assertEqual(launcher_trophies.game_sources(self.root,game)[0].name,'update.trp')


if __name__ == '__main__':
    unittest.main()

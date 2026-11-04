# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import mod_manifest as mods
from tools import nightmare_mod

ROOT = Path(__file__).resolve().parents[1]
BUILD = 'a' * 64
OTHER = 'b' * 64


def manifest(ident='sample', **changes):
    data = dict(schema_version=1, id=ident, name='Sample', version='1.0.0', author='Tests', licence='GPL-3.0-or-later',
                targets=[dict(title_id='CUSA00000', app_version='01.00', executable_sha256=BUILD)],
                settings={'mode': dict(type='choice', choices=['on', 'off'], default='on')},
                operations=[dict(type='asset-patch', target=BUILD, recipe=dict(
                    asset='level/title.bld', source_sha256='c' * 64,
                    chunks=[dict(offset=4096, allocation=4096, edits=[dict(offset=16, expected_hex='0102', replacement_hex='0304')])]))])
    data.update(changes)
    return mods.parse(data)


def code(offset, expected='0011', ident='p'):
    return dict(type='code-patch', target=BUILD, id=ident, file_offset=offset, expected_hex=expected,
                replacement_hex='ff' * (len(expected) // 2), reason='test')


class ManifestTest(unittest.TestCase):
    def test_parses_and_plans(self):
        applied = mods.plan({'sample': manifest()}, ['sample'], BUILD)
        self.assertEqual(applied[0]['settings'], {'mode': 'on'})
        profile = mods.asset_profile(applied, 'CUSA00000', '01.00', BUILD)
        self.assertEqual(profile['assets'][0]['asset'], 'level/title.bld')
        self.assertEqual(mods.record(applied)[0]['operations'][0]['type'], 'asset-patch')

    def test_rejects_bad_manifests(self):
        for change in (dict(schema_version=2), dict(id='Bad Id'), dict(licence=''), dict(targets=[]),
                       dict(targets=[dict(title_id='X', app_version='1', executable_sha256='A' * 64)]),
                       dict(requires=['sample']), dict(operations=[dict(type='replace-everything')]),
                       dict(operations=[dict(code(0), target=OTHER)]),
                       dict(operations=[dict(code(0), replacement_hex='ff')]),
                       dict(operations=[dict(type='host-option', environment={'LD_PRELOAD': 'x'})]),
                       dict(settings={'n': dict(type='number', min=0, max=1, default=2)})):
            with self.subTest(change=change), self.assertRaises(mods.ModError):
                manifest(**change)

    def test_refuses_other_build(self):
        with self.assertRaisesRegex(mods.ModError, 'does not support this game build'):
            mods.plan({'sample': manifest()}, ['sample'], OTHER)

    def test_refuses_code_byte_mismatch(self):
        sample = manifest(operations=[code(2)])
        self.assertEqual(len(mods.plan({'sample': sample}, ['sample'], BUILD, executable=b'\0\0\0\x11')), 1)
        with self.assertRaisesRegex(mods.ModError, 'original bytes mismatch'):
            mods.plan({'sample': sample}, ['sample'], BUILD, executable=b'\0\0\0\x12')

    def test_overlap_names_both_mods(self):
        first, second = manifest('first'), manifest('second')
        second['operations'][0]['recipe']['chunks'][0]['edits'][0]['offset'] = 17
        with self.assertRaisesRegex(mods.ModError, 'mods first and second both change'):
            mods.plan({'first': first, 'second': second}, ['second', 'first'], BUILD)
        second['operations'][0]['recipe']['chunks'][0]['edits'][0]['offset'] = 18
        self.assertEqual(len(mods.plan({'first': first, 'second': second}, ['first', 'second'], BUILD)), 2)
        a, b = manifest('a', operations=[code(0, '001122')]), manifest('b', operations=[code(2, '22')])
        with self.assertRaisesRegex(mods.ModError, 'mods a and b both change bytes 2..3 of eboot.bin'):
            mods.plan({'a': a, 'b': b}, ['a', 'b'], BUILD, executable=b'\0\x11\x22\x11')

    def test_host_options_and_conditions(self):
        options = [dict(type='host-option', environment={'SKY_X': '1'}, when=dict(setting='mode', equals='on'))]
        a, b = manifest('a', operations=options), manifest('b', operations=[dict(type='host-option', environment={'SKY_X': '2'})])
        self.assertEqual(mods.host_environment(mods.plan({'a': a}, ['a'], BUILD)), {'SKY_X': '1'})
        with self.assertRaisesRegex(mods.ModError, 'has no operations'):
            mods.plan({'a': a}, ['a'], BUILD, settings={'a': {'mode': 'off'}})
        with self.assertRaisesRegex(mods.ModError, 'invalid value'):
            mods.plan({'a': a}, ['a'], BUILD, settings={'a': {'mode': 'maybe'}})
        with self.assertRaisesRegex(mods.ModError, 'mods a and b both set SKY_X'):
            mods.plan({'a': a, 'b': b}, ['a', 'b'], BUILD)

    def test_order_requires_and_conflicts(self):
        base = manifest('base')
        top = manifest('top', requires=['base'])
        top['operations'] = copy.deepcopy(top['operations'])
        top['operations'][0]['recipe']['asset'] = 'level/other.bld'
        self.assertEqual(mods.order(['top'], {'base': base, 'top': top}), ['base', 'top'])
        with self.assertRaisesRegex(mods.ModError, 'not installed'):
            mods.order(['top'], {'top': top})
        rival = manifest('rival', conflicts=['base'])
        with self.assertRaisesRegex(mods.ModError, 'rival conflicts with mod base'):
            mods.order(['rival', 'base'], {'base': base, 'rival': rival})

    def test_discovery_refuses_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for base in ('profiles/mods/x', 'mods/x'):
                (root / base).mkdir(parents=True)
                data = {key: value for key, value in manifest().items() if key != 'source'}
                (root / base / 'mod.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(mods.ModError, 'defined by both'):
                mods.discover(root)
            (root / 'mods/x/mod.json').unlink()
            self.assertTrue(mods.discover(root)['sample']['builtin'])

    def test_recipe_files_and_withheld_recipes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = manifest()['operations'][0]['recipe']
            gates = manifest('gates', operations=[dict(type='asset-patch', target=BUILD, profile='profiles/patches/gates.json')])
            gates.update(builtin=True, root=str(root))
            with self.assertRaisesRegex(mods.ModError, 'unavailable in this checkout'):
                mods.plan({'gates': gates}, ['gates'], BUILD)
            (root / 'profiles/patches').mkdir(parents=True)
            (root / 'profiles/patches/gates.json').write_text(json.dumps(dict(executable_sha256=OTHER, assets=[recipe])))
            with self.assertRaisesRegex(mods.ModError, 'different executable'):
                mods.plan({'gates': gates}, ['gates'], BUILD)
            (root / 'profiles/patches/gates.json').write_text(json.dumps(dict(executable_sha256=BUILD, assets=[recipe])))
            applied = mods.plan({'gates': gates}, ['gates'], BUILD)
            self.assertEqual(mods.asset_profile(applied, 'CUSA00000', '01.00', BUILD)['assets'], [recipe])
            # A user mod reads only from its own folder; a built-in one only from profiles/patches.
            outside = dict(gates, builtin=False, source=str(root / 'mods/gates'))
            with self.assertRaisesRegex(mods.ModError, 'unavailable'):
                mods.plan({'gates': outside}, ['gates'], BUILD)
            with self.assertRaises(mods.ModError):
                manifest(operations=[dict(type='asset-patch', target=BUILD, profile='../escape.json')])
            stray = dict(gates, operations=[dict(type='asset-patch', target=BUILD, profile='tools/x.json')])
            with self.assertRaisesRegex(mods.ModError, 'must live in profiles/patches'):
                mods.plan({'gates': stray}, ['gates'], BUILD)

    def test_whole_file_writes_conflict_with_edits(self):
        movies = manifest('movies', operations=[dict(type='generated', handler='movies', target=BUILD, writes=['level/title.bld'])])
        with self.assertRaisesRegex(mods.ModError, 'mods movies and sample both change level/title.bld'):
            mods.plan({'movies': movies, 'sample': manifest()}, ['sample', 'movies'], BUILD)
        writes = []
        applied = mods.plan({'sample': manifest()}, ['sample'], BUILD, writes=writes)
        self.assertEqual(mods.record(applied)[0]['operations'][0]['assets'], ['level/title.bld'])
        generated = manifest()['operations'][0]['recipe']
        with self.assertRaisesRegex(mods.ModError, 'mods sample and glyphs both change bytes 16..18'):
            mods.claim(writes, 'glyphs', list(mods.recipe_ranges(generated)))
        with self.assertRaises(mods.ModError):
            manifest(operations=[dict(type='generated', handler='Bad Handler', target=BUILD)])

    def test_builtin_manifests_parse(self):
        available = mods.discover(ROOT)
        for ident in ('nightmare', 'level-events', 'controller-glyphs', 'movie-audio', 'element-gates',
                      'traptanium', 'unlock-expansions', 'replay-expansion-intros'):
            self.assertTrue(available[ident]['builtin'], ident)
        self.assertTrue(mods.supports(available, "movie-audio", json.loads(
            (ROOT / 'profiles/patches/trap-team-us-01.01-movie-audio.json').read_text())['executable_sha256']))
        self.assertFalse(mods.supports(available, 'movie-audio', BUILD))

    def test_launcher_catalogue_statuses(self):
        from unittest.mock import patch
        from tools import launcher_mods
        with patch.object(launcher_mods, 'build', return_value=None):
            rows, error = launcher_mods.catalogue(ROOT, {'id': 'trap-team'})
        self.assertIsNone(error)
        self.assertEqual({row['status'] for row in rows}, {'not-installed'})
        us = json.loads((ROOT / 'profiles/patches/trap-team-us-01.01-nightmare.json').read_text())['executable_sha256']
        with patch.object(launcher_mods, 'build', return_value=('CUSA00626', '01.01', us)):
            status = {row['id']: row for row in launcher_mods.catalogue(ROOT, {'id': 'trap-team'})[0]}
        self.assertEqual(status['nightmare']['status'], 'ready')
        self.assertTrue(status['nightmare']['controlled'])
        self.assertIsNone(status['element-gates']['controlled'])
        with patch.object(launcher_mods, 'build', return_value=('CUSA00000', '01.00', BUILD)):
            self.assertEqual({row['status'] for row in launcher_mods.catalogue(ROOT, {'id': 'x'})[0]}, {'other-build'})

    def test_builtin_nightmare_matches_profiles(self):
        nightmare = mods.read(ROOT / 'profiles/mods/nightmare')
        for name in ('trap-team-us-01.01-nightmare.json', 'trap-team-nightmare.json'):
            profile = json.loads((ROOT / 'profiles/patches' / name).read_text())
            applied = mods.plan({'nightmare': nightmare}, ['nightmare'], profile['executable_sha256'])
            self.assertEqual(mods.asset_profile(applied, profile['title_id'], profile['app_version'], profile['executable_sha256']),
                             nightmare_mod.recipe(profile))


if __name__ == '__main__':
    unittest.main()

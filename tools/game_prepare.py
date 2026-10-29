#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified, resumable preparation of one library installation. Stdout is JSONL."""
import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import struct
import subprocess
import sys
import uuid

try:
    from . import game_library, game_build, link_native, patches, resolution
    from .file_integrity import VerifiedDigests
except ImportError:
    import game_library, game_build, link_native, patches, resolution
    from file_integrity import VerifiedDigests

PREPARATION_VERSION = 1  # Bump only when output contracts or verification rules change.
ROOT = Path(__file__).resolve().parents[1]
PACK_FILES = ('image.pack','imports.types','boot.plan','metadata.json')


class PreparationError(ValueError):
    pass


def file_hash(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise PreparationError('Preparation refuses redirected files')
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def stamp(path):
    try:return list(VerifiedDigests.stamp(Path(path)))
    except (OSError,ValueError):return None


def state_path(root, entry):
    game_library.selector(entry['title_id'],entry['app_version'])
    return Path(root)/'.local/game-preparation'/entry['title_id']/entry['app_version']/'state.json'


def read_state(root, entry):
    path = state_path(root,entry)
    try:
        if any(p.is_symlink() for p in (path,*path.parents)):return {}
        value = json.loads(path.read_text())
        if not isinstance(value,dict) or value.get('schema_version')!=1 or not isinstance(value.get('steps'),dict):return {}
        value['steps'] = {name:marker for name,marker in value['steps'].items() if isinstance(marker,dict)}
        if value.get('failure') and not isinstance(value['failure'],dict):
            value['failure'] = dict(name='verify-executable',message='Preparation record needs repair')
        return value
    except (OSError,ValueError,TypeError):return {}


def event(name, state, fraction, message):
    return dict(name=name,state=state,fraction=fraction,message=message)


def json_progress(value):
    print(json.dumps(value),flush=True)


@dataclass
class Step:
    name: str
    inputs: object
    action: object
    message: str = ''


class Pipeline:
    def __init__(self, root, entry, progress=json_progress):
        self.root = Path(root).absolute();self.entry = entry;self.progress = progress
        self.path = state_path(self.root,entry)
        self.record = read_state(self.root,entry) or dict(schema_version=1,steps={})
        self.digests = VerifiedDigests(file_hash)

    def key(self, path):
        path = Path(path).absolute()
        try:return path.relative_to(self.root).as_posix()
        except ValueError:return str(path)

    def inputs(self, step):
        spec = step.inputs() if callable(step.inputs) else step.inputs
        values = spec.get('values',{})
        hashes = {self.key(p):self.digests(Path(p)) if Path(p).is_file() else 'absent' for p in spec.get('files',[])}
        payload = dict(values=values,files=hashes,engine=str(PREPARATION_VERSION))
        fingerprint = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        return fingerprint,hashes

    def valid(self, marker, key):
        if marker.get('fingerprint')!=key or not isinstance(marker.get('outputs'),dict) or not marker['outputs']:return False
        for name,digest in marker['outputs'].items():
            try:
                path = game_build.relative(self.root,name)
                if not path.is_relative_to(self.root/'out') and not path.is_relative_to(self.root/'.local'):return False
                if self.digests(path)!=digest:return False
            except (OSError,ValueError,TypeError):return False
        return True

    def save(self):
        game_library.write_json(self.path,self.record)

    def run(self, steps):
        total = len(steps)
        for index,step in enumerate(steps):
            self.progress(event(step.name,'running',index/total,step.message or step.name))
            try:
                key,hashes = self.inputs(step)
                previous = self.record['steps'].get(step.name,{})
                if self.valid(previous,key):
                    previous['stamps'] = {name:stamp(self.root/name) for name in {*hashes,*previous['outputs']}}
                    self.record.pop('failure',None);self.save()
                    self.progress(event(step.name,'skipped',(index+1)/total,'Already up to date.'))
                    continue
                outputs = step.action(key)
                checked = {}
                for path in outputs:
                    path = Path(path).absolute()
                    if not path.is_relative_to(self.root/'out') and not path.is_relative_to(self.root/'.local'):
                        raise PreparationError('Prepared output must be private to this project')
                    checked[self.key(path)] = file_hash(path)
                if not checked:raise PreparationError('Preparation step produced no verified output')
                if self.inputs(step)[0]!=key:raise PreparationError('Inputs changed during preparation; run Repair again')
                self.record['steps'][step.name] = dict(fingerprint=key,engine=str(PREPARATION_VERSION),input_hashes=hashes,outputs=checked,
                    stamps={name:stamp(self.root/name) for name in {*hashes,*checked}})
                self.record.pop('failure',None);self.save()
                self.progress(event(step.name,'complete',(index+1)/total,'Finished.'))
            except (OSError,ValueError,KeyError,TypeError,struct.error) as error:
                self.record['failure'] = dict(name=step.name,message=str(error));self.save()
                self.progress(event(step.name,'failed',index/total,str(error)))
                raise PreparationError(f'{step.name}: {error}') from error
        return self.record

    def report(self, name, key, value):
        path = self.path.parent/'reports'/f'{name}-{key}-{uuid.uuid4().hex[:8]}.json'
        game_library.write_json(path,value)
        return [path]


def run_command(argv, root):
    """Build output is diagnostic stderr; stdout remains machine-readable JSONL."""
    result = subprocess.run([str(arg) for arg in argv],cwd=root,stdout=sys.stderr,stderr=sys.stderr)
    if result.returncode:raise PreparationError(f'Build command failed ({result.returncode}). See the preparation log.')


def source_files(folder):
    suffixes = {'.c','.cpp','.h','.hpp','.S','.cmake'}
    return sorted(p for p in Path(folder).rglob('*') if p.is_file() and (p.suffix in suffixes or p.name=='CMakeLists.txt'))


def runtime_paths(root):
    return (root/'.local/native-gpu-build/skylanders-native-host',root/'out/dependency-build/renderer/libskyrender.so')


def renderer_step(pipeline):
    root = pipeline.root;_,library = runtime_paths(root);source = root/'.local/skyrender/gpu'
    def build(key):
        if not library.is_file() or 'renderer' in pipeline.record['steps']:
            if not (source/'CMakeLists.txt').is_file():
                raise PreparationError('Renderer source is missing. Restore the runtime files supplied with this project, then choose Repair.')
            prefix = root/'.local/deps/prefix'
            run_command(['cmake','-S',source,'-B',library.parent,'-G','Ninja','-DCMAKE_BUILD_TYPE=RelWithDebInfo',
                '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',f'-DCMAKE_PREFIX_PATH={prefix}',f'-DVulkan_INCLUDE_DIR={prefix}/include',
                '-DSKY_RENDERER_LTO=OFF','-DSKY_RENDERER_PGO=off','-DFETCHCONTENT_FULLY_DISCONNECTED=ON'],root)
            run_command(['cmake','--build',library.parent,'--target','skyrender','-j','4'],root)
        with library.open('rb') as stream:
            if stream.read(4)!=b'\x7fELF':raise PreparationError('Renderer library is missing or invalid')
        return [library]
    return Step('renderer',lambda:dict(files=source_files(source),values={'source_available':source.exists()}),build,'Checking the graphics runtime…')


def portal_source(root):
    cache = root/'.local/native-gpu-build/CMakeCache.txt'
    if not cache.is_file():return None
    for line in cache.read_text().splitlines():
        if line.startswith('SKY_PORTAL_SOURCE_ROOT:PATH='):
            value = line.split('=',1)[1]
            if not value:return None
            source = Path(value)
            if not source.is_dir():
                moved = root.parent.parent
                if (moved/'src/runtime/cemu_portal.cpp').is_file():return moved
            return source
    return None


def runtime_step(pipeline):
    root = pipeline.root;host,library = runtime_paths(root);build_dir = host.parent
    def build(key):
        if not host.is_file() or 'runtime' in pipeline.record['steps']:
            if not (root/'native/CMakeLists.txt').is_file():raise PreparationError('Native runtime source is missing. Restore the runtime files, then choose Repair.')
            args = ['cmake','-S',root/'native','-B',build_dir,'-DCMAKE_BUILD_TYPE=RelWithDebInfo',
                f'-DSKY_RENDERER_ROOT={root/".local/skyrender"}',f'-DSKY_RENDERER_LIBRARY={library}',
                f'-DCMAKE_PREFIX_PATH={root/".local/deps/prefix"}']
            # Preserve the configured portal provider, including after relocation.
            portal = portal_source(root)
            if portal:
                if not portal.is_dir():raise PreparationError('Portal runtime source is missing. Restore it, then choose Repair.')
                args.append('-DSKY_PORTAL_SOURCE_ROOT='+str(portal))
            run_command(args,root);run_command(['cmake','--build',build_dir,'--target','skylanders-native-host','-j','4'],root)
        with host.open('rb') as stream:
            if stream.read(4)!=b'\x7fELF':raise PreparationError('Native runtime is missing or invalid')
        check_dependencies(host)
        return [host]
    def inputs():
        portal = portal_source(root)
        portal_files = [portal/p for p in ('src/runtime/cemu_portal.cpp','Cemu-main/src/Cafe/OS/libs/nsyshid/Skylander.cpp','Cemu-main/src/Common/unix/FileStream_unix.cpp')] if portal else []
        return dict(files=[*source_files(root/'native'),*source_files(root/'.local/skyrender/src'),*portal_files,library],values={'source_available':(root/'native').exists(),'portal':str(portal) if portal else None})
    return Step('runtime',inputs,build,'Checking the game runtime…')


def check_dependencies(host):
    try:dependencies = subprocess.run(['ldd',str(host)],capture_output=True,text=True)
    except OSError as error:raise PreparationError('runtime: The runtime checker is unavailable. Restore the runtime tools, then choose Repair.') from error
    if dependencies.returncode or 'not found' in dependencies.stdout:
        print(dependencies.stdout+dependencies.stderr,file=sys.stderr)
        raise PreparationError('runtime: A runtime dependency is missing. Restore the runtime files, then choose Repair.')


def recipe_paths(root, prep):
    return {name:game_build.relative(root,path) for name,path in prep['recipes'].items()}


def plan(pipeline, install, config):
    root = pipeline.root;prep = config['preparation'];digest = config['executable_sha256']
    tools = [Path(__file__).with_name(name+'.py') for name in ('game_build','link_native','prepare_native','module_graph','executable','patches','resolution','file_integrity')]
    required = recipe_paths(root,prep)
    optional = {name:game_build.relative(root,path) for name,path in prep.get('optional_recipes',{}).items()}
    if not isinstance(prep.get('variants'),dict) or any(not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',v) for v in prep['variants']):
        raise PreparationError('Invalid preparation variant')
    module_names = prep.get('modules',[])
    if not isinstance(module_names,list) or len(module_names)>15 or any(not isinstance(name,str) or not name or Path(name).name!=name or name in ('.','..') for name in module_names):raise PreparationError('Invalid profile module name')
    modules = [install.source('sce_module/'+name) for name in module_names]
    profile_file = next(p for p in sorted((root/'profiles').glob('*.json')) if json.loads(p.read_text()).get('id')==config['profile_id'])
    def verify(key):
        actual = file_hash(install.source('eboot.bin'))
        if actual!=digest or actual!=pipeline.entry['executable_sha256']:raise PreparationError('The game file changed. Install the matching supported game again.')
        for module in modules:
            if not module.is_file():raise PreparationError('A required game module is missing: '+module.name)
            if module.stat().st_size>512*1024*1024:raise PreparationError('A game module exceeds the inspection limit: '+module.name)
        return pipeline.report('verify',key,dict(executable_sha256=actual,title_id=install.title_id,app_version=install.app_version))
    steps = [Step('verify-executable',dict(files=[install.source('eboot.bin'),*modules,profile_file]),verify,'Checking your game files…')]
    def validate_recipe(path):
        record = json.loads(path.read_text())
        if (record.get('title_id'),record.get('app_version'),record.get('executable_sha256'))!=(install.title_id,install.app_version,digest):
            raise PreparationError('Recipe does not match the selected executable: '+path.name)
        return record
    def validate(key):
        availability = {}
        for name,path in required.items():
            record = validate_recipe(path)
            if name=='resolution':
                if set(record.get('pack_sha256',{}))!=set(prep['variants']):raise PreparationError('Resolution recipe does not cover the allowed variants')
                renderer = install.source('renderer/tfbRenderer.igx')
                if file_hash(renderer)!=record['renderer_sha256']:raise PreparationError('Graphics asset does not match the verified recipe')
            if 'asset' in record:
                relative = Path(record['asset'])
                if relative.is_absolute() or '..' in relative.parts:raise PreparationError('Invalid recipe asset path')
                expected = record.get('asset_sha256',record.get('source_sha256'))
                if expected and file_hash(install.source(relative))!=expected:raise PreparationError('Game asset does not match '+path.name)
            availability[name] = True
        for name,path in optional.items():
            try:validate_recipe(path);availability[name] = True
            except (OSError,ValueError):availability[name] = False
        return pipeline.report('recipes',key,availability)
    def recipe_inputs():
        files = [*required.values(),*optional.values()]
        for name,path in required.items():
            if path.is_file():
                record = json.loads(path.read_text())
                if name=='resolution':files.append(install.source('renderer/tfbRenderer.igx'))
                if 'asset' in record:files.append(install.source(record['asset']))
        return dict(files=files,values={'executable':digest})
    steps.append(Step('recipes',recipe_inputs,validate,'Checking graphics and game options…'))
    steps += [renderer_step(pipeline),runtime_step(pipeline)]
    for variant,record in prep['variants'].items():
        patch_path = game_build.relative(root,record['patch']) if record.get('patch') else None
        def build(key,variant=variant,patch_path=patch_path):
            original = install.source('eboot.bin').read_bytes();modified = bytearray(original)
            if patch_path:
                manifest = validate_recipe(patch_path)
                for offset,before,after,_ in patches.validate(original,manifest):modified[offset:offset+len(before)] = after
            packed,types,metadata = link_native.link_images([('eboot.bin',bytes(modified)),*[(name,path.read_bytes()) for name,path in zip(module_names,modules)]])
            recipe = json.loads(required['resolution'].read_text())
            if hashlib.sha256(packed).hexdigest()!=recipe['pack_sha256'][variant]:raise PreparationError('Linked pack differs from the verified build; check the game modules')
            resolution.patch_pack(packed,'1080p',variant,recipe)
            boot = link_native.boot_plan(metadata)
            output = root/'out/prepared-games'/install.title_id/install.app_version/variant/(key[:20]+'-'+uuid.uuid4().hex[:8])
            output.mkdir(parents=True)
            for name,data in [('image.pack',packed),('imports.types',types),('boot.plan',boot),('metadata.json',(json.dumps(metadata,indent=2)+'\n').encode())]:
                with (output/name).open('xb') as stream:stream.write(data)
            return [output/name for name in PACK_FILES]
        inputs = dict(files=[install.source('eboot.bin'),*modules,*tools,required['resolution'],*([patch_path] if patch_path else [])],values={'variant':variant,'modules':module_names})
        steps.append(Step('pack.'+variant,inputs,build,'Preparing your game…'))
    return steps


def prepare(root, entry, progress=json_progress, optional=()):
    root = Path(root).absolute()
    if not isinstance(entry,dict):entry = game_library.resolve_entry(root,entry)
    with game_library.locked(root/'.local/game-preparation'):
        pipeline = Pipeline(root,entry,progress)
        try:
            install = game_library.discover(entry)
            profile,build,digest = game_build.identity(root,install)
            variants = build['preparation']['variants']
            if not variants:raise PreparationError('This build has no allowed variants')
            config = dict(preparation=build['preparation'],executable_sha256=digest,profile_id=profile['id'])
            steps = plan(pipeline,install,config)
        except (OSError,ValueError,KeyError,TypeError) as error:
            progress(event('verify-executable','failed',0,str(error)))
            raise PreparationError('verify-executable: '+str(error)) from error
        result = pipeline.run(steps)
        for name in ('controller-art','portraits','variant-art'):
            path = root/('.local/controller-glyphs/manifest.json' if name=='controller-art' else '.local/portal-assets/variant-art/sources.json' if name=='variant-art' else '.local/portal-assets/sources.json')
            progress(event('optional.'+name,'available' if path.is_file() else 'optional',1,
                name+' is optional and does not affect whether the game can start.'))
        for name in optional:prepare_optional(root,entry,name,progress)
        try:check_dependencies(runtime_paths(root)[0])
        except (OSError,ValueError) as error:
            pipeline.record['failure'] = dict(name='runtime',message=str(error));pipeline.save()
            progress(event('runtime','failed',1,str(error)));raise
        progress(event('ready','complete',1,'Game setup is complete.'))
        return result


def prepare_optional(root, entry, name, progress):
    """Optional artwork has its own markers and failures, separate from core readiness."""
    def optional_progress(value):
        if value['state']=='failed':value = {**value,'state':'optional-failed'}
        progress(value)
    worker = Pipeline(root,entry,optional_progress)
    worker.path = worker.path.parent/('optional-'+name)/'state.json'
    try:worker.record = json.loads(worker.path.read_text())
    except (OSError,ValueError):worker.record = dict(schema_version=1,steps={})
    source = None
    try:
        if name=='controller-art':
            try:from . import import_controller_glyphs as importer
            except ImportError:import import_controller_glyphs as importer
            destination = root/'.local/controller-glyphs'
            try:source = importer.discover()
            except (OSError,ValueError):
                if not destination.exists():raise
        elif name=='portraits':
            try:from . import fetch_portal_portraits as importer
            except ImportError:import fetch_portal_portraits as importer
            destination = root/'.local/portal-assets'
        elif name=='variant-art':
            try:from . import fetch_variant_art as importer
            except ImportError:import fetch_variant_art as importer
            destination = root/'.local/portal-assets/variant-art'
        else:raise ValueError('Unknown optional artwork step')
        def action(key):
            with redirect_stdout(sys.stderr):
                if name=='controller-art':
                    if not destination.exists():importer.prepare(source,destination)
                    manifest = json.loads((destination/'manifest.json').read_text())
                    if 'menu-atlas.rgba' not in manifest.get('files',{}):raise ValueError('Optional controller artwork is incomplete')
                    for filename,digest in manifest['files'].items():
                        path = game_build.relative(destination,filename)
                        if file_hash(path)!=digest:raise ValueError('Optional controller artwork needs repair')
                else:importer.prepare(destination)
            return sorted(p for p in destination.rglob('*') if p.is_file())
        inputs = dict(files=[Path(importer.__file__),*sorted(source.glob('*.png'))] if source else [Path(importer.__file__)],values={'optional':name})
        if name=='portraits':inputs['files'].append(root/'profiles/trap-team-portal.json')
        worker.run([Step('optional.'+name,inputs,action,'Adding optional artwork…')])
    except (OSError,ValueError,ImportError,KeyError,TypeError) as error:
        progress(event('optional.'+name,'optional-failed',1,str(error)))


def shallow_ready(root, entry, variant):
    """Metadata changes from hard links are harmless when the recorded bytes still match."""
    required = ['verify-executable','recipes','renderer','runtime','pack.'+variant]
    def check(record, refresh=False):
        if not record:raise PreparationError('verify-executable')
        changed = False;digests = VerifiedDigests(file_hash)
        for name in required:
            marker = record['steps'].get(name)
            if not isinstance(marker,dict) or marker.get('engine')!=str(PREPARATION_VERSION):raise PreparationError(name)
            if not isinstance(marker.get('outputs'),dict) or not marker['outputs'] or not isinstance(marker.get('input_hashes'),dict) or not isinstance(marker.get('stamps'),dict):raise PreparationError(name)
            hashes = {**marker['input_hashes'],**marker['outputs']}
            if not set(hashes).issubset(marker['stamps']):raise PreparationError(name)
            for path,digest in hashes.items():
                current = stamp(root/path)
                if current==marker['stamps'][path]:continue
                if not refresh:return False
                try:actual = digests(root/path) if (root/path).is_file() else 'absent'
                except (OSError,ValueError) as error:raise PreparationError(name) from error
                if actual!=digest:raise PreparationError(name)
                marker['stamps'][path] = stamp(root/path);changed = True
        if record.get('failure'):raise PreparationError(record['failure'].get('name','verify-executable'))
        return changed if refresh else True
    record = read_state(root,entry)
    try:
        if check(record):return record
        with game_library.locked(root/'.local/game-preparation'):
            record = read_state(root,entry)
            if check(record,True):game_library.write_json(state_path(root,entry),record)
        return record
    except PreparationError as error:
        raise PreparationError(f'Game setup needs {error}. Choose Repair in the launcher to finish setup.') from error


def require_ready(root, entry, variant='60-delta', *, deep=True):
    root = Path(root).absolute()
    if not deep:return shallow_ready(root,entry,variant)
    record = read_state(root,entry)
    def missing(name):raise PreparationError(f'Game setup needs {name}. Choose Repair in the launcher to finish setup.')
    if not record:missing('verify-executable')
    required = ['verify-executable','recipes','renderer','runtime','pack.'+variant]
    pipeline = None;steps = {}
    if deep:
        try:
            install = game_library.discover(entry)
            profile,build,digest = game_build.identity(root,install)
            pipeline = Pipeline(root,entry,lambda value:None)
            config = dict(preparation=build['preparation'],executable_sha256=digest,profile_id=profile['id'])
            steps = {step.name:step for step in plan(pipeline,install,config)}
        except (OSError,ValueError,KeyError,TypeError):missing('verify-executable')
    for name in required:
        marker = record['steps'].get(name)
        if not isinstance(marker,dict) or marker.get('engine')!=str(PREPARATION_VERSION):missing(name)
        if not isinstance(marker.get('outputs'),dict) or not marker['outputs'] or not isinstance(marker.get('input_hashes'),dict) or not isinstance(marker.get('stamps'),dict):missing(name)
        if not {*marker['outputs'],*marker['input_hashes']}.issubset(marker['stamps']):missing(name)
        if deep:
            if name not in steps:missing(name)
            try:
                key,_ = pipeline.inputs(steps[name])
                if not pipeline.valid(marker,key):missing(name)
            except (OSError,ValueError,KeyError,TypeError):missing(name)
        elif any(stamp(root/path)!=value for path,value in marker['stamps'].items()):missing(name)
    if record.get('failure'):missing(record['failure']['name'])
    if deep:check_dependencies(runtime_paths(root)[0])
    return record


def relocate_inputs(root, entry, moves):
    """Rebase verified preparation markers after an explicitly requested game move."""
    root = Path(root).absolute()
    if not read_state(root,entry):return
    def relocated(name):
        path = root/name
        for before,after in moves.items():
            if path.is_relative_to(before):return str(Path(after)/path.relative_to(before))
        return str(path)
    record = read_state(root,entry)
    if not any(relocated(name)!=str(root/name) for marker in record['steps'].values() for name in marker.get('input_hashes',{})):return
    with game_library.locked(root/'.local/game-preparation'):
        pipeline = Pipeline(root,entry,lambda value:None)
        install = game_library.discover(entry)
        profile,build,digest = game_build.identity(root,install)
        config = dict(preparation=build['preparation'],executable_sha256=digest,profile_id=profile['id'])
        changed = False
        for step in plan(pipeline,install,config):
            marker = pipeline.record['steps'].get(step.name)
            if not marker or marker.get('engine')!=str(PREPARATION_VERSION):continue
            rebased = {pipeline.key(Path(relocated(name))):value for name,value in marker['input_hashes'].items()}
            if rebased==marker['input_hashes']:continue
            key,hashes = pipeline.inputs(step)
            candidate = {**marker,'fingerprint':key}
            if hashes!=rebased or not pipeline.valid(candidate,key):continue
            marker.update(fingerprint=key,input_hashes=hashes,
                stamps={name:stamp(root/name) for name in {*hashes,*marker['outputs']}})
            changed = True
        if changed:pipeline.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--game',help='TITLE_ID[@APP_VER]')
    parser.add_argument('--optional',action='append',choices=('controller-art','portraits','variant-art'),default=[])
    args = parser.parse_args(argv)
    try:prepare(args.root,args.game,optional=args.optional)
    except (OSError,ValueError) as error:
        json_progress(event('error','failed',0,str(error)));return 1
    return 0


if __name__=='__main__':
    # QProcess cancellation must also stop any compiler children.
    if os.getpgrp()!=os.getpid():os.setsid()
    def stop(signum,frame):
        signal.signal(signum,signal.SIG_DFL);os.killpg(os.getpgrp(),signum)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    sys.exit(main())

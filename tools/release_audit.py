#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check source publication candidates and optionally create a clean source tar.

This is a bounded packaging check, not a legal clearance or binary-release audit.
It never stages/commits files, edits private data or publishes anything.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import os

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES={'LICENSE','LICENSE_SCOPE.md','NOTICE.md','THIRD_PARTY_NOTICES.md','README.md','CONTRIBUTING.md',
            'AGENTS.md','SOURCE_MANIFEST.json','references.lock.json','release-policy.json','.gitignore','.gitattributes'}
SCOPES={'docs','native','tools','tests','profiles','patches','LICENSES','.github'}
SUFFIXES={'.md','.txt','.py','.cpp','.c','.h','.hpp','.S','.inc','.sh','.ld','.json','.patch','.yml','.yaml','.toml','.html','.css','.js'}
CODE={'.py','.cpp','.c','.h','.hpp','.S','.inc','.sh','.ld','.html','.css','.js'}
MAGIC=(b'\x7fELF',b'MZ',b'\x01ZGI',b'IGA\x1a',b'DDS ',b'\x89PNG',b'RIFF',b'PK\x03\x04',b'KB2',b'\x00PSF',b'\x4f\x15\x3d\x1d')
PRIVATE_KEY=re.compile(r'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----\r?\n')
INLINE_IMAGE=re.compile(r'data:image/[^;,\s]+;base64,[A-Za-z0-9+/=]{256,}')


def policy(root):
    value=json.loads((Path(root)/'release-policy.json').read_text())
    if (value.get('schema_version')!=1 or value.get('project_license')!='GPL-3.0-or-later' or
            not isinstance(value.get('withheld'),dict) or not isinstance(value.get('required'),list)):
        raise ValueError('invalid publication policy')
    return value


def allowed(name,record):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or path.as_posix()!=name:return False
    if name in record['withheld']:return False
    if name in ROOT_FILES:return True
    return bool(path.parts and path.parts[0] in SCOPES and
                (path.suffix in SUFFIXES or path.name=='CMakeLists.txt') and
                not any(part.startswith('.') and part!='.github' for part in path.parts))


def candidates(root,record):
    root=Path(root).resolve();result=[]
    for name in sorted(ROOT_FILES):
        if (root/name).exists() or (root/name).is_symlink():result.append(name)
    for directory in sorted(SCOPES):
        base=root/directory
        if base.is_symlink():raise ValueError('redirected source scope: '+directory)
        if not base.exists():continue
        for path in sorted(base.rglob('*')):
            name=path.relative_to(root).as_posix()
            if path.is_symlink():
                # A link under a public scope must never silently disappear.
                result.append(name)
            elif path.is_file() and allowed(name,record):result.append(name)
    return sorted(set(result))


def _inspect_json(value,path,errors):
    if isinstance(value,dict):
        for key,item in value.items():
            if key.endswith('_hex') and isinstance(item,str) and len(item)>512:
                errors.append(path+': bulk literal hex payload requires review/source-relative conversion')
            _inspect_json(item,path,errors)
    elif isinstance(value,list):
        for item in value:_inspect_json(item,path,errors)


def inspect(name,data,record):
    errors=[]
    if not allowed(name,record):return [name+': excluded/private/unreviewed publication path']
    if len(data)>4*1024*1024:return [name+': oversized source candidate']
    if data.startswith(MAGIC) or b'\x00' in data:return [name+': binary/game/artwork content is excluded']
    try:text=data.decode('utf-8')
    except UnicodeDecodeError:return [name+': source export accepts UTF-8 text only']
    if PRIVATE_KEY.search(text):errors.append(name+': private key material')
    if INLINE_IMAGE.search(text):errors.append(name+': embedded artwork requires review')
    if PurePosixPath(name).suffix in CODE and 'SPDX-License-Identifier:' not in text[:1024]:
        errors.append(name+': missing source license identifier')
    if name.endswith('.json'):
        try:_inspect_json(json.loads(text),name,errors)
        except ValueError:errors.append(name+': malformed JSON source file')
    return errors


def audit(root,names,loader=None):
    root=Path(root).resolve();record=policy(root);names=sorted(set(names));errors=[];files=[]
    if not names:errors.append('No source files selected; choose --tree or stage a reviewed source set.')
    for required in record['required']:
        if required not in names:errors.append('Missing publication notice: '+required)
    for name in names:
        if not allowed(name,record):errors.extend(inspect(name,b'',record));continue
        path=root/name
        try:
            if loader is None:
                if path.is_symlink() or path.resolve()!=path or not path.is_file():raise ValueError('redirected/non-regular source file')
                if path.stat().st_size>4*1024*1024:raise ValueError('oversized source candidate')
                data=path.read_bytes()
            else:data=loader(name)
            errors.extend(inspect(name,data,record))
            files.append(dict(path=name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
        except (OSError,ValueError) as error:errors.append(name+': '+str(error))
    # Verify included license text identities, not just filenames.
    try:
        blobs={row['path']:row for row in files}
        dependencies=json.loads((loader('LICENSES/dependencies.json') if loader else (root/'LICENSES/dependencies.json').read_bytes()))
        for component in dependencies['components']:
            notice=component['notice']
            if notice not in blobs or blobs[notice]['sha256']!=component['notice_sha256']:
                errors.append('Missing/changed dependency notice: '+notice)
        source=json.loads((loader('LICENSES/bbport-source.json') if loader else (root/'LICENSES/bbport-source.json').read_bytes()))
        if source['patch'] not in blobs or blobs[source['patch']]['sha256']!=source['patch_sha256']:
            errors.append('Missing/changed canonical provider patch')
    except (OSError,ValueError,KeyError,TypeError) as error:errors.append('Notice/provenance inventory unreadable: '+str(error))
    return dict(schema_version=1,kind='source-publication-audit',ok=not errors,files=files,errors=errors,
                withheld=record['withheld'],binary_release_ready=False,binary_release_blockers=record['binary_release_blockers'])


def git_selection(root,staged):
    command=['git','ls-files','-s','-z']
    rows=subprocess.run(command,cwd=root,check=True,stdout=subprocess.PIPE).stdout.split(b'\0');entries={}
    for row in rows:
        if not row:continue
        info,name=row.split(b'\t',1);mode,oid,stage=info.decode().split()
        if stage!='0':raise ValueError('unmerged index entry')
        entries[name.decode()]=(mode,oid)
    if staged:
        def load(name):
            mode,oid=entries[name]
            if mode not in ('100644','100755'):raise ValueError('symlink/submodule index entry is excluded')
            size=int(subprocess.run(['git','cat-file','-s',oid],cwd=root,check=True,stdout=subprocess.PIPE).stdout)
            if size>4*1024*1024:raise ValueError('oversized staged source candidate')
            return subprocess.run(['git','cat-file','blob',oid],cwd=root,check=True,stdout=subprocess.PIPE).stdout
        return list(entries),load
    return list(entries),None


def export_source(root,result,destination):
    if not result['ok']:raise ValueError('source audit must pass before export')
    root=Path(root).resolve();destination=Path(destination).absolute()
    if destination.exists() or destination.is_symlink():raise ValueError('export destination already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.parent.resolve()!=destination.parent:raise ValueError('redirected export destination')
    with tempfile.TemporaryDirectory(prefix='.source-export-',dir=destination.parent) as folder:
        staged=Path(folder)/'source.tar.gz'
        with staged.open('wb') as output,gzip.GzipFile(fileobj=output,mode='wb',mtime=0,filename='') as compressed,tarfile.open(fileobj=compressed,mode='w') as archive:
            for row in result['files']:
                path=root/row['path']
                if path.is_symlink() or path.resolve()!=path:raise ValueError('source redirected during export')
                data=path.read_bytes()
                if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('source changed during export')
                info=tarfile.TarInfo('SkylandersPS4/'+row['path']);info.size=len(data)
                info.mode=0o755 if path.stat().st_mode&0o111 else 0o644;info.mtime=0
                archive.addfile(info,io.BytesIO(data))
            manifest=json.dumps(dict(project_license='GPL-3.0-or-later',files=result['files'],withheld=result['withheld'],binary_release_ready=False),indent=2).encode()+b'\n'
            info=tarfile.TarInfo('SkylandersPS4/SOURCE_MANIFEST.json');info.size=len(manifest);info.mode=0o644;info.mtime=0
            archive.addfile(info,io.BytesIO(manifest))
        # Publish without replacing an existing user file.
        os.link(staged,destination)
    return destination


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--tree',action='store_true');mode.add_argument('--tracked',action='store_true');mode.add_argument('--staged',action='store_true')
    parser.add_argument('--export',type=Path);parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv)
    if args.export and (args.staged or args.tracked):parser.error('exports use --tree; index audit never changes or exports the index')
    try:
        record=policy(ROOT);names,loader=git_selection(ROOT,args.staged) if args.tracked or args.staged else (candidates(ROOT,record),None)
        result=audit(ROOT,names,loader)
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
        for error in result['errors']:print(error)
        print(f"Source audit: {'PASS' if result['ok'] else 'FAIL'} ({len(result['files'])} files; {len(result['withheld'])} withheld). Binary release readiness: not established.")
        if args.export:print('Source export:',export_source(ROOT,result,args.export))
        return 0 if result['ok'] else 1
    except (OSError,ValueError,subprocess.CalledProcessError) as error:parser.error(str(error))

if __name__=='__main__':raise SystemExit(main())

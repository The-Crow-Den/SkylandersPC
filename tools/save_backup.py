# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified rotating save snapshots. Call only with the session lock held."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid
try:
    from . import save_profile
except ImportError:
    import save_profile


def storage_root(environment=None):
    return save_profile.home_root(environment).parent/'save-backups'


def _title(value):
    if not isinstance(value,str) or not re.fullmatch(r'CUSA\d{5}',value):
        raise ValueError('invalid backup title')


def verify(path, title_id):
    """Verify metadata and every saved byte before offering a recovery point."""
    _title(title_id);path=Path(path)
    manifest=path/'snapshot.json';files=path/'files'
    if (path.is_symlink() or path.resolve()!=path or not path.is_dir() or
            manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>512*1024 or
            files.is_symlink() or not files.is_dir() or files.resolve()!=files or
            {p.name for p in path.iterdir()}!={'files','snapshot.json'}):
        raise ValueError('invalid or modified backup tree')
    record=json.loads(manifest.read_text())
    if (not isinstance(record,dict) or type(record.get('schema_version')) is not int or
            record['schema_version']!=1 or record.get('title_id')!=title_id or
            record.get('snapshot_id')!=path.name or not isinstance(record.get('files'),dict) or
            not record['files'] or len(record['files'])>4096 or
            not isinstance(record.get('created_utc'),str) or
            not re.fullmatch(r'\d{8}T\d{12}Z',record['created_utc']) or
            not isinstance(record.get('source_root'),str)):
        raise ValueError('invalid backup manifest')
    for name,value in record['files'].items():
        relative=Path(name)
        if (relative.is_absolute() or '..' in relative.parts or not relative.parts or
                not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value)):
            raise ValueError('invalid backup file identity')
    if save_profile._manifest(files)!=record['files']:
        raise ValueError('backup content failed integrity verification')
    return record


def snapshots(source_root, title_id, backup_root=None):
    _title(title_id);source_root=Path(source_root).resolve()
    profile=hashlib.sha256(str(source_root).encode()).hexdigest()[:16]
    root=Path(backup_root if backup_root is not None else storage_root())/title_id/profile
    if root.is_symlink() or root.resolve()!=root:raise ValueError('redirected backup root')
    if not root.exists():return []
    result=[]
    for path in root.iterdir():
        if path.name.startswith('.') or not path.is_dir() or path.is_symlink():continue
        try:
            record=verify(path,title_id)
            if record['source_root']!=str(source_root):continue
        except (OSError,ValueError,TypeError):
            # Unrecognised, corrupt or user-modified trees are never pruned.
            continue
        result.append((path,record))
    return sorted(result,key=lambda row:row[1]['created_utc'])


def snapshot(source_root, title_id, *, reason='manual', backup_root=None, keep=8):
    _title(title_id)
    if type(keep) is not int or not 1<=keep<=50 or reason not in ('manual','before-launch','after-exit'):
        raise ValueError('invalid backup policy')
    source_root=Path(source_root).resolve();source=source_root/title_id
    if not source.exists() and not source.is_symlink():return None
    if source.is_symlink() or not source.is_dir() or source.resolve()!=source:
        raise ValueError('redirected source title directory')
    expected=save_profile._manifest(source)
    if not expected:return None
    existing=snapshots(source_root,title_id,backup_root)
    if existing and existing[-1][1]['files']==expected:
        return {'status':'unchanged','path':str(existing[-1][0]),'files':len(expected)}
    profile=hashlib.sha256(str(source_root).encode()).hexdigest()[:16]
    root=Path(backup_root if backup_root is not None else storage_root())/title_id/profile
    if root.is_symlink() or root.resolve()!=root:raise ValueError('redirected backup root')
    root.mkdir(parents=True,exist_ok=True)
    created=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    identity=created+'-'+uuid.uuid4().hex[:8]
    target=root/identity
    record={'schema_version':1,'snapshot_id':identity,'created_utc':created,
            'title_id':title_id,'source_root':str(source_root),'reason':reason,'files':expected}
    with tempfile.TemporaryDirectory(prefix='.pending-',dir=root) as directory:
        staged=Path(directory)
        shutil.copytree(source,staged/'files',symlinks=True)
        if save_profile._manifest(staged/'files')!=expected or save_profile._manifest(source)!=expected:
            raise ValueError('save changed while taking backup')
        (staged/'snapshot.json').write_text(json.dumps(record,indent=2)+'\n')
        target.mkdir()  # reserve without overwriting any existing snapshot
        try:
            staged.replace(target)
        except BaseException:
            try:target.rmdir()
            except OSError:pass
            raise
    verify(target,title_id)
    managed=snapshots(source_root,title_id,backup_root)
    for old,_ in managed[:-keep]:
        verify(old,title_id)  # recheck before removing an owned, immutable snapshot
        shutil.rmtree(old)
    return {'status':'created','path':str(target),'files':len(expected)}

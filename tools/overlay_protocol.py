# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded local messages for the HTML PC overlay; no network server."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import time


def private_directory(path):
    path=Path(path).absolute()
    info=path.lstat()
    if path.resolve()!=path or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('overlay directory must be private and owned by this user')
    return path


def read_snapshot(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>8*1024*1024:
        raise ValueError('invalid overlay snapshot')
    data=json.loads(path.read_text())
    if data.get('version')!=1 or not isinstance(data.get('visible'),bool):raise ValueError('invalid overlay state')
    geometry=data.get('geometry')
    if not isinstance(geometry,list) or len(geometry)!=4 or any(type(value)is not int for value in geometry):raise ValueError('invalid overlay geometry')
    if not all(-32768<=n<=32768 for n in geometry[:2]) or not all(100<=n<=16384 for n in geometry[2:]):raise ValueError('overlay geometry is outside bounds')
    return data


class Commands:
    def __init__(self,directory):self.directory=private_directory(directory);self.serial=0
    def write(self,text):
        if not isinstance(text,str) or len(text.encode())>8192 or '\0' in text:raise ValueError('invalid overlay command')
        self.serial+=1
        name=f'command-{time.monotonic_ns():020d}-{self.serial:04d}'
        temporary=self.directory/(name+'.tmp');target=self.directory/(name+'.req')
        with temporary.open('x') as file:file.write(text)
        temporary.rename(target)
        return target


class Portraits:
    def __init__(self,root):
        self.directory=Path(root)/'.local/portal-assets';self.cells={};self.cache={}
        try:
            manifest=self.directory/'sources.json'
            if manifest.is_symlink() or manifest.stat().st_size>5*1024*1024:return
            sources=json.loads(manifest.read_text())
            if isinstance(sources,dict):sources=sources.get('sources',[])
            for entry in sources:
                cell=entry.get('cell',entry.get('index',-1));name=entry.get('cache','')
                if type(cell)is int and 0<=cell<2048 and isinstance(name,str) and name==Path(name).name and name not in ('','.','..'):
                    self.cells[cell]=(name,entry.get('sha256'))
        except (OSError,ValueError,TypeError):pass
    def get(self,cell):
        if type(cell)is not int or cell not in self.cells:return ''
        if cell in self.cache:return self.cache[cell]
        name,digest=self.cells[cell];path=self.directory/name
        try:
            if path.is_symlink() or path.resolve().parent!=self.directory.resolve() or path.stat().st_size>4*1024*1024:return ''
            data=path.read_bytes()
            if digest and hashlib.sha256(data).hexdigest()!=digest:return ''
            mime='image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8') else 'image/webp' if data.startswith(b'RIFF') and data[8:12]==b'WEBP' else None
            if not mime:return ''
            result='data:'+mime+';base64,'+base64.b64encode(data).decode();self.cache[cell]=result;return result
        except OSError:return ''

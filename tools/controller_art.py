# SPDX-License-Identifier: GPL-3.0-or-later
"""Read locally imported Steam controller artwork; no Steam runtime dependency.

Artwork remains in the ignored local cache. Only this loader is distributed.
"""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[1]/'.local/controller-glyphs'


def _manifest():
    path=ROOT/'manifest.json'
    if ROOT.is_symlink() or ROOT.resolve()!=ROOT or path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
        raise ValueError('Import local Steam glyphs with tools/import_controller_glyphs.py first')
    record=json.loads(path.read_text())
    if (not isinstance(record,dict) or type(record.get('schema_version')) is not int or record.get('schema_version')!=1 or record.get('provider')!='Steam client' or
            not isinstance(record.get('files'),dict)):
        raise ValueError('invalid controller artwork cache')
    return record


def _read(name,width,height,channels):
    path=ROOT/name;record=_manifest();expected=record['files'].get(name)
    size=8+width*height*channels
    if (path.is_symlink() or path.resolve()!=ROOT.resolve()/name or not path.is_file() or
            path.stat().st_size!=size):raise ValueError('missing or redirected controller artwork')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected or struct.unpack_from('<II',data)!=(width,height):
        raise ValueError('controller artwork failed integrity verification')
    return data[8:]


def glyph(mode,index,width,height):
    if mode not in ('xbox','nintendo') or type(index) is not int or not 0<=index<10:
        raise ValueError('invalid controller art selection')
    return _read(f'{mode}-{index}.rgba',width,height,4)


def letter(mode,index,width,height):
    if mode not in ('xbox','nintendo') or type(index) is not int or index not in (0,1,6):
        raise ValueError('unsupported animated glyph')
    return _read(f'{mode}-{index}.alpha',width,height,1)


def atlas_path():
    _read('menu-atlas.rgba',512,256,4)
    return ROOT/'menu-atlas.rgba'


def available():
    try:atlas_path();return True
    except (OSError,ValueError,TypeError):return False

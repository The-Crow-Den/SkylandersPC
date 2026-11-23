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


# Xbox face buttons are drawn like the Nintendo ones: a dark button, with the
# letter in the button's colour instead of white on a coloured disc.
BUTTON=(14,18,24)


def dark_button(pixels,width,height,box=None):
    """Swap a coloured disc with a white letter for a dark disc with a coloured letter."""
    x0,y0,x1,y1=box or (0,0,width,height);out=bytearray(pixels)
    solid=[tuple(out[i:i+3]) for y in range(y0,y1) for x in range(x0,x1)
           for i in [(y*width+x)*4] if out[i+3]==255 and max(out[i:i+3])-min(out[i:i+3])>80]
    if not solid:return bytes(out)
    colour=tuple(sorted(value[channel] for value in solid)[len(solid)//2] for channel in range(3))
    floor=min(colour)
    for y in range(y0,y1):
        for x in range(x0,x1):
            i=(y*width+x)*4
            if not out[i+3]:continue
            white=max(0.0,min(1.0,(min(out[i:i+3])-floor)/max(1,255-floor)))
            out[i:i+3]=bytes(round(BUTTON[c]*(1-white)+colour[c]*white) for c in range(3))
    return bytes(out)


def glyph(mode,index,width,height):
    if mode not in ('xbox','nintendo') or type(index) is not int or not 0<=index<10:
        raise ValueError('invalid controller art selection')
    pixels=_read(f'{mode}-{index}.rgba',width,height,4)
    return dark_button(pixels,width,height) if mode=='xbox' and index<4 else pixels


def letter(mode,index,width,height):
    if mode not in ('xbox','nintendo') or type(index) is not int or index not in (0,1,6):
        raise ValueError('unsupported animated glyph')
    return _read(f'{mode}-{index}.alpha',width,height,1)


def atlas_path():
    """The menu atlas with the Xbox face buttons (top-left 4 x 64 px cells) restyled."""
    pixels=_read('menu-atlas.rgba',512,256,4)
    for cell in range(4):pixels=dark_button(pixels,512,256,(cell*64,0,cell*64+64,64))
    styled=ROOT/'menu-atlas-styled.rgba';data=struct.pack('<II',512,256)+pixels
    if styled.is_symlink():raise ValueError('redirected controller artwork')
    if not styled.is_file() or styled.read_bytes()!=data:
        temporary=styled.with_name(styled.name+'.tmp');temporary.write_bytes(data);temporary.replace(styled)
    return styled


def available():
    try:atlas_path();return True
    except (OSError,ValueError,TypeError):return False

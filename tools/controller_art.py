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
BUTTON=(14,20,27)  # the Nintendo artwork's button colour


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


def dark_shape(pixels,width,height,box=None):
    """A white button with dark lettering becomes a dark button with white lettering."""
    x0,y0,x1,y1=box or (0,0,width,height);out=bytearray(pixels)
    for y in range(y0,y1):
        for x in range(x0,x1):
            i=(y*width+x)*4
            if not out[i+3]:continue
            white=sum(out[i:i+3])/765
            out[i:i+3]=bytes(round(BUTTON[c]*white+255*(1-white)) for c in range(3))
    return bytes(out)


def on_disc(pixels,width,height,box=None):
    """Light line art (View, Menu) on a dark disc, like the Nintendo - and + buttons."""
    x0,y0,x1,y1=box or (0,0,width,height);out=bytearray(pixels)
    cx,cy=(x0+x1)/2,(y0+y1)/2;radius=min(x1-x0,y1-y0)/2-1
    for y in range(y0,y1):
        for x in range(x0,x1):
            i=(y*width+x)*4;distance=((x+.5-cx)**2+(y+.5-cy)**2)**.5
            cover=max(0.0,min(1.0,radius-distance+.5))
            if not cover:out[i:i+4]=bytes(4);continue
            # shrink the art toward the centre so it sits inside the disc
            sx=round(cx+(x+.5-cx)/.62-.5);sy=round(cy+(y+.5-cy)/.62-.5)
            alpha=0.0;art=bytes(3)
            if x0<=sx<x1 and y0<=sy<y1:
                j=(sy*width+sx)*4;alpha=pixels[j+3]/255;art=pixels[j:j+3]
            out[i:i+3]=bytes(round(BUTTON[c]*(1-alpha)+art[c]*alpha) for c in range(3));out[i+3]=round(255*cover)
    return bytes(out)


def lift_black(pixels,width,height,box=None):
    """Pure black buttons (the Xbox triggers) take the shared button colour."""
    x0,y0,x1,y1=box or (0,0,width,height);out=bytearray(pixels)
    for y in range(y0,y1):
        for x in range(x0,x1):
            i=(y*width+x)*4
            if not out[i+3]:continue
            white=min(out[i:i+3])/255
            out[i:i+3]=bytes(round(BUTTON[c]*(1-white)+255*white) for c in range(3))
    return bytes(out)


def glyph(mode,index,width,height):
    if mode not in ('xbox','nintendo') or type(index) is not int or not 0<=index<10:
        raise ValueError('invalid controller art selection')
    pixels=_read(f'{mode}-{index}.rgba',width,height,4)
    if mode!='xbox':return pixels
    return dark_button(pixels,width,height) if index<4 else dark_shape(pixels,width,height) if index in (4,5) else lift_black(pixels,width,height) if index in (6,7) else pixels


def letter(mode,index,width,height):
    if mode not in ('xbox','nintendo') or type(index) is not int or index not in (0,1,6):
        raise ValueError('unsupported animated glyph')
    return _read(f'{mode}-{index}.alpha',width,height,1)


def _place(pixels,art,size,cell):
    """Area-resample a size x size RGBA image into a 64 x 64 atlas cell (8 x 4 grid)."""
    out=bytearray(pixels);x0,y0=cell%8*64,cell//8*64;scale=size/64
    for y in range(64):
        for x in range(64):
            total=[0.0]*4;count=0
            for sy in range(int(y*scale),max(int(y*scale)+1,int((y+1)*scale))):
                for sx in range(int(x*scale),max(int(x*scale)+1,int((x+1)*scale))):
                    i=(sy*size+sx)*4;a=art[i+3]/255;count+=1
                    for c in range(3):total[c]+=art[i+c]*a
                    total[3]+=a
            j=((y0+y)*512+x0+x)*4;alpha=total[3]/count
            out[j:j+4]=bytes([round(total[c]/total[3]) if total[3] else 0 for c in range(3)]+[round(alpha*255)])
    return bytes(out)


def atlas_path(playstation=None):
    """The menu atlas with the Xbox buttons restyled. playstation: the game's own
    face buttons (84 x 84 RGBA each), used instead of the imported PlayStation art."""
    pixels=_read('menu-atlas.rgba',512,256,4)
    for cell,art in enumerate(playstation or ()):pixels=_place(pixels,art,84,20+cell)
    for cell in range(4):pixels=dark_button(pixels,512,256,(cell*64,0,cell*64+64,64))
    for cell in (6,7):pixels=lift_black(pixels,512,256,(cell*64,0,cell*64+64,64))  # RT, LT
    for cell in (4,5):pixels=dark_shape(pixels,512,256,(cell*64,0,cell*64+64,64))  # LS, RS
    for cell in range(2):pixels=on_disc(pixels,512,256,(cell*64,64,cell*64+64,128))  # View, Menu
    styled=ROOT/'menu-atlas-styled.rgba';data=struct.pack('<II',512,256)+pixels
    if styled.is_symlink():raise ValueError('redirected controller artwork')
    if not styled.is_file() or styled.read_bytes()!=data:
        temporary=styled.with_name(styled.name+'.tmp');temporary.write_bytes(data);temporary.replace(styled)
    return styled


def available():
    try:atlas_path();return True
    except (OSError,ValueError,TypeError):return False

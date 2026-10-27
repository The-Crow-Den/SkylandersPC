#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import Steam's local controller glyphs into a private, verified cache.

Pillow is needed for this one-time preparation only. No downloads or Steam SDK.
The PNGs and derived artwork must not be committed or bundled for redistribution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
try:
    from . import controller_art
except ImportError:
    import controller_art

CELLS=((84,84),(84,84),(84,84),(84,84),(85,84),(85,84),(93,84),(93,84),(121,84),(93,84))
NAMES={
 'xbox':('shared_color_button_a','shared_color_button_x','shared_color_button_b','shared_color_button_y',
         'shared_lstick_click','shared_rstick_click','xbox_rt','xbox_lt','xbox_button_select','xbox_button_start'),
 'nintendo':('shared_button_b','shared_button_y','shared_button_a','shared_button_x',
             'switchpro_lstick_click','switchpro_rstick_click','switchpro_r2','switchpro_l2','switchpro_button_minus','switchpro_button_plus'),
 'playstation':('ps_color_button_x','ps_color_button_circle','ps_color_button_square','ps_color_button_triangle'),
}


def discover():
    home=Path.home()
    for base in (home/'.steam/steam',home/'.local/share/Steam',home/'.var/app/com.valvesoftware.Steam/.local/share/Steam'):
        candidate=base/'controller_base/images/api/dark'
        if candidate.is_dir():return candidate.resolve()
    raise ValueError('Steam controller glyph directory not found; pass --source')


def prepare(source,destination):
    from PIL import Image,ImageOps
    source=Path(source).resolve();destination=Path(destination).absolute()
    if destination.is_symlink() or destination.resolve()!=destination:
        raise ValueError('redirected artwork cache')
    if destination.exists():raise ValueError('destination already exists; use a new cache directory')
    sources=[];files={};art={}
    def load(name,light=False):
        path=(source.parent/'light' if light else source)/(name+'_lg.png')
        if not path.is_file() or path.stat().st_size>4*1024*1024:raise ValueError('missing or oversized Steam glyph: '+name)
        data=path.read_bytes();sources.append(dict(name=path.name,source=str(path),sha256=hashlib.sha256(data).hexdigest()))
        with Image.open(path) as image:
            if image.size!=(256,256):raise ValueError('unexpected Steam glyph dimensions')
            return image.convert('RGBA')
    def fit(image,width,height,padding=3):
        bounds=image.getbbox()
        if bounds is None:raise ValueError('empty Steam glyph')
        fitted=ImageOps.contain(image.crop(bounds),(width-padding*2,height-padding*2),Image.Resampling.LANCZOS)
        canvas=Image.new(image.mode,(width,height),0)
        canvas.paste(fitted,((width-fitted.width)//2,(height-fitted.height)//2))
        return canvas
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.glyph-import-',dir=destination.parent) as temporary:
        staged=Path(temporary)
        def write(name,image):
            data=struct.pack('<II',*image.size)+image.tobytes()
            (staged/name).write_bytes(data);files[name]=hashlib.sha256(data).hexdigest()
        for mode,names in NAMES.items():
            for index,name in enumerate(names):
                image=load(name,light=mode=='xbox' and index in (4,5,8,9));art[mode,index]=image
                if mode=='playstation':continue
                width,height=CELLS[index]
                write(f'{mode}-{index}.rgba',fit(image,width,height,padding=8 if index in (4,5) else 3))
                if index in (0,1,6):
                    # Steam's filled icons use a white letter on a colored or
                    # dark body. Extract its actual antialiased letter shapes.
                    mask=Image.new('L',image.size)
                    mask.putdata([round(a*max(0,min(1,(min(r,g,b)-160)/80))) for r,g,b,a in (image.get_flattened_data() if hasattr(image,'get_flattened_data') else image.getdata())])
                    width,height=(40,28) if index==6 else (48,48)
                    write(f'{mode}-{index}.alpha',fit(mask,width,height,padding=4))
        atlas=Image.new('RGBA',(512,256),(0,0,0,0));slot=0
        for mode in ('xbox','nintendo','playstation'):
            for index in range(len(NAMES[mode])):
                atlas.paste(fit(art[mode,index],64,64,padding=3),(slot%8*64,slot//8*64));slot+=1
        write('menu-atlas.rgba',atlas)
        record=dict(schema_version=1,provider='Steam client',style='contrast-selected dark/light',sources=sources,files=files,
                    note='Local client artwork; not a redistribution grant. No Steam process or SDK required at runtime.')
        (staged/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
        destination.mkdir()
        try:os.replace(staged,destination)
        except BaseException:
            try:destination.rmdir()
            except OSError:pass
            raise
    return dict(provider='Steam client',destination=str(destination),files=len(files),sources=len(sources))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--destination',type=Path,default=controller_art.ROOT)
    args=parser.parse_args()
    try:print(json.dumps(prepare(args.source or discover(),args.destination),indent=2))
    except (OSError,ValueError,ImportError) as error:parser.error(str(error))

if __name__=='__main__':main()

# SPDX-License-Identifier: GPL-2.0-or-later
"""Locally imported Steam glyphs in a verified, private Trap Team font atlas.

GCN addressing follows the pinned GPL-2.0-or-later provider's detile.comp.
Only a session copy is changed. The source archive and text metrics stay intact.
"""
import ctypes
import ctypes.util
import json
import lzma
from pathlib import Path
import struct
try:
    from . import asset_mod, block_texture, controller_art
except ImportError:
    import asset_mod, block_texture, controller_art

MODES=('auto','playstation','xbox','nintendo')
# Texture coordinates, independent of the game's unchanged character codes.
CELLS=(('south',0,0,84,84),('west',87,0,84,84),('east',174,0,84,84),
       ('north',261,0,84,84),('left-stick',668,0,85,84),('right-stick',758,0,85,84),
       ('right-trigger',0,84,93,84),('left-trigger',94,84,93,84),
       ('view',188,84,121,84),('menu',849,0,93,84))
LABELS={
 'xbox':('A','X','B','Y','LS','RS','RT','LT','V','='),
 'nintendo':('B','Y','A','X','L','R','ZR','ZL','-','+'),
}

def detect():
    """Probe SDL's mapped pad type at launch, without creating a window."""
    library=ctypes.util.find_library('SDL3')
    if not library:return 'playstation','SDL3 unavailable'
    try:
        sdl=ctypes.CDLL(library)
        sdl.SDL_Init.argtypes=[ctypes.c_uint32];sdl.SDL_Init.restype=ctypes.c_bool
        sdl.SDL_GetGamepads.argtypes=[ctypes.POINTER(ctypes.c_int)];sdl.SDL_GetGamepads.restype=ctypes.POINTER(ctypes.c_uint32)
        sdl.SDL_GetGamepadTypeForID.argtypes=[ctypes.c_uint32];sdl.SDL_GetGamepadTypeForID.restype=ctypes.c_int
        sdl.SDL_free.argtypes=[ctypes.c_void_p];sdl.SDL_Quit.argtypes=[]
        if not sdl.SDL_Init(0x00002000):return 'playstation','SDL gamepad probe failed'
        try:
            count=ctypes.c_int();ids=sdl.SDL_GetGamepads(ctypes.byref(count))
            try:
                if not ids or not 0<count.value<=64:return 'playstation','no mapped controller'
                kind=sdl.SDL_GetGamepadTypeForID(ids[0])
                # Enum values are checked against the bundled SDL3 header.
                return ('xbox' if kind in (2,3) else 'nintendo' if kind in (7,8,9,10) else 'playstation'),f'SDL pad type {kind}'
            finally:
                sdl.SDL_free(ids)
        finally:
            sdl.SDL_Quit()
    except (OSError,AttributeError) as error:
        return 'playstation',f'SDL probe unavailable: {error}'


def label(mode,index):
    if mode not in LABELS or type(index) is not int or not 0<=index<len(CELLS):
        raise ValueError('invalid controller glyph')
    return LABELS[mode][index]


def raster(mode,index):
    """Use supplied artwork, preserving its aspect ratio and original lettering."""
    label(mode,index)  # validate before opening the private artwork cache
    _,_,_,width,height=CELLS[index]
    return controller_art.glyph(mode,index,width,height)


def tiled_offset(x,y):
    """Verified 1024-pitch 32-bit thin macro layout, bank16/aspect2/P8."""
    tx,ty=x//8,y//8
    pipe=((tx&1)^(ty&1)^(tx>>1&1))|(((tx>>1&1)^(ty>>1&1))<<1)|(((tx>>2&1)^(ty>>2&1))<<2)
    bx,by=x//64,y//8
    bank=((bx&1)^(by>>3&1))|(((bx>>1&1)^(by>>2&1)^(by>>3&1))<<1)|(((bx>>2&1)^(by>>1&1))<<2)|(((bx>>3&1)^(by&1))<<3)
    micro=sum(((x>>i&1)<<(2*i))|((y>>i&1)<<(2*i+1)) for i in range(3))
    offset=((y//64)*8+x//128)*256+micro*4
    return (offset&255)|(pipe<<8)|(bank<<11)|((offset>>8)<<15)


def _read_blocks(source,profile):
    """Decode only hash-verified transport blocks required by the art recipe."""
    if asset_mod.digest(source)!=profile['source_sha256']:
        raise ValueError('controller glyphs refuse an unknown font archive')
    if not 0<len(profile['chunks'])<=256:raise ValueError('invalid controller glyph block count')
    blocks={}
    for row in profile['chunks']:
        at=asset_mod.number(row['offset'],len(source),'glyph source offset')
        size=asset_mod.number(row['decoded_size'],32768,'glyph decoded size')
        allocation=asset_mod.number(row['allocation'],65536,'glyph allocation')
        base=asset_mod.number(row['plain_offset'],512*1024*1024,'glyph decoded offset')
        if not size or not allocation or at+allocation>len(source) or base%32768 or base in blocks:
            raise ValueError('invalid controller glyph block extent')
        block=source[at:at+allocation]
        if row['encoding']=='raw':plain=block[:size]
        elif row['encoding']=='raw-lzma':
            if len(block)<7:raise ValueError('short glyph compression header')
            n=struct.unpack_from('<H',block)[0];props=block[2:7]
            dictionary=struct.unpack_from('<I',props,1)[0]
            if not n or n+7>allocation or not 4096<=dictionary<=32768:
                raise ValueError('invalid glyph compression bounds')
            if n!=row['encoded_size'] or props.hex()!=row['properties_hex'] or props[0]!=0x5d:
                raise ValueError('controller glyph compressed header mismatch')
            decoder=lzma.LZMADecompressor(format=lzma.FORMAT_RAW,filters=[dict(id=lzma.FILTER_LZMA1,dict_size=dictionary,lc=3,lp=0,pb=2)])
            plain=decoder.decompress(block[7:7+n],max_length=size)
        else:raise ValueError('unknown controller glyph block')
        if len(plain)!=size or asset_mod.digest(plain)!=row['decoded_sha256']:
            raise ValueError('controller glyph decoded block mismatch')
        blocks[base]=(row,plain,bytearray(plain))
    return blocks


def _write_blocks(profile,blocks):
    chunks=[]
    for row,plain,modified in blocks.values():
        if plain==modified:continue
        chunks.append({k:v for k,v in row.items() if k!='plain_offset'}|{'edits':[dict(offset=0,expected_hex=plain.hex(),replacement_hex=modified.hex())]})
    return dict(asset=profile['asset'],source_sha256=profile['source_sha256'],chunks=chunks)



def recipe(source,profile,mode):
    """Materialize an expected-byte font recipe, without stored game bytes."""
    if mode not in LABELS:raise ValueError('invalid glyph pack')
    blocks=_read_blocks(source,profile)
    for index,(_,left,top,width,height) in enumerate(CELLS):
        pixels=raster(mode,index)
        for y in range(height):
            for x in range(width):
                absolute=profile['texture_offset']+tiled_offset(left+x,top+y)
                base=absolute//32768*32768
                if base not in blocks:raise ValueError('glyph exceeds verified font blocks')
                _,_,modified=blocks[base];at=absolute-base;src=(y*width+x)*4
                if at+4>len(modified):raise ValueError('glyph pixel exceeds block')
                modified[at:at+4]=pixels[src:src+4]
    return _write_blocks(profile,blocks)


def prompt_recipe(source,profile,mode):
    if mode not in LABELS:raise ValueError('invalid prompt pack')
    blocks=_read_blocks(source,profile)
    if not 0<len(profile['textures'])<=64:raise ValueError('invalid prompt count')
    seen=set()
    for image in profile['textures']:
        start=asset_mod.number(image['texture_offset'],512*1024*1024,'prompt offset');length=image['texture_size']
        if any(start<end and begin<start+16384 for begin,end in seen):raise ValueError('overlapping prompt textures')
        seen.add((start,start+16384))
        if length!=16384:raise ValueError('unsupported prompt texture size')
        raw=bytearray();at=start
        while at<start+length:
            base=at//32768*32768
            if base not in blocks:raise ValueError('prompt exceeds verified blocks')
            _,plain,_=blocks[base];take=min(len(plain)-(at-base),start+length-at)
            if take<=0:raise ValueError('invalid prompt region')
            raw.extend(plain[at-base:at-base+take]);at+=take
        index=image['glyph_index'];label(mode,index)
        mask=controller_art.letter(mode,index,*image['rectangle'][2:])
        result=block_texture.patch_prompt(bytes(raw),mask,image['rectangle'])
        at=start
        while at<start+length:
            base=at//32768*32768;_,_,modified=blocks[base];take=min(len(modified)-(at-base),start+length-at)
            modified[at-base:at-base+take]=result[at-start:at-start+take];at+=take
    return _write_blocks(profile,blocks)


def build_profile(source_root,profile_path,mode,executable_sha256):
    profile=json.loads(Path(profile_path).read_text())
    if profile['executable_sha256']!=executable_sha256:raise ValueError('controller glyphs require the verified executable')
    assets=[]
    for current,transform in [(profile,recipe)]+([(profile['prompts'],prompt_recipe)] if 'prompts' in profile else []):
        relative=Path(current['asset'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('invalid glyph asset path')
        source=Path(source_root)/relative
        if source.is_symlink() or source.resolve()!=source:raise ValueError('redirected glyph source')
        assets.append(transform(source.read_bytes(),current,mode))
    return dict(schema_version=2,executable_sha256=executable_sha256,title_id=profile.get('title_id'),app_version=profile.get('app_version'),recipe_features=['iga-block-alignment'],assets=assets)


def prepare(source_root,game_root,session,profile_path,mode,executable_sha256):
    record=build_profile(source_root,profile_path,mode,executable_sha256)
    result=asset_mod.prepare(source_root,game_root,session,record,enabled=True)
    return dict(mode=mode,coverage='shared font and animated mash prompts',**result)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Small BC1-color/BC3 helpers for bounded, offline prompt-art editing.

Format layout: Microsoft Learn, Block compression. No runtime image library.
Only RGB halves of selected BC3 blocks are re-encoded; alpha is copied exactly.
"""
import struct


def _rgb(word):
    r,g,b=word>>11,(word>>5)&63,word&31
    return (r<<3|r>>2,g<<2|g>>4,b<<3|b>>2)


def _palette(a,b,opaque=True):
    first,second=_rgb(a),_rgb(b)
    if opaque or a>b:
        return (first,second,tuple((2*x+y)//3 for x,y in zip(first,second)),tuple((x+2*y)//3 for x,y in zip(first,second)))
    return (first,second,tuple((x+y)//2 for x,y in zip(first,second)),(0,0,0))


def decode_color(block,opaque=True):
    if len(block)!=8:raise ValueError('BC color block must be eight bytes')
    a,b,indices=struct.unpack('<HHI',block);palette=_palette(a,b,opaque)
    return [palette[indices>>(i*2)&3] for i in range(16)]


def encode_color(pixels):
    if len(pixels)!=16 or any(len(p)!=3 or any(type(v) is not int or not 0<=v<=255 for v in p) for p in pixels):
        raise ValueError('BC color encoder requires sixteen RGB pixels')
    colors=list(dict.fromkeys(map(tuple,pixels)))
    # Farthest pair is adequate for tiny letter/background blocks. This encoder
    # is deliberately limited to offline UI modifications, not game textures.
    a,b=max(((a,b) for a in colors for b in colors),key=lambda pair:sum((x-y)**2 for x,y in zip(*pair)))
    quantize=lambda p:((p[0]*31+127)//255<<11)|((p[1]*63+127)//255<<5)|((p[2]*31+127)//255)
    first,second=sorted((quantize(a),quantize(b)),reverse=True)
    palette=_palette(first,second)
    indices=sum(min(range(4),key=lambda j:sum((v-palette[j][c])**2 for c,v in enumerate(p)))<<(i*2) for i,p in enumerate(pixels))
    return struct.pack('<HHI',first,second,indices)


def block_offset(x,y):
    """128x128 BC3 texture: 32x32 blocks in 8x8 thin microtiles."""
    if type(x) is not int or type(y) is not int or not 0<=x<32 or not 0<=y<32:
        raise ValueError('BC prompt block outside verified dimensions')
    micro=sum(((x>>i&1)<<(2*i))|((y>>i&1)<<(2*i+1)) for i in range(3))
    return (((y//8)*4+x//8)*64+micro)*16


def patch_prompt(raw,mask,rectangle,color=(255,255,255)):
    """Replace a letter region, retaining every encoded alpha/glow block.

    The source sprite is vertically flipped relative to the displayed prompt;
    imported letter masks are flipped correspondingly. Background shading is
    interpolated from the unchanged pixels immediately beside each row.
    """
    if len(raw)!=16384 or len(rectangle)!=4 or any(type(v) is not int for v in rectangle):
        raise ValueError('unsupported BC3 prompt layout')
    left,top,width,height=rectangle
    if not isinstance(mask,bytes) or len(mask)!=width*height or len(color)!=3:
        raise ValueError('invalid prompt letter mask')
    if (not all(v%4==0 for v in rectangle) or width<8 or height<8 or left<4 or top<4 or left+width>=128 or top+height>=128):
        raise ValueError('prompt edit must be interior and BC block aligned')
    blocks={}
    def pixel(x,y):
        bx,by=x//4,y//4;key=bx,by
        if key not in blocks:
            at=block_offset(bx,by);blocks[key]=decode_color(raw[at+8:at+16])
        return blocks[key][(y%4)*4+x%4]
    backgrounds=[(pixel(left-1,y),pixel(left+width,y)) for y in range(top,top+height)]
    verticals=[(pixel(x,top-1),pixel(x,top+height)) for x in range(left,left+width)]
    corners=(pixel(left-1,top-1),pixel(left+width,top-1),pixel(left-1,top+height),pixel(left+width,top+height))
    changed={}
    for y in range(top,top+height):
        before,after=backgrounds[y-top]
        for x in range(left,left+width):
            key=x//4,y//4
            if key not in changed:changed[key]=list(blocks.get(key) or [pixel(key[0]*4+i%4,key[1]*4+i//4) for i in range(16)])
            t=(x-left+.5)/width;v=(y-top+.5)/height
            upper,lower=verticals[x-left]
            background=[]
            for c in range(3):
                bilinear=(corners[0][c]*(1-t)+corners[1][c]*t)*(1-v)+(corners[2][c]*(1-t)+corners[3][c]*t)*v
                background.append(max(0,min(255,before[c]*(1-t)+after[c]*t+upper[c]*(1-v)+lower[c]*v-bilinear)))
            feather=min(1,min(x-left+.5,left+width-x-.5,y-top+.5,top+height-y-.5)/4)
            old=pixel(x,y);background=[a*(1-feather)+b*feather for a,b in zip(old,background)]
            ink=mask[(height-1-(y-top))*width+x-left]/255
            changed[key][y%4*4+x%4]=tuple(min(255,round((b*(1-ink)+c*ink)/16)*16) for b,c in zip(background,color))
    out=bytearray(raw)
    for (x,y),pixels in changed.items():
        at=block_offset(x,y);out[at+8:at+16]=encode_color(pixels)
    return bytes(out)


def micro_tiled_offset(x,y,blocks_per_row):
    """BC block (x,y) of a 1D thin micro tiled texture: 8x8-block tiles, row major."""
    micro=sum(((x>>i&1)<<(2*i))|((y>>i&1)<<(2*i+1)) for i in range(3))
    return (((y//8)*(blocks_per_row//8)+x//8)*64+micro)*16


def encode_alpha(values):
    """BC3 alpha block: endpoints max/min with six interpolated levels."""
    if len(values)!=16 or any(type(v) is not int or not 0<=v<=255 for v in values):
        raise ValueError('BC alpha encoder requires sixteen values')
    high,low=max(values),min(values)
    if high==low:return bytes((high,low))+bytes(6)
    palette=[high,low]+[((7-i)*high+i*low)//7 for i in range(1,7)]
    indices=sum(min(range(8),key=lambda j:abs(v-palette[j]))<<(3*i) for i,v in enumerate(values))
    return bytes((high,low))+indices.to_bytes(6,'little')


def encode_bc3(pixels):
    """Sixteen RGBA pixels to one BC3 block (alpha, then opaque-mode colour)."""
    if len(pixels)!=16:raise ValueError('BC3 encoder requires sixteen pixels')
    return encode_alpha([p[3] for p in pixels])+encode_color([tuple(p[:3]) for p in pixels])

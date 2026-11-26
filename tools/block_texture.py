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


def decode_alpha(block):
    if len(block)!=8:raise ValueError('BC alpha block must be eight bytes')
    a0,a1=block[0],block[1];bits=int.from_bytes(block[2:8],'little')
    if a0>a1:palette=[a0,a1]+[((7-i)*a0+i*a1)//7 for i in range(1,7)]
    else:palette=[a0,a1]+[((5-i)*a0+i*a1)//5 for i in range(1,5)]+[0,255]
    return [palette[bits>>(3*i)&7] for i in range(16)]


def decode_prompt(raw):
    """A 128x128 BC3 prompt as display-oriented RGBA rows (the stored sprite is flipped)."""
    if len(raw)!=16384:raise ValueError('unsupported BC3 prompt layout')
    image=[[(0,0,0,0)]*128 for _ in range(128)]
    for by in range(32):
        for bx in range(32):
            at=block_offset(bx,by);alpha=decode_alpha(raw[at:at+8]);color=decode_color(raw[at+8:at+16])
            for i in range(16):image[127-(by*4+i//4)][bx*4+i%4]=(*color[i],alpha[i])
    return image


def encode_prompt(image):
    """Inverse of decode_prompt: display-oriented RGBA rows to the stored BC3 layout."""
    if len(image)!=128 or any(len(row)!=128 for row in image):raise ValueError('prompt image must be 128x128')
    out=bytearray(16384)
    for by in range(32):
        for bx in range(32):
            pixels=[tuple(image[127-(by*4+i//4)][bx*4+i%4]) for i in range(16)]
            at=block_offset(bx,by);out[at:at+16]=encode_bc3(pixels)
    return bytes(out)


# The HUD swap button: 52x52 RGBA8 in a 64-pixel 2D-tiled surface (0x8000 bytes).
# Its 8x8 micro tiles sit in 16-tile rows; rows are bit-reversed and columns
# swizzled. Worked out from the game's own button, every opaque tile accounted for.
SWAP_SIZE,SWAP_WIDTH=0x8000,52


def swap_offset(x,y):
    tx,ty=x//8,y//8
    row=(ty&1)<<2|(ty&2)|(ty>>2&1)
    column=(tx^(tx>>1&1))^ty
    return (row*16+column)*256+(sum(((x>>i&1)<<(2*i))|((y>>i&1)<<(2*i+1)) for i in range(3)))*4


def decode_swap(raw):
    """The swap button as a display-oriented 128x128 RGBA canvas (button at the top left)."""
    if len(raw)!=SWAP_SIZE:raise ValueError('unsupported swap button layout')
    image=[[(0,0,0,0)]*128 for _ in range(128)]
    for y in range(SWAP_WIDTH):
        for x in range(SWAP_WIDTH):
            at=swap_offset(x,y);image[SWAP_WIDTH-1-y][x]=tuple(raw[at:at+4])
    return image


def encode_swap(image,raw):
    """Write the canvas's button back over the original bytes; padding is kept."""
    out=bytearray(raw)
    for y in range(SWAP_WIDTH):
        for x in range(SWAP_WIDTH):
            at=swap_offset(x,y);out[at:at+4]=bytes(image[SWAP_WIDTH-1-y][x])
    return bytes(out)


def opaque_bounds(image,threshold=128):
    """Smallest (left, top, right, bottom) box around pixels at least this opaque, or None."""
    xs=[x for row in image for x,p in enumerate(row) if p[3]>=threshold]
    ys=[y for y,row in enumerate(image) if any(p[3]>=threshold for p in row)]
    return (min(xs),min(ys),max(xs)+1,max(ys)+1) if xs else None


def luminance(image,threshold=128):
    values=[0.299*p[0]+0.587*p[1]+0.114*p[2] for row in image for p in row if p[3]>=threshold]
    return sum(values)/len(values) if values else 0.0


def replace_prompt(image,art,width,height,brightness=1.0,margin=2,rim=0.0):
    """Draw controller art over a prompt frame's button, fitted to its opaque box.

    The whole button is replaced (not only its symbol); the frame's box keeps the
    game's press/mash scaling, and brightness keeps its darker pressed frames.
    Pixels well outside the button (glow, rings) are kept. rim (0..1) draws a
    light ring around the art, like the game's white button rim; its strength
    follows the original frame so the mash animation still pulses."""
    box=opaque_bounds(image)
    if box is None:return [list(row) for row in image]
    left,top,right,bottom=box;bw,bh=right-left,bottom-top
    # A rim takes the outer ring of the box, as the game's own white rim does.
    rim_width=max(2,round(min(bw,bh)*.07)) if rim>0 else 0
    left,top,right,bottom=left+rim_width,top+rim_width,right-rim_width,bottom-rim_width;bw,bh=right-left,bottom-top
    scale=min(bw/width,bh/height);dw,dh=max(1,round(width*scale)),max(1,round(height*scale))
    ox,oy=left+(bw-dw)//2,top+(bh-dh)//2
    out=[list(row) for row in image]
    clear=margin+rim_width
    for y in range(max(0,top-clear),min(128,bottom+clear)):
        for x in range(max(0,left-clear),min(128,right+clear)):out[y][x]=(0,0,0,0)
    for y in range(dh):
        for x in range(dw):
            # Area-average the art onto the target pixel.
            x0,x1=x/scale,(x+1)/scale;y0,y1=y/scale,(y+1)/scale;total=[0.0]*4;weight=0.0
            for sy in range(int(y0),min(height,int(y1-1e-9)+1)):
                wy=min(sy+1,y1)-max(sy,y0)
                for sx in range(int(x0),min(width,int(x1-1e-9)+1)):
                    w=wy*(min(sx+1,x1)-max(sx,x0));i=(sy*width+sx)*4;a=art[i+3]*w
                    total[0]+=art[i]*a;total[1]+=art[i+1]*a;total[2]+=art[i+2]*a;total[3]+=a;weight+=w
            if not total[3]:continue
            rgb=tuple(max(0,min(255,round(total[c]/total[3]*brightness))) for c in range(3))
            tx,ty=ox+x,oy+y
            if 0<=tx<128 and 0<=ty<128:out[ty][tx]=(*rgb,max(0,min(255,round(total[3]/weight))))
    if rim>0:
        solid={(x,y) for y in range(max(0,oy),min(128,oy+dh)) for x in range(max(0,ox),min(128,ox+dw)) if out[y][x][3]>=128}
        alpha=max(0,min(255,round(255*rim)))
        for y in range(max(0,oy-rim_width),min(128,oy+dh+rim_width)):
            for x in range(max(0,ox-rim_width),min(128,ox+dw+rim_width)):
                if (x,y) in solid:continue
                if any((x+dx,y+dy) in solid for dy in range(-rim_width,rim_width+1) for dx in range(-rim_width,rim_width+1) if dx*dx+dy*dy<=rim_width*rim_width):
                    out[y][x]=(255,255,255,alpha)
    return out

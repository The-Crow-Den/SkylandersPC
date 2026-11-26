# SPDX-License-Identifier: GPL-3.0-or-later
"""Portal portraits read from the player's own game: its collection pictures.

Trap Team keeps a 192x192 picture of every toy and trap in two archives, named
'<figure id>_<variant>_<name>.png'. Nothing is downloaded or shipped: the
pictures are decoded from the installed game into a private cache.

Archive layout (Trap Team PS4, IGA version 0x0B): member count at 0x0C, chunk
alignment at 0x10, name table offset at 0x28, then 4-byte checksums and
16-byte local headers (offset, -, size, mode). Mode 0x20xxxxxx members are
0x8000-byte raw LZMA chunks with a 2-byte size and 5-byte properties.
Textures are BC3 in 1D thin micro tiles (8x8 blocks), stored at the file end.
"""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import zlib
try:
    from .block_texture import decode_color, micro_tiled_offset
except ImportError:
    from block_texture import decode_color, micro_tiled_offset

ARCHIVES = ('misc/ui_collection_champions.arc', 'misc/ui_collection_traps.arc')
NAME = re.compile(r'/(\d{1,5})_(\d{1,5})(?:_[a-z0-9_]*)?\.png/[^/]*\.tex\.igz$')
SIZE = 96
# Bump when the decoded pictures change, so older caches are rebuilt.
SCHEMA = 2


def members(data):
    if data[:4] != b'IGA\x1a' or len(data) < 0x38:raise ValueError('not a game archive')
    count, align = struct.unpack_from('<II', data, 0x0C)
    table = struct.unpack_from('<Q', data, 0x28)[0]
    if not 0 < count <= 4096 or align not in (0x800, 0x1000) or table + 4 * count > len(data):
        raise ValueError('unexpected archive header')
    base = 0x38 + 4 * count
    for i in range(count):
        start = table + struct.unpack_from('<I', data, table + 4 * i)[0]
        end = data.index(b'\0', start)
        offset, _, size, mode = struct.unpack_from('<IIII', data, base + 16 * i)
        if offset >= len(data) or size > 1 << 22:raise ValueError('unexpected archive member')
        yield data[start:end].decode('latin-1'), offset, size, mode, align


def extract(data, offset, size, mode, align):
    if mode == 0xFFFFFFFF:return data[offset:offset + size]
    if mode >> 24 != 0x20:raise ValueError('unsupported archive compression')
    out = bytearray(); at = offset
    while len(out) < size:
        length = struct.unpack_from('<H', data, at)[0]; props = data[at + 2:at + 7]
        want = min(0x8000, size - len(out))
        if props[0] == 0x5D:
            dictionary = struct.unpack_from('<I', props, 1)[0]
            decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
                dict(id=lzma.FILTER_LZMA1, dict_size=dictionary, lc=3, lp=0, pb=2)])
            out += decoder.decompress(data[at + 7:at + 7 + length], max_length=want); at += 7 + length
        else:
            out += data[at:at + want]; at += 0x8000
        at = (at + align - 1) // align * align
    return bytes(out)


def alpha(block):
    a0, a1 = block[0], block[1]; bits = int.from_bytes(block[2:8], 'little')
    if a0 > a1:palette = [a0, a1] + [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
    else:palette = [a0, a1] + [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255]
    return [palette[bits >> (3 * i) & 7] for i in range(16)]


def picture(texture):
    """RGBA rows at half size (2x2 average) from a 192x192 BC3 collection texture.
    The game stores them bottom row first."""
    sections = struct.unpack_from('<I', texture, 0x28)[0]
    width, height = struct.unpack_from('<HH', texture, sections + 0x110)
    if (width, height) != (192, 192) or len(texture) < width * height:raise ValueError('unexpected portrait texture')
    pixels = texture[-width * height:]; blocks = width // 4
    full = [[None] * width for _ in range(height)]
    for by in range(height // 4):
        for bx in range(blocks):
            at = micro_tiled_offset(bx, by, blocks); block = pixels[at:at + 16]
            alphas = alpha(block[:8]); colours = decode_color(block[8:])
            for i in range(16):full[by * 4 + i // 4][bx * 4 + i % 4] = (*colours[i], alphas[i])
    rows = []
    for y in range(0, height, 2):
        row = bytearray()
        for x in range(0, width, 2):
            quad = (full[y][x], full[y][x + 1], full[y + 1][x], full[y + 1][x + 1])
            row += bytes(sum(p[c] for p in quad) // 4 for c in range(4))
        rows.append(bytes(row))
    return rows[::-1]


def png(rows):
    width = len(rows[0]) // 4
    def chunk(kind, body):return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    raw = b''.join(b'\0' + row for row in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, len(rows), 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def find(games, relative):
    """The update's copy wins over the base game's."""
    for game in games:
        path = Path(game) / relative
        if path.is_file() and not path.is_symlink():return path
    raise ValueError('The installed game has no ' + relative)


def prepare(destination, games):
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    index = {}
    try:current = json.loads((destination / 'index.json').read_text(encoding='utf-8')).get('schema_version') == SCHEMA
    except (OSError, ValueError, AttributeError):current = False
    for relative in ARCHIVES:
        data = find(games, relative).read_bytes()
        for name, offset, size, mode, align in members(data):
            match = NAME.search(name)
            if not match:continue
            key = f'{int(match[1])}:{int(match[2])}'; filename = key.replace(':', '_') + '.png'
            target = destination / filename
            if target.is_symlink():raise ValueError('redirected portrait cache')
            if not current or not target.is_file():
                target.write_bytes(png(picture(extract(data, offset, size, mode, align))))
            index[key] = filename
    if not index:raise ValueError('No portraits were found in the installed game')
    (destination / 'index.json').write_text(json.dumps(dict(schema_version=SCHEMA, portraits=index), indent=1, sort_keys=True) + '\n', encoding='utf-8')
    if destination.name == 'game':install(destination.parent)  # .local/portal-assets/game
    return index


def unpng(data):
    """RGBA rows of a PNG written by png() above (filter 0, 8-bit RGBA)."""
    width, height = struct.unpack('>II', data[16:24])
    raw = zlib.decompress(data[data.index(b'IDAT') + 4:data.rindex(b'IEND') - 8])
    stride = width * 4 + 1
    if data[24:26] != b'\x08\x06' or len(raw) != stride * height or any(raw[y * stride] for y in range(height)):
        raise ValueError('unexpected portrait picture')
    return width, [raw[y * stride + 1:(y + 1) * stride] for y in range(height)]


def write(path, content):
    temporary = path.with_name(path.name + '.tmp')
    if isinstance(content, bytes):temporary.write_bytes(content)
    else:temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)


COLUMNS = 16
# Cells below this stay for villains and trap elements (the runtime maps
# villains to fixed cells), even without the optional downloaded pictures.
RESERVED = 64


def install(assets):
    """Put the game's pictures in the in-game portal's atlas and index
    (.local/portal-assets/portraits.rgba, portrait-index.txt, sources.json),
    keeping the villain and element cells already there. Safe to repeat."""
    assets = Path(assets); game = assets / 'game'
    index_data = (game / 'index.json').read_bytes()
    index = json.loads(index_data)['portraits']
    try:record = json.loads((assets / 'sources.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):record = {}
    if not isinstance(record, dict):record = {}
    try:atlas = (assets / 'portraits.rgba').read_bytes()
    except OSError:atlas = b''
    digest = hashlib.sha256(index_data).hexdigest()
    if record.get('game_index_sha256') == digest and atlas and record.get('atlas_sha256') == hashlib.sha256(atlas).hexdigest():
        return False
    stride = COLUMNS * SIZE * 4
    kept = []
    if len(atlas) >= 8:
        width, height = struct.unpack_from('<II', atlas)
        if width * 4 == stride and len(atlas) == 8 + width * height * 4:
            kept = [s for s in record.get('sources', []) if isinstance(s, dict) and s.get('kind') in ('villain', 'element')
                    and type(s.get('cell')) is int and 0 <= s['cell'] < height // SIZE * COLUMNS]
    # Villain cells are fixed; trap element icons move up behind them (element-index.txt follows).
    moved = {}; free = max([-1] + [e['cell'] for e in kept if e['kind'] == 'villain']) + 1
    for entry in sorted((e for e in kept if e['kind'] == 'element'), key=lambda e: e['cell']):
        moved[entry['cell']] = free; free += 1
    first = max(RESERVED, free)
    keys = sorted(index, key=lambda key: tuple(map(int, key.split(':'))))
    rows = -(-(first + len(keys)) // COLUMNS)
    if rows > 64:raise ValueError('Too many portraits for the portal atlas')
    pixels = bytearray(stride * rows * SIZE)
    def place(cell, lines):
        x = cell % COLUMNS * SIZE * 4; y = cell // COLUMNS * SIZE
        for row in range(SIZE):pixels[(y + row) * stride + x:(y + row) * stride + x + SIZE * 4] = lines[row]
    def place_old(cell, old):
        x = cell % COLUMNS * SIZE * 4; y = cell // COLUMNS * SIZE; ox = old % COLUMNS * SIZE * 4; oy = old // COLUMNS * SIZE
        for row in range(SIZE):
            at = 8 + (oy + row) * stride + ox
            pixels[(y + row) * stride + x:(y + row) * stride + x + SIZE * 4] = atlas[at:at + SIZE * 4]
    sources = []
    for entry in kept:
        cell = moved.get(entry['cell'], entry['cell']); place_old(cell, entry['cell']); sources.append(dict(entry, cell=cell))
    mapping = {}
    for cell, key in enumerate(keys, first):
        data = (game / index[key]).read_bytes()
        width, lines = unpng(data)
        if width != SIZE or len(lines) != SIZE:raise ValueError('unexpected portrait size')
        place(cell, lines); mapping[tuple(map(int, key.split(':')))] = cell
        sources.append(dict(cell=cell, kind='figure', cache='game/' + index[key], sha256=hashlib.sha256(data).hexdigest()))
    # A swapper's bottom half (1xxx) shows its top half (2xxx) when the game has no picture of its own.
    for (identity, variant), cell in list(mapping.items()):
        if 2000 <= identity < 3000 and not any(i == identity - 1000 for i, _ in mapping):
            mapping.setdefault((identity - 1000, variant), cell)
    content = struct.pack('<II', COLUMNS * SIZE, rows * SIZE) + bytes(pixels)
    if moved:
        try:lines = (assets / 'element-index.txt').read_text(encoding='utf-8').split()
        except OSError:lines = []
        pairs = [(int(lines[i]), int(lines[i + 1])) for i in range(0, len(lines) - 1, 2)]
        write(assets / 'element-index.txt', ''.join(f'{e} {moved.get(c, c)}\n' for e, c in pairs))
    write(assets / 'portraits.rgba', content)
    write(assets / 'portrait-index.txt', '\n'.join([f'SKYPORTRAITS1 {COLUMNS} {rows}'] +
          [f'{i} {v} {c}' for (i, v), c in sorted(mapping.items())]) + '\n')
    record.update(schema_version=2, atlas_sha256=hashlib.sha256(content).hexdigest(), dimensions=[COLUMNS * SIZE, rows * SIZE],
                  columns=COLUMNS, rows=rows, figure_portraits=len(keys), game_index_sha256=digest, sources=sources)
    write(assets / 'sources.json', json.dumps(record, indent=2) + '\n')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('game', type=Path, nargs='+', help='update folder first, then the base game folder')
    args = parser.parse_args()
    print(len(prepare(args.destination, args.game)), 'portraits')


if __name__ == '__main__':
    main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and edit Skylander figure progress (nickname, experience, gold).

Interpretation matches native/trap_metadata.hpp. Per-block keys are derived in
memory; the format seed stays in the user's private asset cache. Edits are made
in place in the active save area, so every other byte of the tag is preserved.
"""
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SIZE = 1024
AREAS = (0x08, 0x24)            # first block of each save area
# Total experience required for each level; 10 / 15 / 20 are the three game caps.
LEVEL_XP = (0, 1000, 2200, 3800, 6000, 9000, 13000, 18200, 24800, 33000,
            42700, 53900, 66600, 80800, 96500, 113700, 132400, 152600, 174300, 197500)
XP_CAPS = (33000, 63500, 101000)
MAX_XP = sum(XP_CAPS)
MAX_GOLD = 65000
NICKNAME_LENGTH = 15


class FigureError(ValueError):
    pass


def crc16(data, value=0xffff):
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x1021 if value & 0x8000 else 0)) & 0xffff
    return value


def load_seed(root):
    path = Path(root) / '.local/portal-assets/trap-metadata.seed'
    try:
        seed = path.read_bytes()
    except OSError:
        raise FigureError('Figure editing needs the private portal seed in .local/portal-assets.') from None
    if not seed or len(seed) > 256:
        raise FigureError('The private portal seed is invalid.')
    return seed


def kind(identity):
    if 210 <= identity <= 220:
        return 'trap'
    if 200 <= identity <= 209 or 230 <= identity <= 233 or 300 <= identity <= 308:
        return 'item'
    return 'character'


def level_for(xp):
    return max(i + 1 for i, need in enumerate(LEVEL_XP) if xp >= need)


def xp_for(level):
    if not 1 <= level <= len(LEVEL_XP):
        raise FigureError('Level must be between 1 and 20.')
    return LEVEL_XP[level - 1]


def blank(identity, variant, random=os.urandom):
    """A new, never-played tag: random UID, identity block and open sector trailers."""
    if not 0 <= identity <= 0xffff or not 0 <= variant <= 0xffff:
        raise FigureError('Invalid figure identity.')
    data = bytearray(SIZE)
    data[0:4] = random(4)
    data[4] = data[0] ^ data[1] ^ data[2] ^ data[3]
    data[5:8] = b'\x81\x01\x0f'
    data[0x10:0x12] = identity.to_bytes(2, 'little')
    data[0x1c:0x1e] = variant.to_bytes(2, 'little')
    data[0x1e:0x20] = crc16(data[:0x1e]).to_bytes(2, 'little')
    for sector in range(16):
        data[sector * 0x40 + 0x36:sector * 0x40 + 0x3a] = (b'\x0f\x0f\x0f\x69' if sector == 0 else b'\x7f\x0f\x08\x69')
    return bytes(data)


class Figure:
    def __init__(self, raw, seed):
        if len(raw) != SIZE:
            raise FigureError('A figure dump must be exactly 1024 bytes.')
        self.raw = bytes(raw)
        self.seed = seed
        if crc16(self.raw[:0x1e]) != int.from_bytes(self.raw[0x1e:0x20], 'little'):
            raise FigureError('The figure identity block is damaged.')
        self.plain = bytearray(self.raw)
        for block in range(8, 64):
            if block % 4 != 3 and any(self._raw_block(block)):
                self.plain[block * 16:block * 16 + 16] = self._cipher(block).decryptor().update(self._raw_block(block))
        self.changed = set()
        self.header = self._active(lambda area: self._header_valid(area), lambda area: self.plain[area * 16 + 9])
        self.extended = self._active(lambda area: self._extended_valid(area), lambda area: self.plain[(area + 9) * 16 + 2])

    identity = property(lambda self: int.from_bytes(self.raw[0x10:0x12], 'little'))
    variant = property(lambda self: int.from_bytes(self.raw[0x1c:0x1e], 'little'))
    kind = property(lambda self: kind(self.identity))
    editable = property(lambda self: self.kind == 'character' and self.header is not None)

    def _raw_block(self, block):
        return self.raw[block * 16:block * 16 + 16]

    def _cipher(self, block, raw=None):
        key = hashlib.md5((raw or self.raw)[:32] + bytes([block]) + self.seed).digest()
        return Cipher(algorithms.AES(key), modes.ECB())

    def _block(self, area, offset):
        start = (area + offset) * 16
        return bytes(self.plain[start:start + 16])

    def _header_valid(self, area):
        header = self._block(area, 0)
        return any(self._raw_block(area)) and crc16(header[:14] + b'\x05\x00') == int.from_bytes(header[14:16], 'little')

    def _extended_valid(self, area):
        block = self._block(area, 9)
        return (any(self._raw_block(area + 9)) and
                crc16(b'\x06\x01' + block[2:] + self._block(area, 10) + self._block(area, 12) + self._block(area, 13))
                == int.from_bytes(block[:2], 'little'))

    @staticmethod
    def _active(valid, sequence):
        first, second = (valid(area) for area in AREAS)
        if second and (not first or (sequence(AREAS[0]) + 1) & 0xff == sequence(AREAS[1])):
            return AREAS[1]
        return AREAS[0] if first else None

    def _read(self, area, block, offset, size):
        start = (area + block) * 16 + offset
        return int.from_bytes(self.plain[start:start + size], 'little')

    def _write(self, area, block, offset, data):
        start = (area + block) * 16 + offset
        self.plain[start:start + len(data)] = data
        self.changed.add(area + block)

    def _require(self):
        if not self.editable:
            raise FigureError('Place this Skylander in game once before editing its progress.')

    @property
    def nickname(self):
        if self.header is None:
            return ''
        text = (self._block(self.header, 2) + self._block(self.header, 4)).decode('utf-16le', 'replace')
        return text.split('\0', 1)[0]

    @nickname.setter
    def nickname(self, text):
        self._require()
        if len(text) > NICKNAME_LENGTH or '\0' in text or any(ord(c) > 0xffff for c in text):
            raise FigureError(f'Nicknames can have up to {NICKNAME_LENGTH} characters.')
        data = text.encode('utf-16le').ljust(32, b'\0')
        self._write(self.header, 2, 0, data[:16])
        self._write(self.header, 4, 0, data[16:])

    @property
    def gold(self):
        return self._read(self.header, 0, 3, 2) if self.header is not None else 0

    @gold.setter
    def gold(self, value):
        self._require()
        if not 0 <= value <= MAX_GOLD:
            raise FigureError(f'Gold must be between 0 and {MAX_GOLD}.')
        self._write(self.header, 0, 3, value.to_bytes(2, 'little'))

    @property
    def max_xp(self):
        return MAX_XP if self.extended is not None else XP_CAPS[0]

    @property
    def xp(self):
        if self.header is None:
            return 0
        total = self._read(self.header, 0, 0, 3)
        if self.extended is not None:
            total += self._read(self.extended, 9, 3, 2) + self._read(self.extended, 9, 8, 3)
        return total

    @xp.setter
    def xp(self, value):
        self._require()
        if not 0 <= value <= self.max_xp:
            raise FigureError(f'Experience must be between 0 and {self.max_xp}.')
        first = min(value, XP_CAPS[0])
        self._write(self.header, 0, 0, first.to_bytes(3, 'little'))
        if self.extended is not None:
            second = min(value - first, XP_CAPS[1])
            self._write(self.extended, 9, 3, second.to_bytes(2, 'little'))
            self._write(self.extended, 9, 8, (value - first - second).to_bytes(3, 'little'))

    @property
    def level(self):
        return level_for(self.xp)

    @level.setter
    def level(self, value):
        self.xp = xp_for(value)

    @property
    def max_level(self):
        return level_for(self.max_xp)

    @property
    def seconds_played(self):
        return self._read(self.header, 0, 5, 4) if self.header is not None else 0

    def to_bytes(self):
        """Re-checksum and re-encrypt only the blocks an edit touched."""
        if self.header is not None and {self.header + 2, self.header + 4} & self.changed:
            self._write(self.header, 0, 12, crc16(self._block(self.header, 1) + self._block(self.header, 2) +
                                                  self._block(self.header, 4)).to_bytes(2, 'little'))
        if self.header is not None and self.header in self.changed:
            self._write(self.header, 0, 14, crc16(self._block(self.header, 0)[:14] + b'\x05\x00').to_bytes(2, 'little'))
        if self.extended is not None and self.extended + 9 in self.changed:
            area = self.extended
            self._write(area, 9, 0, crc16(b'\x06\x01' + self._block(area, 9)[2:] + self._block(area, 10) +
                                          self._block(area, 12) + self._block(area, 13)).to_bytes(2, 'little'))
        raw = bytearray(self.raw)
        for block in self.changed:
            raw[block * 16:block * 16 + 16] = self._cipher(block).encryptor().update(bytes(self.plain[block * 16:block * 16 + 16]))
        return bytes(raw)


def rekey(raw, seed, random=os.urandom):
    """Copy a figure's progress onto a new UID, so both copies can share a portal."""
    figure = Figure(raw, seed)
    fresh = bytearray(figure.raw)
    fresh[0:4] = random(4)
    fresh[4] = fresh[0] ^ fresh[1] ^ fresh[2] ^ fresh[3]
    fresh[0x1e:0x20] = crc16(fresh[:0x1e]).to_bytes(2, 'little')
    for block in range(8, 64):
        start = block * 16
        if block % 4 != 3 and any(figure._raw_block(block)):
            fresh[start:start + 16] = figure._cipher(block, bytes(fresh)).encryptor().update(bytes(figure.plain[start:start + 16]))
    return bytes(fresh)

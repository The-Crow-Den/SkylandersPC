# SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
# SPDX-License-Identifier: GPL-2.0-or-later
"""Streaming fake-PKG/PFSC extraction, adapted from shadPS4 (see LICENSES/pkg-source.json).

Key material stays in ignored .local/. No retail-package decryption is supported.
"""
import argparse
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import urllib.request
import zlib

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[1]
BLOCK = 0x10000
SECTOR = 0x1000


def load_keys():
    """Fetch only the pinned, hash-verified reference; never export parsed keys."""
    provenance = json.loads((ROOT / 'LICENSES/pkg-source.json').read_text())
    source = provenance['keys']
    path = ROOT / '.local/shadps4-pkg-reference' / source['path']
    if path.exists():
        data = path.read_bytes()
    else:
        print('Downloading pinned PKG key reference…', flush=True)
        with urllib.request.urlopen(source['url'], timeout=30) as response:
            data = response.read(1024 * 1024)
    if hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('PKG key reference hash mismatch; refusing to use it')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    return parse_keys(data.decode('utf-8'))


def parse_keys(source):
    result = []
    for name in ('PkgDerivedKey3Keyset', 'FakeKeyset'):
        match = re.search(r'(?:struct|class)\s+' + name + r'\s*\{(.*?)\n\};', source, re.S)
        if not match:
            raise ValueError('Missing RSA keyset ' + name)
        values = {}
        for field, body in re.findall(r'(\w+)\[.*?\]\s*=\s*\{(.*?)\}', match[1], re.S):
            values[field] = int.from_bytes(bytes(int(v, 0) for v in re.findall(r'0x[\da-fA-F]+|\b\d+\b', re.sub(r'//[^\n]*', '', body))), 'big')
        try:
            key = rsa.RSAPrivateNumbers(values['Prime1'], values['Prime2'],
                values['PrivateExponent'], values['Exponent1'], values['Exponent2'],
                values['Coefficient'], rsa.RSAPublicNumbers(values['PublicExponent'], values['Modulus'])).private_key()
        except (KeyError, ValueError) as error:
            raise ValueError('Invalid RSA keyset ' + name) from error
        result.append(key)
    return result


def safe_path(name):
    if not name or '\\' in name or '\x00' in name or ':' in name:
        raise ValueError('Unsafe package path')
    parts = name.split('/')
    if any(part in ('', '.', '..') for part in parts) or PurePosixPath(name).is_absolute():
        raise ValueError('Unsafe package path: ' + repr(name))
    return Path(*parts)


@dataclass(frozen=True)
class Entry:
    id: int
    name_offset: int
    flags1: int
    flags2: int
    offset: int
    size: int
    raw: bytes


class Package:
    def __init__(self, stream):
        self.stream = stream
        self.length = stream.seek(0, 2)
        header = self.read(0, 0x480)
        if header[:4] != b'\x7fCNT':
            raise ValueError('Not a PS4 PKG (invalid magic)')
        self.pfs_offset, self.pfs_size = struct.unpack_from('>QQ', header, 0x410)
        self.pkg_size = struct.unpack_from('>Q', header, 0x430)[0]
        self.cache_size = struct.unpack_from('>I', header, 0x43c)[0]
        content_offset, content_size = struct.unpack_from('>QQ', header, 0x30)
        if self.pkg_size != self.length or content_offset + content_size > self.pkg_size:
            raise ValueError('PKG size/content bounds are invalid or file is truncated')
        if self.pfs_offset + self.pfs_size > self.pkg_size or self.pfs_size < SECTOR:
            raise ValueError('Invalid PFS image bounds')
        count = struct.unpack_from('>I', header, 0x10)[0]
        offset = struct.unpack_from('>I', header, 0x18)[0]
        if not 0 < count <= 100000 or offset + count * 32 > self.length:
            raise ValueError('Invalid PKG entry table')
        self.entries = []
        for index in range(count):
            raw = self.read(offset + index * 32, 32)
            entry = Entry(*struct.unpack_from('>6I', raw), raw)
            if entry.offset + entry.size > self.pkg_size:
                raise ValueError('PKG entry exceeds package bounds')
            self.entries.append(entry)
        self.by_id = {e.id: e for e in self.entries}
        if len(self.by_id) != len(self.entries):
            raise ValueError('Duplicate PKG entry ID')

    def read(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.length:
            raise ValueError('Read exceeds package bounds')
        self.stream.seek(offset)
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError('Truncated package')
        return data

    def entry_data(self, id):
        try:
            e = self.by_id[id]
        except KeyError as error:
            raise ValueError(f'Missing required PKG entry {id:#x}') from error
        if e.size > 16 * 1024 * 1024:
            raise ValueError('Oversized PKG metadata entry')
        return self.read(e.offset, e.size)

    def cbc(self, entry, dk3, data):
        ivkey = hashlib.sha256(entry.raw + dk3).digest()
        if len(data) % 16:
            raise ValueError('Encrypted entry is not AES block aligned')
        decryptor = Cipher(algorithms.AES(ivkey[16:]), modes.CBC(ivkey[:16])).decryptor()
        return decryptor.update(data) + decryptor.finalize()

    def unlock(self, keys):
        entry_keys = self.entry_data(0x10)
        if len(entry_keys) < 32 + 7 * 32 + 7 * 256:
            raise ValueError('Truncated entry_keys')
        dk3 = keys[0].decrypt(entry_keys[256 + 3 * 256:256 + 4 * 256], padding.PKCS1v15())
        if len(dk3) < 32:
            raise ValueError('Invalid derived PKG key (unsupported package)')
        dk3 = dk3[:32]
        image_data = self.entry_data(0x20)
        if len(image_data) != 256:
            raise ValueError('Invalid image_key size')
        image = self.cbc(self.by_id[0x20], dk3, image_data)
        ekpfs = keys[1].decrypt(image, padding.PKCS1v15())
        if len(ekpfs) < 32:
            raise ValueError('Invalid image key (unsupported package)')
        seed = self.read(self.pfs_offset + 0x370, 16)
        derived = hmac.digest(ekpfs[:32], struct.pack('<I', 1) + seed, 'sha256')
        self.xts_key = derived[16:] + derived[:16]
        return dk3

    def decrypted(self, offset, size):
        start = offset // SECTOR * SECTOR
        end = (offset + size + SECTOR - 1) // SECTOR * SECTOR
        if offset < 0 or end > self.pfs_size:
            raise ValueError('Read exceeds PFS image bounds')
        encrypted = self.read(self.pfs_offset + start, end - start)
        plain = bytearray()
        for pos in range(0, len(encrypted), SECTOR):
            sector = (start + pos) // SECTOR
            dec = Cipher(algorithms.AES(self.xts_key), modes.XTS(sector.to_bytes(16, 'little'))).decryptor()
            plain.extend(dec.update(encrypted[pos:pos + SECTOR]) + dec.finalize())
        return bytes(plain[offset - start:offset - start + size])

    def setup_pfs(self):
        # Scan sectors instead of allocating the potentially huge PFS cache.
        limit = min(self.cache_size * 2, self.pfs_size)
        for offset in range(0x20000, limit, BLOCK):
            header = self.decrypted(offset, 48)
            if header[:4] == b'PFSC':
                self.pfsc_offset = offset
                break
        else:
            raise ValueError('PFSC image not found (unsupported or corrupt package)')
        _, _, _, block_size, block_size2, map_offset, _, length = struct.unpack('<4I4Q', header)
        if block_size != BLOCK or block_size2 != BLOCK or length % BLOCK:
            raise ValueError('Unsupported PFSC block layout')
        count = length // BLOCK
        if not 1 <= count <= 16 * 1024 * 1024 or map_offset < 48:
            raise ValueError('Invalid PFSC block map')
        raw = self.decrypted(offset + map_offset, (count + 1) * 8)
        self.block_map = struct.unpack('<' + 'Q' * (count + 1), raw)
        if self.block_map[0] < map_offset + len(raw) or offset + self.block_map[-1] > self.pfs_size:
            raise ValueError('PFSC block map exceeds image bounds')
        if any(not 0 < b - a <= BLOCK for a, b in zip(self.block_map, self.block_map[1:])):
            raise ValueError('Invalid PFSC stored block length')

    def block(self, index):
        if not 0 <= index < len(self.block_map) - 1:
            raise ValueError('Invalid inode block reference')
        start, end = self.block_map[index:index + 2]
        data = self.decrypted(self.pfsc_offset + start, end - start)
        if len(data) == BLOCK:
            return data
        dec = zlib.decompressobj()
        plain = dec.decompress(data, BLOCK + 1)
        if len(plain) != BLOCK or not dec.eof or dec.unconsumed_tail:
            raise ValueError('Invalid compressed PFSC block')
        return plain

    def inodes(self):
        count = struct.unpack_from('<I', self.block(0), 0x30)[0]
        if not 1 <= count <= 1000000:
            raise ValueError('Invalid PFS inode count')
        nodes = []
        # Each metadata block holds whole 0xa8-byte records, with tail padding.
        per_block = BLOCK // 0xa8
        for index in range(1, (count + per_block - 1) // per_block + 1):
            data = self.block(index)
            for pos in range(0, BLOCK - 0xa8 + 1, 0xa8):
                mode = struct.unpack_from('<H', data, pos)[0]
                if not mode:
                    break
                size = struct.unpack_from('<Q', data, pos + 8)[0]
                blocks, loc = struct.unpack_from('<II', data, pos + 0x60)
                nodes.append((mode, size, blocks, loc))
                if len(nodes) == count:
                    return nodes
        raise ValueError('Truncated PFS inode table')

    def dirents(self, node):
        _, size, blocks, loc = node
        if size > blocks * BLOCK or loc + blocks >= len(self.block_map):
            raise ValueError('Invalid directory extent')
        remaining = size
        for index in range(blocks):
            data = self.block(loc + index)[:min(remaining, BLOCK)]
            remaining -= len(data)
            pos = 0
            while pos + 16 <= len(data):
                ino, kind, namesize, entsize = struct.unpack_from('<4I', data, pos)
                if ino == 0 and entsize == 0:
                    break
                if entsize < 16 or entsize % 8 or pos + entsize > len(data) or not 0 < namesize <= entsize - 16:
                    raise ValueError('Invalid PFS directory record')
                name = data[pos + 16:pos + 16 + namesize].decode('utf-8')
                yield ino, kind, name
                pos += entsize

    def files(self):
        nodes = self.inodes()
        # PFS inode zero is the super-root; its uroot directory is the game root.
        roots = [ino for ino, kind, name in self.dirents(nodes[0]) if kind == 3 and name == 'uroot']
        if len(roots) != 1:
            raise ValueError('PFS super-root does not contain exactly one uroot')
        queue = [(roots[0], Path())]
        visited = set()
        while queue:
            ino, path = queue.pop()
            if ino in visited or not 0 <= ino < len(nodes):
                raise ValueError('Invalid or cyclic PFS directory')
            visited.add(ino)
            if nodes[ino][0] & 0xf000 != 0x4000:
                raise ValueError('Directory inode has unsupported mode')
            yield path, None
            for child, kind, name in self.dirents(nodes[ino]):
                if kind in (4, 5):
                    if name != ('.' if kind == 4 else '..'):
                        raise ValueError('Invalid dot directory record')
                    continue
                rel = safe_path(name)
                if len(rel.parts) != 1 or not 0 <= child < len(nodes):
                    raise ValueError('Invalid PFS child entry')
                target = path / rel
                if kind == 3:
                    queue.append((child, target))
                elif kind == 2 and nodes[child][0] & 0xf000 == 0x8000:
                    yield target, nodes[child]
                else:
                    raise ValueError('Unsupported PFS entry (symlinks are refused)')


def extract(pkg, destination, keys=None, progress=print):
    destination = Path(destination)
    # Reject symlink ancestors and any existing destination, including empty ones.
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError('Extraction destination cannot contain symlinks')
    if destination.exists():
        raise ValueError('Extraction destination already exists')
    with Path(pkg).open('rb') as stream:
        package = Package(stream)
        dk3 = package.unlock(load_keys() if keys is None else keys)
        package.setup_pfs()
        names = package.entry_data(0x200) if 0x200 in package.by_id else b''
        fallbacks = json.loads((ROOT / 'tools/pkg_entry_names.json').read_text())
        destination.mkdir(parents=True)
        metadata = set()
        for entry in package.entries:
            name = ''
            if entry.name_offset:
                if entry.name_offset >= len(names):
                    raise ValueError('Invalid PKG filename offset')
                end = names.find(b'\0', entry.name_offset)
                if end < 0:
                    raise ValueError('Unterminated PKG filename')
                name = names[entry.name_offset:end].decode('utf-8')
            name = name or fallbacks.get(str(entry.id), str(entry.id))
            path = destination / 'sce_sys' / safe_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            progress('Metadata: sce_sys/' + name)
            metadata.add(path)
            with path.open('xb') as output:
                if 0x400 <= entry.id <= 0x403:
                    if entry.size > 16 * 1024 * 1024:
                        raise ValueError('Oversized encrypted metadata entry')
                    encrypted = package.read(entry.offset, (entry.size + 15) // 16 * 16)
                    output.write(package.cbc(entry, dk3, encrypted)[:entry.size])
                else:
                    for pos in range(0, entry.size, 1024 * 1024):
                        output.write(package.read(entry.offset + pos, min(1024 * 1024, entry.size - pos)))
        for relative, node in package.files():
            path = destination / relative
            if node is None:
                path.mkdir(parents=True, exist_ok=True)
                continue
            _, size, blocks, loc = node
            if size > blocks * BLOCK or loc + blocks >= len(package.block_map):
                raise ValueError('Invalid file extent: ' + str(relative))
            path.parent.mkdir(parents=True, exist_ok=True)
            progress(f'File: {relative} ({size:,} bytes)')
            if path in metadata and path.is_file() and not path.is_symlink():
                # The game image's sce_sys copy wins over the PKG metadata entry
                # (the dump layout console tools produce); anything else is refused.
                metadata.discard(path); path.unlink()
            with path.open('xb') as output:
                remaining = size
                for index in range(blocks):
                    data = package.block(loc + index)
                    output.write(data[:min(remaining, BLOCK)])
                    remaining -= min(remaining, BLOCK)
                    if index and index % 1024 == 0:
                        progress(f'  {size - remaining:,} / {size:,} bytes')
        progress('Extraction complete.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pkg', type=Path)
    parser.add_argument('out_dir', type=Path)
    args = parser.parse_args()
    try:
        extract(args.pkg, args.out_dir, progress=lambda line: print(line, flush=True))
    except (OSError, ValueError, struct.error, zlib.error) as error:
        print('Extraction failed: ' + str(error), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

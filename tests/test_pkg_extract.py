# SPDX-License-Identifier: GPL-3.0-or-later
"""Entirely synthetic PKG, RSA and encrypted PFSC fixtures; no game/key data."""
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from tools import pkg_extract as pkg


def encrypt(data, key, mode):
    enc = Cipher(algorithms.AES(key), mode).encryptor()
    return enc.update(data) + enc.finalize()


def directory(entries):
    result = bytearray(pkg.BLOCK)
    pos = 0
    for ino, kind, name in entries:
        name = name.encode()
        length = (16 + len(name) + 7) // 8 * 8
        struct.pack_into('<4I', result, pos, ino, kind, len(name), length)
        result[pos + 16:pos + 16 + len(name)] = name
        pos += length
    return bytes(result)


def fixture(keys, name='eboot.bin', kind=2, mode=0x8000, corrupt_zlib=False, folder='folder', nested=None):
    block = pkg.BLOCK
    content = bytes(range(256)) * 256 + b'truncated tail'
    blocks = [bytearray(block) for _ in range(8)]
    nodes = [(0x4000,block,1,2), (0x8000,0,0,0),
             (0x4000,block,1,3), (mode,len(content),2,6),
             (0x4000,block,1,4)] + ([(0x8000,len(content),2,6)] if nested else [])
    struct.pack_into('<I', blocks[0], 0x30, len(nodes))
    for i, (m, size, count, loc) in enumerate(nodes):
        struct.pack_into('<H', blocks[1], i * 0xa8, m)
        struct.pack_into('<Q', blocks[1], i * 0xa8 + 8, size)
        struct.pack_into('<II', blocks[1], i * 0xa8 + 0x60, count, loc)
    blocks[2] = directory([(1,2,'flat_path_table'),(2,3,'uroot')])
    blocks[3] = directory([(2,4,'.'),(0,5,'..'),(3,kind,name),(4,3,folder)])
    blocks[4] = directory([(4,4,'.'),(2,5,'..')] + ([(5,2,nested)] if nested else []))
    blocks[6] = content[:block] # raw path
    blocks[7][:len(content)-block] = content[block:]
    stored = [bytes(b) if i == 6 else zlib.compress(b) for i,b in enumerate(blocks)]
    if corrupt_zlib:
        stored[7] = b'bad zlib'
    offsets = [0x1000]
    for b in stored:
        offsets.append(offsets[-1] + len(b))
    pfsc_offset = 0x20000
    image_size = (pfsc_offset + offsets[-1] + 0xfff) // 0x1000 * 0x1000
    plain = bytearray(image_size)
    struct.pack_into('<4I4Q', plain, pfsc_offset, 0x43534650,0,0,block,block,48,0x1000,len(blocks)*block)
    struct.pack_into('<9Q', plain, pfsc_offset + 48, *offsets)
    for offset,data in zip(offsets, stored):
        plain[pfsc_offset+offset:pfsc_offset+offset+len(data)] = data
    # All key bytes below are synthetic, with generated RSA keys supplied by tests.
    dk3, ekpfs, seed = bytes(range(32)),bytes(range(32,64)),bytes(range(16))
    derived = hmac.digest(ekpfs,struct.pack('<I',1)+seed,'sha256')
    encrypted = bytearray()
    for offset in range(0,len(plain),0x1000):
        encrypted.extend(encrypt(bytes(plain[offset:offset+0x1000]),derived[16:]+derived[:16],modes.XTS((offset//0x1000).to_bytes(16,'little'))))
    encrypted[0x370:0x380] = seed
    entry_keys = bytearray(2048)
    entry_keys[1024:1280] = keys[0].public_key().encrypt(dk3,padding.PKCS1v15())
    image_key = keys[1].public_key().encrypt(ekpfs,padding.PKCS1v15())
    metadata = b'synthetic metadata'
    entries = [(0x10,0,entry_keys),(0x20,0,image_key),(0x200,0,b'\0custom.bin\0'),(0x1000,0,b'synthetic sfo'),(0x402,1,metadata)]
    result = bytearray(0x10000)
    pos = 0x2000
    for index,(id,nameoff,data) in enumerate(entries):
        raw = struct.pack('>6IQ',id,nameoff,0,0,pos,len(data),0)
        result[0x1000+index*32:0x1020+index*32] = raw
        if id in (0x20,0x402):
            ivkey = hashlib.sha256(raw+dk3).digest()
            data = encrypt(data+b'\0'*((-len(data))%16),ivkey[16:],modes.CBC(ivkey[:16]))
        result[pos:pos+len(data)] = data
        pos += (len(data)+15)//16*16
    result.extend(encrypted)
    result[:4] = b'\x7fCNT'
    struct.pack_into('>I',result,0x10,len(entries))
    struct.pack_into('>I',result,0x18,0x1000)
    struct.pack_into('>QQ',result,0x410,0x10000,image_size)
    struct.pack_into('>Q',result,0x430,len(result))
    struct.pack_into('>I',result,0x43c,image_size//2)
    return bytes(result),content,metadata


class ExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = [rsa.generate_private_key(public_exponent=65537,key_size=2048) for _ in range(2)]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root/'input.pkg'
        self.output = self.root/'output'

    def tearDown(self):
        self.temp.cleanup()

    def run_fixture(self, **kwargs):
        data,content,metadata = fixture(self.keys,**kwargs)
        self.input.write_bytes(data)
        pkg.extract(self.input,self.output,keys=self.keys,progress=lambda s:None)
        return content,metadata

    def test_complete_extract_raw_zlib_nested_directory_truncation_and_names(self):
        content,metadata = self.run_fixture()
        self.assertEqual((self.output/'eboot.bin').read_bytes(),content)
        self.assertTrue((self.output/'folder').is_dir())
        self.assertEqual((self.output/'sce_sys/custom.bin').read_bytes(),metadata)
        self.assertEqual((self.output/'sce_sys/param.sfo').read_bytes(),b'synthetic sfo')
        self.assertFalse((self.output/'flat_path_table').exists())
        with self.assertRaisesRegex(ValueError,'already exists'):
            pkg.extract(self.input,self.output,keys=self.keys)
        self.assertEqual((self.output/'eboot.bin').read_bytes(),content)

    def test_image_sce_sys_file_replaces_metadata_copy(self):
        # The game image has sce_sys/param.sfo too: its copy replaces the PKG entry's.
        content,_ = self.run_fixture(folder='sce_sys',nested='param.sfo')
        self.assertEqual((self.output/'sce_sys/param.sfo').read_bytes(),content)
        self.assertEqual((self.output/'sce_sys/custom.bin').read_bytes(),b'synthetic metadata')

    def test_image_never_replaces_its_own_files(self):
        data,_,_ = fixture(self.keys,folder='sce_sys',nested='param.sfo')
        self.input.write_bytes(data)
        real = pkg.Package.files
        def twice(package):  # the same image path listed twice must still be refused
            for item in real(package):
                yield item
                if item[1] is not None and item[0].name == 'param.sfo': yield item
        with patch.object(pkg.Package,'files',twice), self.assertRaises(FileExistsError):
            pkg.extract(self.input,self.output,keys=self.keys,progress=lambda s:None)

    def test_header_and_entry_bounds(self):
        data,_,_ = fixture(self.keys)
        for offset,value in [(0,b'bad!'),(0x10,struct.pack('>I',0xffffffff)),
                             (0x1010,struct.pack('>I',len(data))),
                             (0x430,struct.pack('>Q',len(data)+1))]:
            with self.subTest(offset=offset):
                broken=bytearray(data);broken[offset:offset+len(value)]=value
                with self.assertRaises(ValueError): pkg.Package(io.BytesIO(broken))
        with self.assertRaises(ValueError): pkg.Package(io.BytesIO(b'short'))

    def test_paths_and_symlinks_refused(self):
        for path in ('../escape','/absolute','folder/../../escape','a\\b','a//b','C:escape','.', 'nul\0'):
            with self.subTest(path=path), self.assertRaises(ValueError): pkg.safe_path(path)
        self.input.write_bytes(fixture(self.keys)[0])
        link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):
            pkg.extract(self.input,link/'new',keys=self.keys)
        with self.assertRaisesRegex(ValueError,'symlink'):
            self.run_fixture(kind=6,mode=0xa000)

    def test_directory_traversal_refused(self):
        with self.assertRaisesRegex(ValueError,'Unsafe package path'):
            self.run_fixture(name='../escape')
        self.assertFalse((self.root/'escape').exists())

    def test_corrupt_compressed_file_fails(self):
        with self.assertRaises((ValueError,zlib.error)):
            self.run_fixture(corrupt_zlib=True)

    def test_metadata_traversal_refused(self):
        data=bytearray(fixture(self.keys)[0])
        q=pkg.Package(io.BytesIO(data));e=q.by_id[0x200]
        data[e.offset:e.offset+e.size]=b'\0../bad\0\0\0\0\0'
        self.input.write_bytes(data)
        with self.assertRaises(ValueError): pkg.extract(self.input,self.output,keys=self.keys,progress=lambda s:None)
        self.assertFalse((self.output/'bad').exists())

    def test_missing_required_entry_is_clear_error(self):
        data=bytearray(fixture(self.keys)[0])
        struct.pack_into('>I',data,0x1020,0x21)
        self.input.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'Missing required PKG entry 0x20'):
            pkg.extract(self.input,self.output,keys=self.keys,progress=lambda s:None)
        self.assertFalse(self.output.exists())

    def test_invalid_pfs_map_and_directory_cycle(self):
        data=fixture(self.keys)[0]
        q=pkg.Package(io.BytesIO(data));q.unlock(self.keys);q.setup_pfs()
        q.block_map=(100,99)
        with self.assertRaises(ValueError): q.block(1)
        nodes=[(0x4000,1,0,0),(0x4000,2,0,0)]
        def records(node):
            return [(1,3,'uroot')] if node is nodes[0] else [(1,3,'cycle')]
        with patch.object(q,'inodes',return_value=nodes),patch.object(q,'dirents',side_effect=records):
            with self.assertRaisesRegex(ValueError,'cyclic'): list(q.files())

    def test_runtime_key_parser_with_generated_keys(self):
        source=''
        for name,key in zip(('PkgDerivedKey3Keyset','FakeKeyset'),self.keys):
            n=key.private_numbers();pub=n.public_numbers
            values=dict(Prime1=n.p,Prime2=n.q,PrivateExponent=n.d,Exponent1=n.dmp1,
                        Exponent2=n.dmq1,Coefficient=n.iqmp,PublicExponent=pub.e,Modulus=pub.n)
            source+='class '+name+' {\n'
            for field,value in values.items():
                raw=value.to_bytes((value.bit_length()+7)//8,'big')
                source+='static constexpr byte '+field+'[] = {'+','.join(hex(b) for b in raw)+'};\n'
            source+='\n};\n'
        parsed=pkg.parse_keys(source)
        self.assertEqual(parsed[0].private_numbers(),self.keys[0].private_numbers())
        with self.assertRaisesRegex(ValueError,'Missing RSA keyset'): pkg.parse_keys('')

    def test_key_download_hash_mismatch_never_cached(self):
        source={'path':'keys.h','url':'https://example.invalid/keys.h','sha256':'0'*64}
        (self.root/'LICENSES').mkdir()
        import json
        (self.root/'LICENSES/pkg-source.json').write_text(json.dumps({'keys':source}))
        with patch.object(pkg,'ROOT',self.root),patch.object(pkg.urllib.request,'urlopen',return_value=io.BytesIO(b'not keys')):
            with self.assertRaisesRegex(ValueError,'hash mismatch'): pkg.load_keys()
        self.assertFalse((self.root/'.local/shadps4-pkg-reference/keys.h').exists())


if __name__ == '__main__':
    unittest.main()

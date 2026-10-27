# SPDX-License-Identifier: GPL-3.0-or-later
import ctypes
import hashlib
import mmap
import platform
import struct
import sys
import unittest

from tools import prepare_native as n
from tools.level_events_mod import (patch_pack, observer_stub, event_stub, relative,
    MAILBOX, MAILBOX_MAGIC, MAILBOX_SIZE, RECORD_SIZE)


def fixture():
    base=0x400000
    code=bytearray(4096)
    first=b'\x48\x8d\x3d'+relative(base+0x200,base+0x47)
    second=b'\xe8'+relative(base+0x240,base+0x65)
    third=b'\xe8'+relative(base+0x280,base+0x85)
    code[0x40:0x47]=first;code[0x60:0x65]=second;code[0x80:0x85]=third
    data=n.HEADER.pack(n.MAGIC,base,base,4096,1,0,0)
    data+=n.SEGMENT.pack(base,4096,4096,5,n.HEADER.size+n.SEGMENT.size)+code
    profile={'pack_sha256':{'synthetic':hashlib.sha256(data).hexdigest()},'status':'synthetic only','commit_label_address':base+0x300,
             'hooks':[dict(event='switch-request',kind='subscription-tail',virtual_address=base+0x40,
                           expected_hex=first.hex(),original_target=base+0x200),
                      dict(event='load-commit-return',kind='call-return-three-register-args',
                           virtual_address=base+0x60,expected_hex=second.hex(),original_target=base+0x240),
                      dict(event='load-begin',kind='call-tail-utf16-name',virtual_address=base+0x80,
                           expected_hex=third.hex(),original_target=base+0x280)]}
    return data,profile


class LevelEventModTests(unittest.TestCase):
    def test_private_pack_gains_separate_rx_and_rw_pages(self):
        data,profile=fixture()
        output,metadata=patch_pack(data,profile,'synthetic')
        header=n.HEADER.unpack_from(output)
        self.assertEqual(header[4],3)
        records=[n.SEGMENT.unpack_from(output,n.HEADER.size+i*n.SEGMENT.size) for i in range(3)]
        self.assertEqual([r[3] for r in records],[5,5,6])
        self.assertEqual(records[0][4],n.HEADER.size+3*n.SEGMENT.size)
        box=output[records[2][4]:records[2][4]+MAILBOX.size]
        self.assertEqual(MAILBOX.unpack(box),(MAILBOX_MAGIC,2,0,0,0,0,0,0))
        self.assertEqual(records[2][0],metadata['mailbox_address'])
        # Source bytes and original targets are unchanged; only checked sites move.
        self.assertEqual(data,fixture()[0])
        self.assertEqual(output[records[0][4]+0x200:records[0][4]+0x240],bytes(0x40))

    def test_hash_expected_bytes_and_branch_targets_fail_closed(self):
        data,profile=fixture()
        with self.assertRaisesRegex(ValueError,'unknown linked pack'):
            patch_pack(data+b'x',profile,'synthetic')
        profile['hooks'][0]['expected_hex']='90'*7
        with self.assertRaisesRegex(ValueError,'bytes mismatch'):
            patch_pack(data,profile,'synthetic')
        data,profile=fixture();profile['hooks'][1]['original_target']+=1
        with self.assertRaisesRegex(ValueError,'target mismatch'):
            patch_pack(data,profile,'synthetic')
        with self.assertRaises(ValueError):relative(1<<40,0)

    @unittest.skipUnless(sys.platform=='linux' and platform.machine()=='x86_64','SysV x86-64 ABI')
    def test_real_stubs_preserve_scalar_abi_and_commit_is_after_return(self):
        try:
            memory=mmap.mmap(-1,4096,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
        except OSError as error:
            self.skipTest(str(error))
        address=ctypes.addressof(ctypes.c_char.from_buffer(memory))
        counter=ctypes.c_uint64.from_buffer(memory,256)
        observations=[]
        signature=ctypes.CFUNCTYPE(ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64)
        @signature
        def original(a,b,c):
            observations.append((a,b,c,counter.value))
            return a+7*b+11*c
        target=ctypes.cast(original,ctypes.c_void_p).value
        try:
            for after in (False,True):
                counter.value=0
                try:code=observer_stub(address,target,address+256,after)
                except ValueError as error:self.skipTest(str(error))
                memory[:len(code)]=code
                result=signature(address)(3,5,9)
                self.assertEqual(result,137)
                self.assertEqual(counter.value,1)
                self.assertEqual(observations[-1],(3,5,9,0 if after else 1))
        finally:
            del counter
            memory.close()

    @unittest.skipUnless(sys.platform=='linux' and platform.machine()=='x86_64','SysV x86-64 ABI')
    def test_named_stubs_copy_live_names_preserve_abi_and_publish_ring(self):
        memory=mmap.mmap(-1,32768,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
        address=ctypes.addressof(ctypes.c_char.from_buffer(memory))
        box=address+4096
        label=ctypes.create_string_buffer(b'misc0/ui_pausemenu_streamed')
        utf16=ctypes.create_string_buffer('misc/ui_pausemenu_streamed'.encode('utf-16-le')+b'\0\0')
        message=(ctypes.c_uint64*5)(0,0,ctypes.addressof(utf16),1234,0)
        signature=ctypes.CFUNCTYPE(ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64)
        seen=[]
        @signature
        def target(a,b,c):
            seen.append((a,b,c,struct.unpack_from('<Q',memory,4096+32)[0]))
            return a+7*c
        pointer=ctypes.cast(target,ctypes.c_void_p).value
        def install(kind):
            code=event_stub(address,pointer,box,kind,ctypes.addressof(label))
            memory[:len(code)]=code
            return signature(address)
        def record(ticket):
            offset=4096+64+((ticket-1)%64)*RECORD_SIZE
            fields=struct.unpack_from('<4Q192s',memory,offset)
            return (*fields[:4],fields[4].split(b'\0')[0])
        try:
            memory[4096:4096+MAILBOX_SIZE]=bytes(MAILBOX_SIZE)
            memory[4096:4096+MAILBOX.size]=MAILBOX.pack(MAILBOX_MAGIC,2,0,0,0,0,0,0)
            for kind,argument,name,pool in ((1,ctypes.addressof(message),b'misc/ui_pausemenu_streamed',1234),
                                          (2,77,b'misc0/ui_pausemenu_streamed',0),
                                          (3,ctypes.addressof(utf16),b'misc/ui_pausemenu_streamed',0)):
                call=install(kind)
                self.assertEqual(call(3,argument,9),66)
                self.assertEqual(seen[-1][:3],(3,argument,9))
                self.assertEqual(seen[-1][3],kind-1 if kind==2 else kind)
                self.assertEqual(record(kind),(kind,kind,0,pool,name))
            # Null messages and UTF-16 arguments never dereference address zero.
            install(1)(1,0,2);self.assertEqual(record(4)[4],b'')
            install(3)(1,0,2);self.assertEqual(record(5)[4],b'')
            # Non-ASCII/truncated names carry explicit flags; callers fail closed.
            unicode=ctypes.create_string_buffer(('a\u03a9'+'z'*220).encode('utf-16-le')+b'\0\0')
            install(3)(1,ctypes.addressof(unicode),2)
            self.assertEqual(record(6)[2],3)
            self.assertEqual(record(6)[4],b'a?'+b'z'*189)
            # A busy publisher never spins or leaves a lock held by this writer.
            struct.pack_into('<Q',memory,4096+48,1)
            install(3)(1,ctypes.addressof(utf16),2)
            self.assertEqual(struct.unpack_from('<Q',memory,4096+32)[0],6)
            self.assertEqual(struct.unpack_from('<Q',memory,4096+40)[0],1)
            struct.pack_into('<Q',memory,4096+48,0)
            call=install(3)
            for _ in range(70):call(1,ctypes.addressof(utf16),2)
            self.assertEqual(record(76),(76,3,0,0,b'misc/ui_pausemenu_streamed'))
            self.assertEqual(struct.unpack_from('<Q',memory,4096+48)[0],0)
        finally:
            memory.close()

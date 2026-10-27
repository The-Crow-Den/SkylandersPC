# SPDX-License-Identifier: GPL-3.0-or-later
import ctypes
import hashlib
import mmap
import platform
import struct
import unittest
from tools import prepare_native as n
from tools.fps_probe_mod import argument_stub, patch_pack, MAGIC, CAPACITY, INLINE_SPRITE_DELTA, INLINE_PARTICLE_DISPATCH, UV_TRACK_ENTRY
from tools.game_build import US_UPDATE_SHA256
from tools.level_events_mod import relative


def fixture():
    base=0x400000
    code=bytearray(4096)
    call=b'\xe8'+relative(base+0x100,base+0x45)
    code[0x40:0x45]=call
    data=n.HEADER.pack(n.MAGIC,base,base,4096,1,0,0)
    data+=n.SEGMENT.pack(base,4096,4096,5,n.HEADER.size+n.SEGMENT.size)+code
    profile=dict(executable_sha256=US_UPDATE_SHA256,
                 pack_sha256=hashlib.sha256(data).hexdigest(),hooks=[
                     dict(site=1,virtual_address=base+0x40,original_target=base+0x100,expected_hex=call.hex())])
    return data,profile


class TimingProbeTests(unittest.TestCase):
    def test_pack_keeps_original_and_adds_rx_rw_regions(self):
        data,p=fixture(); result,meta=patch_pack(data,p)
        h=n.HEADER.unpack_from(result)
        self.assertEqual(h[4],3)
        records=[n.SEGMENT.unpack_from(result,n.HEADER.size+i*40) for i in range(3)]
        self.assertEqual([r[3] for r in records],[5,5,6])
        self.assertEqual(result[records[2][4]:records[2][4]+8],MAGIC)
        self.assertEqual(records[2][0],meta['mailbox_address'])
        self.assertEqual(data,fixture()[0])
        self.assertFalse(meta['timing_modified'])

    def test_identity_bytes_target_and_overlaps_refused(self):
        data,p=fixture()
        with self.assertRaisesRegex(ValueError,'unknown pack'):patch_pack(data+b'x',p)
        p['executable_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'exact US'):patch_pack(data,p)
        data,p=fixture();p['hooks'][0]['original_target']+=1
        with self.assertRaisesRegex(ValueError,'target mismatch'):patch_pack(data,p)
        data,p=fixture();p['hooks'].append(dict(p['hooks'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'):patch_pack(data,p)
        data,p=fixture();p['hooks'][0]['virtual_address']+=8
        p['hooks'][0]['original_target']+=8
        with self.assertRaisesRegex(ValueError,'bytes mismatch'):patch_pack(data,p)

    def test_exact_inline_sprite_observation_preserves_following_call(self):
        data,p=fixture();data=bytearray(data)
        segment=n.HEADER.size+n.SEGMENT.size
        data[segment+0x50:segment+0x58]=INLINE_SPRITE_DELTA
        data=bytes(data);p['pack_sha256']=hashlib.sha256(data).hexdigest()
        p['hooks'].append(dict(site=2,kind='inline-before-virtual',
                               virtual_address=0x400050,
                               expected_hex=INLINE_SPRITE_DELTA.hex()))
        result,meta=patch_pack(data,p)
        offset=segment+2*n.SEGMENT.size
        self.assertEqual(result[offset+0x50],0xe9)
        self.assertEqual(result[offset+0x55:offset+0x58],b'\x90'*3)
        self.assertFalse(meta['timing_modified'])
        p['hooks'][1]['expected_hex']='90'*8
        with self.assertRaisesRegex(ValueError,'inline instruction mismatch'):
            patch_pack(data,p)

    def test_exact_uv_track_entry_replays_whole_prologue(self):
        data,p=fixture();data=bytearray(data)
        segment=n.HEADER.size+n.SEGMENT.size
        data[segment+0x60:segment+0x66]=UV_TRACK_ENTRY
        data=bytes(data);p['pack_sha256']=hashlib.sha256(data).hexdigest()
        p['hooks'].append(dict(site=12,kind='function-entry',virtual_address=0x400060,
                               expected_hex=UV_TRACK_ENTRY.hex()))
        result,meta=patch_pack(data,p)
        offset=segment+2*n.SEGMENT.size
        self.assertEqual(result[offset+0x60],0xe9)
        self.assertEqual(result[offset+0x65],0x90)
        self.assertFalse(meta['timing_modified'])
        p['hooks'][1]['expected_hex']='90'*6
        with self.assertRaisesRegex(ValueError,'inline instruction mismatch'):patch_pack(data,p)

    def test_exact_particle_dispatch_replays_both_integer_moves(self):
        data,p=fixture();data=bytearray(data)
        segment=n.HEADER.size+n.SEGMENT.size
        data[segment+0x60:segment+0x66]=INLINE_PARTICLE_DISPATCH
        data=bytes(data);p['pack_sha256']=hashlib.sha256(data).hexdigest()
        p['hooks'].append(dict(site=14,kind='inline-before-virtual',virtual_address=0x400060,
                               expected_hex=INLINE_PARTICLE_DISPATCH.hex()))
        result,meta=patch_pack(data,p)
        offset=segment+2*n.SEGMENT.size
        self.assertEqual(result[offset+0x60],0xe9)
        self.assertEqual(result[offset+0x65],0x90)
        self.assertFalse(meta['timing_modified'])
        p['hooks'][1]['expected_hex']='90'*6
        with self.assertRaisesRegex(ValueError,'inline instruction mismatch'):patch_pack(data,p)

    @unittest.skipUnless(platform.machine()=='x86_64','x86-64 native synthetic execution')
    def test_stub_preserves_float_arguments_and_tail_stack_and_drops_without_wait(self):
        memory=mmap.mmap(-1,400000,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
        address=ctypes.addressof(ctypes.c_char.from_buffer(memory));box=address+8192
        try:
            # Original synthetic target returns XMM0+XMM1. No game code is used.
            memory[4096:4101]=bytes.fromhex('f3 0f 58 c1 c3')
            code=argument_stub(address,address+4096,box,3);memory[:len(code)]=code
            fn=ctypes.CFUNCTYPE(ctypes.c_float,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_float,ctypes.c_float)(address)
            self.assertEqual(fn(123,456,0.125,0.5),0.625)
            self.assertEqual(struct.unpack_from('<Q',memory,8192+32)[0],1)
            self.assertEqual(struct.unpack_from('<4Q2f',memory,8192+64),(1,3,123,456,0.125,0.5))
            struct.pack_into('<I',memory,8192+48,1)
            self.assertEqual(fn(9,8,2.,3.),5.)
            self.assertEqual(struct.unpack_from('<Q',memory,8192+40)[0],1)
            self.assertEqual(struct.unpack_from('<Q',memory,8192+32)[0],1)
            struct.pack_into('<I',memory,8192+48,0)
            # Ring wrap remains bounded and publishes the latest ticket.
            struct.pack_into('<Q',memory,8192+32,CAPACITY)
            self.assertEqual(fn(5,6,1.,2.),3.)
            self.assertEqual(struct.unpack_from('<Q',memory,8192+64)[0],CAPACITY+1)
            # Tail jump retains the original seventh integer stack argument.
            memory[4096:4102]=bytes.fromhex('48 8b 44 24 08 c3')
            integers=ctypes.CFUNCTYPE(ctypes.c_uint64,*([ctypes.c_uint64]*7))(address)
            self.assertEqual(integers(1,2,3,4,5,6,987654321),987654321)
        finally:
            memory.close()

    @unittest.skipUnless(platform.machine()=='x86_64','x86-64 native synthetic execution')
    def test_inline_sprite_stub_replays_load_and_records_vtable_without_changing_arguments(self):
        memory=mmap.mmap(-1,400000,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
        address=ctypes.addressof(ctypes.c_char.from_buffer(memory))
        box=address+8192
        try:
            stub=argument_stub(address+1024,address+4096,box,10,
                               prefix=INLINE_SPRITE_DELTA,record_vtable=True)
            memory[1024:1024+len(stub)]=stub
            memory[4096:4097]=b'\xc3'
            # A synthetic stack frame supplies the saved sprite delta. The
            # replacement call enters the stub; the original target returns.
            wrapper=bytes.fromhex('55 48 89 e5 48 81 ec 20 01 00 00 '
                                  'f3 0f 11 85 f4 fe ff ff e8')
            wrapper+=relative(address+1024,address+len(wrapper)+4)
            wrapper+=bytes.fromhex('c9 c3')
            memory[:len(wrapper)]=wrapper
            vtable=ctypes.c_uint64(0x1234567890abcdef)
            ptr=ctypes.addressof(vtable)
            fn=ctypes.CFUNCTYPE(ctypes.c_float,ctypes.c_void_p,ctypes.c_uint64,
                                ctypes.c_float,ctypes.c_float)(address)
            self.assertEqual(fn(ptr,77,0.25,0.5),0.25)
            self.assertEqual(struct.unpack_from('<4Q2f',memory,8192+64),
                             (1,10,ptr,vtable.value,0.25,0.5))
            # The original virtual target may use RSI. Preserve it even when
            # the observation stores the vtable instead of that argument.
            memory[4096:4100]=bytes.fromhex('48 89 f0 c3')
            integer_fn=ctypes.CFUNCTYPE(ctypes.c_uint64,ctypes.c_void_p,
                                        ctypes.c_uint64,ctypes.c_float,
                                        ctypes.c_float)(address)
            self.assertEqual(integer_fn(ptr,77,0.25,0.5),77)
        finally:
            memory.close()

    @unittest.skipUnless(platform.machine()=='x86_64','x86-64 native synthetic execution')
    def test_uv_track_entry_stub_preserves_arguments_and_stack(self):
        memory=mmap.mmap(-1,400000,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
        address=ctypes.addressof(ctypes.c_char.from_buffer(memory));box=address+8192
        try:
            stub=argument_stub(address,address+4096,box,12,prefix=UV_TRACK_ENTRY,record_vtable=True)
            memory[:len(stub)]=stub
            memory[4096:4102]=bytes.fromhex('48 89 f0 41 5f 5d')
            memory[4102:4103]=b'\xc3'
            vtable=ctypes.c_uint64(0xf44cf0);ptr=ctypes.addressof(vtable)
            fn=ctypes.CFUNCTYPE(ctypes.c_uint64,ctypes.c_void_p,ctypes.c_uint64,
                                ctypes.c_uint64,ctypes.c_float)(address)
            self.assertEqual(fn(ptr,77,88,0.25),77)
            self.assertEqual(struct.unpack_from('<4Q',memory,8192+64),(1,12,ptr,vtable.value))
            self.assertEqual(struct.unpack_from('<f',memory,8192+64+32)[0],0.25)
            memory[4096:4103]=bytes.fromhex('41 5f 5d c3 90 90 90')
            float_fn=ctypes.CFUNCTYPE(ctypes.c_float,ctypes.c_void_p,ctypes.c_uint64,
                                      ctypes.c_uint64,ctypes.c_float)(address)
            self.assertEqual(float_fn(ptr,77,88,0.25),0.25)
        finally:
            memory.close()

class TimingProbeReaderTests(unittest.TestCase):
    def box(self):
        from tools.fps_probe_mod import MAILBOX_SIZE
        data=bytearray(MAILBOX_SIZE)
        struct.pack_into('<8s7Q',data,0,MAGIC,1,1,0,1,0,0,0)
        struct.pack_into('<4Q2f',data,64,1,3,42,1,1/60,1.)
        return data

    def test_read_exact_bits_and_cursor(self):
        from tools.fps_probe_read import snapshot
        data=self.box()
        result=snapshot(lambda a,n:data[a:a+n],0)
        self.assertEqual(result['produced'],1)
        self.assertEqual(result['records'][0]['xmm1_bits'],0x3f800000)
        self.assertEqual(snapshot(lambda a,n:data[a:a+n],0,1)['records'],[])

    def test_loss_and_reuse_fail_closed(self):
        from tools.fps_probe_read import snapshot
        for offset,value,reason in ((32,CAPACITY+1,'overrun'),(40,1,'contention'),(64,0,'reuse')):
            data=self.box();struct.pack_into('<Q',data,offset,value)
            with self.assertRaisesRegex(ValueError,reason):snapshot(lambda a,n:data[a:a+n],0)

    def test_opt_in_loss_marker_allows_later_clean_window(self):
        from tools.fps_probe_read import snapshot
        data=self.box();struct.pack_into('<Q',data,40,1)
        first=snapshot(lambda a,n:data[a:a+n],0,allow_loss=True)
        self.assertEqual(first['loss_since_last'],1)
        self.assertEqual(first['dropped'],1)
        later=snapshot(lambda a,n:data[a:a+n],0,first['produced'],first['dropped'],allow_loss=True)
        self.assertEqual(later['loss_since_last'],0)
        self.assertEqual(later['records'],[])

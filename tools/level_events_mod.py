# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact-build, opt-in guest-only lifecycle observation stubs.

Original code, data and imports stay intact except for two checked hook sites.
Generated guest code and packs are private artifacts, never source assets.
"""
import hashlib
import json
from pathlib import Path
import struct

try:
    from . import prepare_native, resolution
except ImportError:
    import prepare_native, resolution

PROFILE = Path(__file__).resolve().parents[1]/'profiles/patches/trap-team-level-events.json'
MAILBOX_MAGIC = b'SKYLEV02'
MAILBOX = struct.Struct('<8s7Q')
RING_CAPACITY = 64
RECORD_SIZE = 256
MAILBOX_SIZE = 64 + RING_CAPACITY*RECORD_SIZE
PAGE = 4096


def relative(target, next_instruction):
    delta = target-next_instruction
    if not -(1<<31) <= delta < (1<<31):
        raise ValueError('level-event branch exceeds rel32 range')
    return struct.pack('<i',delta)


def observer_stub(address, target, counter, after_return=False):
    # No host calls, TLS access, SIMD instructions or argument-register writes.
    # The tail form leaves every stack argument at its original offset. The
    # return form is restricted to the established three-register-argument call.
    code = bytearray()
    if after_return:
        code += b'\x48\x8d\x64\x24\xf8'  # align stack without modifying flags
        code += b'\xe8'+relative(target,address+len(code)+5)
    code += b'\x9c\x50\x48\xb8'+struct.pack('<Q',counter)
    code += b'\xf0\x48\xff\x00\x58\x9d'  # atomic increment, restore RAX/flags
    if after_return:
        code += b'\x48\x8d\x64\x24\x08\xc3'
    else:
        code += b'\xe9'+relative(target,address+len(code)+5)
    return bytes(code)


class _Code:
    """Tiny rel32 label writer for original, bounded observation instructions."""
    def __init__(self):
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    def emit(self, hex_text): self.data += bytes.fromhex(hex_text)
    def label(self, name): self.labels[name] = len(self.data)
    def branch(self, opcode, label):
        self.emit(opcode)
        self.fixups.append((len(self.data), label))
        self.data += bytes(4)

    def finish(self):
        for offset, label in self.fixups:
            self.data[offset:offset+4] = struct.pack('<i', self.labels[label]-offset-4)
        return bytes(self.data)


def named_publisher(mailbox, kind, label_address=0):
    """Publish an immutable name while live; contention drops instead of spinning.

    kind 1: SwitchLevelMessage RSI, UTF-16 name at +16, pool at +24.
    kind 2: selected main-loop integration return, ASCII serialized load label.
    kind 3: selected main-loop load start, UTF-16 RSI argument.
    All integer scratch registers and flags are restored; no host or SIMD calls.
    """
    if kind not in (1,2,3): raise ValueError('unknown lifecycle event kind')
    c = _Code()
    c.emit('9c 50 51 52 41 50 41 51 41 52 41 53')
    c.emit('48 ba'); c.data += struct.pack('<Q',mailbox)
    c.emit('f0 48 ff 42'); c.data.append({1:16,2:24,3:56}[kind])
    c.emit('31 c0 b9 01 00 00 00 f0 0f b1 4a 30')
    c.branch('0f 85','contended')
    c.emit('48 8b 4a 20 48 89 c8 83 e0 3f 48 c1 e0 08 4c 8d 4c 02 40')
    c.emit('49 c7 01 00 00 00 00 49 c7 41 08'); c.data += struct.pack('<I',kind)
    c.emit('49 c7 41 10 00 00 00 00 49 c7 41 18 00 00 00 00')
    if kind == 1:
        c.emit('45 31 c0 48 85 f6'); c.branch('0f 84','source_ready')
        c.emit('4c 8b 46 10 48 8b 46 18 49 89 41 18')
    elif kind == 3:
        c.emit('49 89 f0')
    else:
        c.emit('49 b8'); c.data += struct.pack('<Q',label_address)
    c.label('source_ready')
    c.emit('45 31 db 4d 85 c0'); c.branch('0f 84','terminate')
    c.label('copy')
    c.emit('41 81 fb bf 00 00 00'); c.branch('0f 83','truncated')
    c.emit('47 0f b6 14 18' if kind == 2 else '47 0f b7 14 58')
    c.emit('45 85 d2'); c.branch('0f 84','terminate')
    c.emit('41 83 fa 7f'); c.branch('0f 86','ascii')
    c.emit('49 83 49 10 01 41 ba 3f 00 00 00')
    c.label('ascii')
    c.emit('47 88 54 19 20 41 ff c3'); c.branch('e9','copy')
    c.label('truncated'); c.emit('49 83 49 10 02')
    c.label('terminate')
    c.emit('43 c6 44 19 20 00 48 ff c1 49 89 09 48 89 4a 20 c7 42 30 00 00 00 00')
    c.branch('e9','restore')
    c.label('contended'); c.emit('f0 48 ff 42 28')
    c.label('restore'); c.emit('41 5b 41 5a 41 59 41 58 5a 59 58 9d')
    return c.finish()


def event_stub(address, target, mailbox, kind, label_address=0):
    code = bytearray()
    if kind == 2:
        code += bytes.fromhex('48 8d 64 24 f8')
        code += b'\xe8'+relative(target,address+len(code)+5)
    code += named_publisher(mailbox,kind,label_address)
    if kind == 2: code += bytes.fromhex('48 8d 64 24 08 c3')
    else: code += b'\xe9'+relative(target,address+len(code)+5)
    return bytes(code)


def patch_pack(data, profile, variant, preset=None, graphics_profile=None):
    if hashlib.sha256(data).hexdigest() != profile['pack_sha256'].get(variant):
        raise ValueError('level events refuse an unknown linked pack')
    if preset:
        graphics = graphics_profile or json.loads(resolution.PROFILE.read_text())
        data = resolution.patch_pack(data,preset,variant,graphics)
    header = list(prepare_native.HEADER.unpack_from(data))
    if header[0] != prepare_native.MAGIC or not 0 < header[4] <= 4094:
        raise ValueError('invalid level-event input pack')
    table_end = prepare_native.HEADER.size+header[4]*prepare_native.SEGMENT.size
    segments = [list(prepare_native.SEGMENT.unpack_from(data,prepare_native.HEADER.size+i*40))
                for i in range(header[4])]
    code_address = (header[2]+header[3]+PAGE-1)&~(PAGE-1)
    mailbox_address = code_address+PAGE
    mailbox_span = (MAILBOX_SIZE+PAGE-1)&~(PAGE-1)
    if mailbox_address+mailbox_span-header[2] > prepare_native.MAX_IMAGE:
        raise ValueError('level events exceed supported image span')
    patched = bytearray(data)
    code = bytearray()
    hooks = profile['hooks']
    if len(hooks) != 3 or {h['event'] for h in hooks} != {'switch-request','load-commit-return','load-begin'}:
        raise ValueError('unsupported level-event contract')
    for hook in hooks:
        address = hook['virtual_address']
        expected = bytes.fromhex(hook['expected_hex'])
        locations = [offset+address-start for start,mem,size,flags,offset in segments
                     if flags&1 and start <= address and address+len(expected) <= start+size]
        if len(locations)!=1 or patched[locations[0]:locations[0]+len(expected)] != expected:
            raise ValueError('level-event instruction bytes mismatch')
        # A relocation must not overwrite an installed hook after the pack loads.
        for i in range(header[5]):
            site = prepare_native.RELOCATION.unpack_from(data,table_end+i*32)[0]
            if address < site+8 and site < address+len(expected):
                raise ValueError('relocation overlaps level-event hook')
        stub_address = code_address+len(code)
        if hook['kind']=='subscription-tail' and len(expected)==7 and expected[:3]==b'\x48\x8d\x3d':
            old_target = address+7+struct.unpack('<i',expected[3:])[0]
            replacement = expected[:3]+relative(stub_address,address+7)
            kind = 1
        elif hook['kind']=='call-return-three-register-args' and len(expected)==5 and expected[:1]==b'\xe8':
            old_target = address+5+struct.unpack('<i',expected[1:])[0]
            replacement = b'\xe8'+relative(stub_address,address+5)
            kind = 2
        elif hook['kind']=='call-tail-utf16-name' and len(expected)==5 and expected[:1]==b'\xe8':
            old_target = address+5+struct.unpack('<i',expected[1:])[0]
            replacement = b'\xe8'+relative(stub_address,address+5)
            kind = 3
        else:
            raise ValueError('unsupported level-event hook encoding')
        if old_target != hook['original_target']:
            raise ValueError('level-event original branch target mismatch')
        if not any(flags&1 and start <= old_target < start+size
                   for start,mem,size,flags,offset in segments):
            raise ValueError('level-event handler is outside executable memory')
        code += event_stub(stub_address,old_target,mailbox_address,kind,profile['commit_label_address'])
        patched[locations[0]:locations[0]+len(expected)] = replacement
    if len(code)>PAGE:
        raise ValueError('level-event stubs exceed code page')
    shift = 2*prepare_native.SEGMENT.size
    for record in segments: record[4] += shift
    segments += [[code_address,PAGE,len(code),5,len(data)+shift],
                 [mailbox_address,mailbox_span,MAILBOX_SIZE,6,len(data)+shift+len(code)]]
    header[3] = mailbox_address+mailbox_span-header[2]
    header[4] += 2
    output = bytearray(prepare_native.HEADER.pack(*header))
    for record in segments: output += prepare_native.SEGMENT.pack(*record)
    output += patched[table_end:]+code+MAILBOX.pack(MAILBOX_MAGIC,2,0,0,0,0,0,0)+bytes(MAILBOX_SIZE-MAILBOX.size)
    return bytes(output), {'mailbox_address':mailbox_address,'code_address':code_address,
                          'events':[h['event'] for h in hooks],'status':profile['status'],
                          'mailbox_version':2,'ring_capacity':RING_CAPACITY}


def prepare(pack, session, executable, variant, preset=None, profile_path=None, graphics_profile_path=None):
    profile = json.loads(Path(profile_path or PROFILE).read_text())
    if hashlib.sha256(executable.read_bytes()).hexdigest()!=profile['executable_sha256']:
        raise ValueError('level events refuse an unknown original executable')
    source = (pack/'image.pack').read_bytes()
    graphics = json.loads(Path(graphics_profile_path).read_text()) if graphics_profile_path else None
    patched, metadata = patch_pack(source,profile,variant,preset,graphics)
    output = session/'level-events.pack'
    with output.open('xb') as stream: stream.write(patched)
    metadata.update(source_pack_sha256=hashlib.sha256(source).hexdigest(),
                    output_pack_sha256=hashlib.sha256(patched).hexdigest(),
                    executable_sha256=profile['executable_sha256'])
    return output,metadata

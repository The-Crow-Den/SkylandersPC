# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in, private-pack timing argument observations. No timing values are edited.

A call-site stub records raw scalar arguments and tail-jumps to the original
callee. Exact sprite-load and UV-track-entry instructions may instead be replayed
before returning to their original continuation. It uses no host services,
changes no SIMD state, and drops contended observations instead of waiting.
This is diagnostic overhead, never a benchmark.
"""
import hashlib
import struct
from . import prepare_native as n
from .level_events_mod import _Code, relative
from .game_build import US_UPDATE_SHA256

PAGE = 4096
CAPACITY = 4096
RECORD_SIZE = 64
MAILBOX_SIZE = 64 + CAPACITY * RECORD_SIZE
MAGIC = b'SKYFPS01'


INLINE_SPRITE_DELTA = bytes.fromhex('c5 fa 10 85 f4 fe ff ff')
INLINE_PARTICLE_DISPATCH = bytes.fromhex('4c 89 e6 4c 89 f2')
UV_TRACK_ENTRY = bytes.fromhex('55 48 89 e5 41 57')


def argument_stub(address, target, mailbox, site, *, prefix=b'', record_vtable=False):
    if type(site) is not int or not 1 <= site <= 32:
        raise ValueError('invalid timing site ID')
    c = _Code()
    if prefix:
        if prefix not in (INLINE_SPRITE_DELTA, INLINE_PARTICLE_DISPATCH, UV_TRACK_ENTRY):
            raise ValueError('unsupported timing probe inline instruction')
        c.data += prefix
    # Save every integer register written below and all flags. MOVD reads XMM
    # bits without changing XMM, MXCSR, upper vector lanes or floating exceptions.
    c.emit('9c 50 51 52 41 50 41 51')
    c.emit('48 ba'); c.data += struct.pack('<Q', mailbox)
    c.emit('f0 48 ff 42 10')  # total attempts
    c.emit('31 c0 b9 01 00 00 00 f0 0f b1 4a 30')
    c.branch('0f 85', 'drop')
    c.emit('48 8b 4a 20 48 89 c8 25 ff 0f 00 00 48 c1 e0 06 4c 8d 44 02 40')
    c.emit('49 c7 00 00 00 00 00')  # invalidate before replacing ring slot
    c.emit('49 c7 40 08'); c.data += struct.pack('<I', site)
    c.emit('49 89 78 10')  # RDI object pointer
    if record_vtable:
        c.emit('48 8b 07 49 89 40 18')  # saved RAX scratch; valid virtual object
    else:
        c.emit('49 89 70 18')  # original RSI argument
    c.emit('66 41 0f 7e c1 45 89 48 20')  # XMM0 low bits
    c.emit('66 41 0f 7e c9 45 89 48 24')  # XMM1 low bits
    c.emit('48 ff c1 49 89 08 48 89 4a 20 c7 42 30 00 00 00 00')
    c.branch('e9', 'restore')
    c.label('drop'); c.emit('f0 48 ff 42 28')
    c.label('restore'); c.emit('41 59 41 58 5a 59 58 9d')
    code = c.finish()
    return code + b'\xe9' + relative(target, address + len(code) + 5)


def patch_pack(data, profile):
    if profile.get('executable_sha256') != US_UPDATE_SHA256:
        raise ValueError('timing probe requires exact US 01.01 profile')
    if hashlib.sha256(data).hexdigest() != profile.get('pack_sha256'):
        raise ValueError('timing probe refuses unknown pack')
    if len(data) < n.HEADER.size:
        raise ValueError('truncated timing probe pack')
    header = list(n.HEADER.unpack_from(data))
    if header[0] != n.MAGIC or not 0 < header[4] <= 4094:
        raise ValueError('invalid timing probe pack')
    table_end = n.HEADER.size + header[4] * n.SEGMENT.size
    reloc_end = table_end + header[5] * n.RELOCATION.size
    if reloc_end > len(data):
        raise ValueError('truncated timing probe tables')
    segments = [list(n.SEGMENT.unpack_from(data, n.HEADER.size + i*n.SEGMENT.size))
                for i in range(header[4])]
    for start, mem, size, flags, offset in segments:
        if size > mem or offset < reloc_end or offset + size > len(data):
            raise ValueError('invalid timing probe segment')
        if start < header[2] or start + mem > header[2] + header[3]:
            raise ValueError('timing probe segment outside image')
    hooks = profile.get('hooks')
    if not isinstance(hooks, list) or not 1 <= len(hooks) <= 16:
        raise ValueError('timing probe requires 1..16 hooks')
    code_address = (header[2] + header[3] + PAGE - 1) & -PAGE
    mailbox = code_address + PAGE
    span = (MAILBOX_SIZE + PAGE - 1) & -PAGE
    if mailbox + span - header[2] > n.MAX_IMAGE:
        raise ValueError('timing probe exceeds image limit')
    patched, code, seen, ids = bytearray(data), bytearray(), {}, set()
    for hook in hooks:
        address, site = hook['virtual_address'], hook['site']
        expected = bytes.fromhex(hook['expected_hex'])
        kind = hook.get('kind','direct-call')
        if kind not in ('direct-call','inline-before-virtual','function-entry'):
            raise ValueError('unsupported timing probe hook kind')
        width = len(expected)
        if address in seen or site in ids:
            raise ValueError('duplicate timing probe site')
        if any(address < previous+size and previous < address+width
               for previous,size in seen.items()):
            raise ValueError('overlapping timing probe sites')
        seen[address]=width; ids.add(site)
        if kind == 'direct-call':
            if width != 5 or expected[0] != 0xe8:
                raise ValueError('timing probe direct call bytes invalid')
            target = address + 5 + struct.unpack('<i', expected[1:])[0]
            if target != hook['original_target']:
                raise ValueError('timing probe target mismatch')
        else:
            accepted = (INLINE_SPRITE_DELTA, INLINE_PARTICLE_DISPATCH) if kind=='inline-before-virtual' else (UV_TRACK_ENTRY,)
            if expected not in accepted or hook.get('original_target') is not None:
                raise ValueError('timing probe inline instruction mismatch')
            target = address + width
        if not any(f&1 and s <= target < s+z for s,m,z,f,o in segments):
            raise ValueError('timing probe target outside executable memory')
        locations = [o + address-s for s,m,z,f,o in segments
                     if f&1 and s <= address and address+width <= s+z]
        if len(locations) != 1 or data[locations[0]:locations[0]+width] != expected:
            raise ValueError('timing probe expected bytes mismatch')
        for i in range(header[5]):
            relocation = n.RELOCATION.unpack_from(data, table_end + i*n.RELOCATION.size)[0]
            if address < relocation+8 and relocation < address+width:
                raise ValueError('timing probe overlaps relocation')
        stub_address = code_address + len(code)
        code += argument_stub(stub_address, target, mailbox, site,
                              prefix=expected if kind!='direct-call' else b'',
                              record_vtable=kind!='direct-call')
        opcode = b'\xe8' if kind=='direct-call' else b'\xe9'
        patched[locations[0]:locations[0]+width] = (opcode + relative(stub_address,address+5)
                                                    + b'\x90'*(width-5))
    if len(code) > PAGE:
        raise ValueError('timing probe code exceeds page')
    shift = 2*n.SEGMENT.size
    for record in segments:
        record[4] += shift
    segments += [[code_address, PAGE, len(code), 5, len(data)+shift],
                 [mailbox, span, MAILBOX_SIZE, 6, len(data)+shift+len(code)]]
    header[3] = mailbox + span - header[2]; header[4] += 2
    output = bytearray(n.HEADER.pack(*header))
    for record in segments:
        output += n.SEGMENT.pack(*record)
    output += patched[table_end:] + code
    output += struct.pack('<8s7Q', MAGIC, 1, 0, 0, 0, 0, 0, 0)
    output += bytes(MAILBOX_SIZE-64)
    return bytes(output), dict(mailbox_address=mailbox, code_address=code_address,
                              capacity=CAPACITY, record_size=RECORD_SIZE,
                              diagnostic_only=True, timing_modified=False)


def prepare(executable, source, profile, output):
    """Write a separate diagnostic pack only after source executable identity checks."""
    if hashlib.sha256(executable.read_bytes()).hexdigest()!=US_UPDATE_SHA256:
        raise ValueError('timing probe refuses foreign source executable')
    data=source.read_bytes()
    result,metadata=patch_pack(data,profile)
    with output.open('xb') as stream:
        stream.write(result)
    metadata.update(executable_sha256=US_UPDATE_SHA256,
                    input_pack_sha256=hashlib.sha256(data).hexdigest(),
                    output_pack_sha256=hashlib.sha256(result).hexdigest())
    return metadata


def main():
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable',type=Path)
    parser.add_argument('source_pack',type=Path)
    parser.add_argument('profile',type=Path)
    parser.add_argument('output_pack',type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare(args.executable,args.source_pack,
                             json.loads(args.profile.read_text()),args.output_pack),indent=2))


if __name__=='__main__':
    main()

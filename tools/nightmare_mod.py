# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact-build difficulty-menu asset patch, prepared in a private session tree.

IGA format facts were checked against the public igArchiveExtractor project.
This bounded recipe rewrites one existing raw-LZMA allocation; no archive tool,
download or proprietary replacement asset is required at launch.
"""
import hashlib
import json
import lzma
from pathlib import Path
import struct

PROFILE=Path(__file__).resolve().parents[1]/'profiles/patches/trap-team-nightmare.json'


def recipe(profile):
    """The same edit as an asset_mod recipe, so it composes with other edits of
    level/title.bld (such as the controller glyph pack) in one preparation."""
    offset,allocation=profile['chunk_offset'],profile['allocation_size']
    chunk=dict(offset=offset,allocation=allocation,decoded_size=profile['decoded_size'],
               decoded_sha256=profile['decoded_sha256'],encoding='raw-lzma',
               encoded_size=profile['compressed_payload_size'],properties_hex=profile['lzma_properties_hex'],
               edits=[dict(offset=profile['patch_offset_in_chunk'],expected_hex=profile['expected_hex'],
                           replacement_hex=profile['replacement_hex'])])
    if offset%2048==0 and allocation%2048==0:chunk['alignment']=2048
    return dict(schema_version=2,executable_sha256=profile['executable_sha256'],title_id=profile.get('title_id'),
                app_version=profile.get('app_version'),
                assets=[dict(asset=profile['asset'],source_sha256=profile['asset_sha256'],chunks=[chunk])])


def patch_asset(data, profile):
    if hashlib.sha256(data).hexdigest()!=profile['asset_sha256']:
        raise ValueError('Nightmare mod refuses an unknown title asset')
    if data[:8]!=b'IGA\x1a\x0b\0\0\0':
        raise ValueError('unsupported Nightmare archive version')
    offset,allocation=profile['chunk_offset'],profile['allocation_size']
    if offset<0 or allocation<7 or offset+allocation>len(data):
        raise ValueError('Nightmare chunk outside asset')
    size=struct.unpack_from('<H',data,offset)[0]
    props=data[offset+2:offset+7]
    if size!=profile['compressed_payload_size'] or props.hex()!=profile['lzma_properties_hex'] or size+7>allocation:
        raise ValueError('Nightmare compression recipe mismatch')
    dictionary=struct.unpack_from('<I',props,1)[0]
    if props[0]!=0x5d or not 4096<=dictionary<=64*1024*1024:
        raise ValueError('unsupported Nightmare LZMA properties')
    filters=[dict(id=lzma.FILTER_LZMA1,dict_size=dictionary,lc=3,lp=0,pb=2)]
    def decode(payload):
        decoder=lzma.LZMADecompressor(format=lzma.FORMAT_RAW,filters=filters)
        return decoder.decompress(payload,max_length=profile['decoded_size']+1)
    plain=decode(data[offset+7:offset+7+size])
    if len(plain)!=profile['decoded_size'] or hashlib.sha256(plain).hexdigest()!=profile['decoded_sha256']:
        raise ValueError('Nightmare decoded chunk mismatch')
    at=profile['patch_offset_in_chunk']
    before,after=bytes.fromhex(profile['expected_hex']),bytes.fromhex(profile['replacement_hex'])
    if not before or len(before)!=len(after) or at<0 or at+len(before)>len(plain) or plain[at:at+len(before)]!=before:
        raise ValueError('Nightmare eligibility bytes mismatch')
    modified=plain[:at]+after+plain[at+len(before):]
    encoding=[dict(filters[0],mode=lzma.MODE_NORMAL,nice_len=64,mf=lzma.MF_BT4)]
    compressed=lzma.compress(modified,format=lzma.FORMAT_RAW,filters=encoding)
    if len(compressed)>65535 or len(compressed)+7>allocation:
        raise ValueError('Nightmare patched chunk does not fit original allocation')
    if decode(compressed)!=modified:
        raise ValueError('Nightmare recompression failed verification')
    block=struct.pack('<H',len(compressed))+props+compressed
    block+=bytes(allocation-len(block))
    result=data[:offset]+block+data[offset+allocation:]
    return result,{'source_asset_sha256':profile['asset_sha256'],
                   'output_asset_sha256':hashlib.sha256(result).hexdigest(),
                   'decoded_changed_bytes':sum(a!=b for a,b in zip(plain,modified)),
                   'status':profile['status'],'asset':profile['asset']}


def prepare(original_game, session_game, session, profile_path=None):
    profile=json.loads(Path(profile_path or PROFILE).read_text())
    if hashlib.sha256((original_game/'eboot.bin').read_bytes()).hexdigest()!=profile['executable_sha256']:
        raise ValueError('Nightmare mod refuses an unknown original executable')
    source=original_game/profile['asset']
    data=source.read_bytes()
    patched,metadata=patch_asset(data,profile)
    if session_game.resolve()!=(session/'game').resolve() or session_game.resolve()==original_game.resolve():
        raise ValueError('Nightmare mod requires a private session game tree')
    destination=session_game/profile['asset']
    if destination.is_symlink() or destination.resolve()!=session_game.resolve()/profile['asset']:
        raise ValueError('Nightmare mod refuses a redirected destination')
    if hashlib.sha256(destination.read_bytes()).hexdigest()!=profile['asset_sha256']:
        raise ValueError('Nightmare mod refuses to overwrite another title modification')
    # Session files normally hard-link immutable originals. Break this link first.
    destination.unlink()
    with destination.open('xb') as stream:stream.write(patched)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=profile['asset_sha256']:
        raise ValueError('original title asset changed during mod preparation')
    return metadata

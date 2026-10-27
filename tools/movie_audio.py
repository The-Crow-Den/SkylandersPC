# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact-build Bink movie localization; encoded video/audio are never re-encoded.

Container layout corroborated against FFmpeg libavformat/bink.c. This module
implements only the supplied KB2i layout, refusing other formats/identities.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import struct
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    if not path.is_file() or path.stat().st_size>512*1024*1024:
        raise ValueError('invalid or oversized movie file')
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def _u32(data, offset):
    if offset < 0 or offset+4 > len(data):
        raise ValueError('movie header/packet outside file')
    return struct.unpack_from('<I',data,offset)[0]


def _layout(data):
    if len(data)<48 or data[:4]!=b'KB2i' or _u32(data,4)+8!=len(data):
        raise ValueError('unsupported movie container')
    frames, count = _u32(data,8), _u32(data,40)
    if not 0<frames<=1000000 or not 0<count<=64:
        raise ValueError('invalid movie frame/track count')
    index=48+count*12
    if index+4*(frames+1)>len(data):
        raise ValueError('movie index outside file')
    offsets=struct.unpack_from('<'+str(frames+1)+'I',data,index)
    if (offsets[0]&~1)<index+4*(frames+1) or offsets[-1]&~1!=len(data):
        raise ValueError('invalid movie index bounds')
    tracks=[_u32(data,48+count*8+i*4) for i in range(count)]
    if len(set(tracks))!=count:
        raise ValueError('duplicate movie track identity')
    records=[]
    for frame in range(frames):
        begin,end=offsets[frame]&~1,offsets[frame+1]&~1
        if not begin<end<=len(data):
            raise ValueError('nonmonotonic movie index')
        position=begin;audio=[]
        for track in range(count):
            length=_u32(data,position)
            if position+4+length>end:
                raise ValueError('movie audio packet exceeds frame')
            audio.append((position,position+4+length));position+=4+length
        records.append((audio,(position,end),offsets[frame]&1))
    return tracks,records,index,offsets


def rewrite(data, keep):
    tracks,records,index,offsets=_layout(data)
    if not keep or len(set(keep))!=len(keep) or not set(keep).issubset(tracks):
        raise ValueError('requested movie track missing or duplicated')
    selected=[i for i,track in enumerate(tracks) if track in keep]
    count=len(tracks)
    output=bytearray(data[:48]);struct.pack_into('<I',output,40,len(selected))
    for group in range(3):
        for i in selected:output.extend(data[48+group*count*4+i*4:52+group*count*4+i*4])
    table=len(output);output.extend(bytes(4*(len(records)+1)))
    output.extend(data[index+4*(len(records)+1):offsets[0]&~1])
    view=memoryview(data);new_offsets=[];largest=0
    for audio,video,key in records:
        if len(output)%2:
            raise ValueError('unaligned movie frame; refusing to invent padding')
        start=len(output);new_offsets.append(start|key)
        for i in selected:
            a,b=audio[i];output.extend(view[a:b])
        a,b=video;output.extend(view[a:b]);largest=max(largest,len(output)-start)
    if len(output)%2 or len(output)>=1<<32:
        raise ValueError('invalid rewritten movie size')
    new_offsets.append(len(output))
    struct.pack_into('<'+str(len(new_offsets))+'I',output,table,*new_offsets)
    struct.pack_into('<I',output,4,len(output)-8);struct.pack_into('<I',output,12,largest)
    # Verify every retained encoded packet, video payload, keyframe and count.
    after_tracks,after,_,_=_layout(output)
    if after_tracks!=[tracks[i] for i in selected] or len(after)!=len(records):
        raise ValueError('movie rewrite verification failed')
    result=memoryview(output)
    for (audio,video,key),(new_audio,new_video,new_key) in zip(records,after):
        if key!=new_key or view[slice(*video)]!=result[slice(*new_video)]:
            raise ValueError('movie rewrite changed video payload')
        for old_index,new_range in zip(selected,new_audio):
            if view[slice(*audio[old_index])]!=result[slice(*new_range)]:
                raise ValueError('movie rewrite changed retained audio')
    return bytes(output)


def prepare(original_game, session_game, session, profile_path):
    try:from .file_integrity import VerifiedDigests
    except ImportError:from file_integrity import VerifiedDigests
    checked_digest=VerifiedDigests(file_digest)
    profile=json.loads(Path(profile_path).read_text())
    if (type(profile.get('schema_version')) is not int or profile['schema_version']!=1 or
            profile.get('keep_tracks')!=[7,0] or profile.get('language')!='English'):
        raise ValueError('unsupported movie localization profile')
    if checked_digest(original_game/'eboot.bin')!=profile['executable_sha256']:
        raise ValueError('movie localization refuses unknown executable')
    if session_game.resolve()!=(session/'game').resolve() or session_game.resolve()==original_game.resolve():
        raise ValueError('movie localization requires a private session tree')
    if not isinstance(profile.get('assets'),list) or not 0<len(profile['assets'])<=128:
        raise ValueError('invalid movie recipe count')
    report=[]
    # One movie in memory at a time; cached outputs are immutable session inputs.
    cache=Path(profile_path).resolve().parents[2]/'out/movie-audio-cache'
    cache.mkdir(parents=True,exist_ok=True)
    if cache.is_symlink() or cache.resolve()!=cache:
        raise ValueError('redirected movie cache')
    for recipe in profile['assets']:
        relative=Path(recipe['asset'])
        if relative.is_absolute() or len(relative.parts)!=2 or relative.parts[0]!='movies' or relative.suffix!='.mov' or '..' in relative.parts:
            raise ValueError('invalid movie asset path')
        if any(not isinstance(recipe.get(key),str) or not re.fullmatch(r'[0-9a-f]{64}',recipe[key]) for key in ('source_sha256','output_sha256')):
            raise ValueError('invalid movie digest recipe')
        source=original_game/relative;target=session_game/relative
        if source.is_symlink() or source.resolve()!=original_game.resolve()/relative or target.is_symlink() or target.resolve()!=session_game.resolve()/relative:
            raise ValueError('redirected movie asset')
        if source.stat().st_size>512*1024*1024:
            raise ValueError('movie exceeds bounded preparation size')
        if checked_digest(source)!=recipe['source_sha256'] or checked_digest(target)!=recipe['source_sha256']:
            raise ValueError('movie localization refuses unexpected source/session asset')
        cached=cache/(recipe['output_sha256']+'.mov')
        if cached.is_symlink():raise ValueError('redirected cached movie')
        if cached.exists():
            if checked_digest(cached)!=recipe['output_sha256']:
                raise ValueError('cached movie failed integrity check')
        else:
            data=source.read_bytes()
            if digest(data)!=recipe['source_sha256']:raise ValueError('movie changed during preparation')
            if _layout(data)[0]!=recipe['source_tracks']:
                raise ValueError('movie source track layout mismatch')
            modified=rewrite(data,profile['keep_tracks'])
            if digest(modified)!=recipe['output_sha256']:
                raise ValueError('movie localization output mismatch')
            with tempfile.NamedTemporaryFile(dir=cache,delete=False) as stream:
                temporary=Path(stream.name);stream.write(modified)
            try:
                os.link(temporary,cached)  # Never replace another writer's output.
            except FileExistsError:
                if checked_digest(cached)!=recipe['output_sha256']:raise ValueError('conflicting cached movie')
            finally:
                temporary.unlink(missing_ok=True)
            del modified,data
        if checked_digest(source)!=recipe['source_sha256']:
            raise ValueError('movie changed during preparation')
        # Replace only our session link. The dump and cached output are unchanged.
        with tempfile.TemporaryDirectory(prefix='.movie-link-',dir=target.parent) as directory:
            temporary=Path(directory)/'localized.mov'
            os.link(cached,temporary)
            os.replace(temporary,target)
        report.append({'asset':str(relative),'source_sha256':recipe['source_sha256'],'output_sha256':recipe['output_sha256']})
    return {'language':'English','narration_track':7,'shared_track':0,'video_reencoded':False,'assets':report}

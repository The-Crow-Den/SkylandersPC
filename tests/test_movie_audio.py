# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import struct
import tempfile
import unittest
from tools import movie_audio


def movie():
    header=bytearray(48);header[:4]=b'KB2i'
    struct.pack_into('<I',header,8,2);struct.pack_into('<I',header,40,3)
    header+=struct.pack('<3I',8,8,8)+struct.pack('<6H',48000,0x5000,48000,0x5000,48000,0x7000)+struct.pack('<3I',1,7,0)
    index=len(header);header+=bytes(12);offsets=[]
    for frame in range(2):
        offsets.append(len(header)|(frame==0))
        for track in range(3):header+=struct.pack('<I',6)+bytes([frame,track])*3
        header+=bytes([0x90+frame])*12
    offsets.append(len(header));struct.pack_into('<3I',header,index,*offsets)
    struct.pack_into('<I',header,4,len(header)-8)
    return bytes(header)


class MovieAudioTests(unittest.TestCase):
    def test_localization_preserves_video_and_selected_encoded_packets(self):
        data=movie();after=movie_audio.rewrite(data,[7,0])
        tracks,frames,_,_=movie_audio._layout(after)
        self.assertEqual(tracks,[7,0]);self.assertEqual(len(frames),2)
        old=movie_audio._layout(data)[1]
        for (audio,video,key),(new_audio,new_video,new_key) in zip(old,frames):
            self.assertEqual(data[slice(*video)],after[slice(*new_video)])
            self.assertEqual(key,new_key)
            self.assertEqual([data[slice(*audio[i])] for i in (1,2)],[after[slice(*p)] for p in new_audio])

    def test_invalid_tracks_indices_and_packets_fail_closed(self):
        data=movie()
        for keep in ([],[20],[7,7]):
            with self.assertRaises(ValueError):movie_audio.rewrite(data,keep)
        for offset,value in ((4,1),(40,65),(84,0),(96,0xffffffff)):
            broken=bytearray(data);struct.pack_into('<I',broken,offset,value)
            with self.assertRaises(ValueError):movie_audio.rewrite(broken,[7,0])

    def test_private_preparation_cache_and_source_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'source';session=root/'out/session';target=session/'game'
            (source/'movies').mkdir(parents=True);(target/'movies').mkdir(parents=True)
            data=movie();after=movie_audio.rewrite(data,[7,0])
            (source/'eboot.bin').write_bytes(b'executable')
            (source/'movies/test.mov').write_bytes(data);(target/'movies/test.mov').write_bytes(data)
            profile=root/'profiles/patches/audio.json';profile.parent.mkdir(parents=True)
            recipe=dict(schema_version=1,language='English',keep_tracks=[7,0],executable_sha256=movie_audio.digest(b'executable'),assets=[dict(asset='movies/test.mov',source_sha256=movie_audio.digest(data),output_sha256=movie_audio.digest(after),source_tracks=[1,7,0])])
            profile.write_text(json.dumps(recipe))
            report=movie_audio.prepare(source,target,session,profile)
            self.assertEqual(report['narration_track'],7)
            self.assertEqual((source/'movies/test.mov').read_bytes(),data)
            self.assertEqual((target/'movies/test.mov').read_bytes(),after)
            (target/'movies/test.mov').unlink();(target/'movies/test.mov').write_bytes(data)
            cache=root/'out/movie-audio-cache'/(movie_audio.digest(after)+'.mov');cache.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):movie_audio.prepare(source,target,session,profile)
            self.assertEqual((target/'movies/test.mov').read_bytes(),data)
            with self.assertRaises(ValueError):movie_audio.prepare(source,source,session,profile)

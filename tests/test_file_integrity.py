# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import hashlib,os,tempfile,unittest
from tools.file_integrity import VerifiedDigests

class VerifiedDigestsTests(unittest.TestCase):
    def test_hard_links_share_work_but_later_operations_hash_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';alias=root/'alias';source.write_bytes(b'one');os.link(source,alias);reads=[]
            def reader(path):reads.append(path);return hashlib.sha256(path.read_bytes()).hexdigest()
            verify=VerifiedDigests(reader);self.assertEqual(verify(source),verify(alias));self.assertEqual(len(reads),1)
            self.assertEqual(VerifiedDigests(reader)(source),verify(source));self.assertEqual(len(reads),2)
            before=source.stat();source.write_bytes(b'two');os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
            self.assertEqual(verify(alias),hashlib.sha256(b'two').hexdigest());self.assertEqual(len(reads),3)
    def test_mutation_during_hash_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source';path.write_bytes(b'one')
            def changing_reader(file):
                digest=hashlib.sha256(file.read_bytes()).hexdigest();file.write_bytes(b'two');return digest
            with self.assertRaisesRegex(ValueError,'changed'):VerifiedDigests(changing_reader)(path)
            link=Path(tmp)/'link';link.symlink_to(path)
            with self.assertRaisesRegex(ValueError,'regular'):VerifiedDigests(lambda file:'unused')(link)

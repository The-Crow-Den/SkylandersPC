# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from tools import release_audit as release


class ReleaseAuditTests(unittest.TestCase):
    def fixture(self,root):
        withheld='profiles/patches/private.json'
        policy=dict(schema_version=1,project_license='GPL-3.0-or-later',withheld={withheld:'private bytes'},
            required=['LICENSE','LICENSES/dependencies.json','LICENSES/bbport-source.json','release-policy.json'],binary_release_blockers=['binary source unresolved'])
        files={'LICENSE':b'GPL license text fixture\n','tools/public.py':b'# SPDX-License-Identifier: GPL-3.0-or-later\nprint(1)\n',
               'native/dependency-patches/canonical.patch':b'patch fixture\n',withheld:b'private game data'}
        notice='LICENSES/third-party/example.txt';files[notice]=b'upstream notice\n'
        files['LICENSES/dependencies.json']=json.dumps(dict(components=[dict(notice=notice,notice_sha256=hashlib.sha256(files[notice]).hexdigest())])).encode()
        files['LICENSES/bbport-source.json']=json.dumps(dict(patch='native/dependency-patches/canonical.patch',patch_sha256=hashlib.sha256(files['native/dependency-patches/canonical.patch']).hexdigest())).encode()
        files['release-policy.json']=json.dumps(policy).encode()
        for name,data in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        return policy

    def test_export_excludes_private_data_is_deterministic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();policy=self.fixture(root)
            (root/'Game').mkdir();(root/'Game/eboot.bin').write_bytes(b'private executable')
            names=release.candidates(root,policy);self.assertNotIn('profiles/patches/private.json',names)
            result=release.audit(root,names);self.assertTrue(result['ok'],result['errors']);self.assertFalse(result['binary_release_ready'])
            first=release.export_source(root,result,root/'first.tar.gz');second=release.export_source(root,result,root/'second.tar.gz')
            self.assertEqual(first.read_bytes(),second.read_bytes())
            with tarfile.open(first) as archive:
                self.assertNotIn('SkylandersPS4/profiles/patches/private.json',archive.getnames())
                self.assertIn('SkylandersPS4/LICENSE',archive.getnames());self.assertIn('SkylandersPS4/SOURCE_MANIFEST.json',archive.getnames())
            with self.assertRaises(ValueError):release.export_source(root,result,first)
            self.assertEqual((root/'Game/eboot.bin').read_bytes(),b'private executable')

    def test_offline_overlay_sources_are_exported_and_still_inspected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();policy=self.fixture(root)
            files={'tools/pc_menu/index.html':b'<!-- SPDX-License-Identifier: GPL-3.0-or-later -->\n<html></html>',
                   'tools/pc_menu/menu.css':b'/* SPDX-License-Identifier: GPL-3.0-or-later */\nbody{}',
                   'tools/pc_menu/menu.js':b'// SPDX-License-Identifier: GPL-3.0-or-later\nvoid 0;',
                   'tools/pc_menu/vendor.js':b'// SPDX-License-Identifier: ISC AND MIT\nvoid 0;'}
            for name,data in files.items():
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
            names=release.candidates(root,policy)
            for name in files:self.assertIn(name,names)
            result=release.audit(root,names);self.assertTrue(result['ok'],result['errors'])
            with tarfile.open(release.export_source(root,result,root/'overlay.tar.gz')) as archive:
                for name,data in files.items():self.assertEqual(archive.extractfile('SkylandersPS4/'+name).read(),data)
            for extension in ('html','css','js'):
                name='tools/unsafe.'+extension
                self.assertTrue(release.inspect(name,b'no license',policy))
                embedded=b'// SPDX-License-Identifier: GPL-3.0-or-later\ndata:image/png;base64,'+b'A'*300
                self.assertTrue(release.inspect(name,embedded,policy))

    def test_forced_private_paths_renamed_binaries_and_bulk_literals_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();policy=self.fixture(root)
            for name,data in [('Game/eboot.bin',b'private'),('profiles/patches/private.json',b'{}'),
                              ('tools/disguised.py',b'\x7fELF executable'),('docs/fake.md',b'\x89PNG image'),
                              ('profiles/bulk.json',json.dumps(dict(expected_hex='ab'*300)).encode())]:
                self.assertTrue(release.inspect(name,data,policy),name)
            text=('-----BEGIN '+'PRIVATE KEY-----\n'+'private fixture\n').encode()
            self.assertTrue(release.inspect('docs/key.md',text,policy))
            self.assertTrue(release.inspect('tools/no_license.py',b'print(1)',policy))

    def test_symlinks_tampered_notices_and_post_audit_mutations_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();policy=self.fixture(root);names=release.candidates(root,policy)
            result=release.audit(root,names);self.assertTrue(result['ok'])
            (root/'tools/public.py').write_bytes(b'# SPDX-License-Identifier: GPL-3.0-or-later\nchanged\n')
            with self.assertRaises(ValueError):release.export_source(root,result,root/'bad.tar.gz')
            (root/'LICENSES/third-party/example.txt').write_text('changed notice')
            self.assertFalse(release.audit(root,names)['ok'])
            (root/'tools/link.py').symlink_to(root/'tools/public.py')
            self.assertFalse(release.audit(root,release.candidates(root,policy))['ok'])

    def test_index_audit_reads_staged_bytes_instead_of_clean_working_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();self.fixture(root)
            subprocess.run(['git','init','-q'],cwd=root,check=True)
            file=root/'tools/public.py';file.write_bytes(b'\x7fELF private binary')
            subprocess.run(['git','add','tools/public.py'],cwd=root,check=True)
            file.write_bytes(b'# SPDX-License-Identifier: GPL-3.0-or-later\nprint(1)\n')
            names,loader=release.git_selection(root,True)
            self.assertTrue(any('binary' in error for error in release.audit(root,names,loader)['errors']))

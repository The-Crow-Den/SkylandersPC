# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import tempfile
import unittest
from tools import save_backup


class SaveBackupTests(unittest.TestCase):
    def test_snapshots_deduplicate_rotate_and_never_change_current_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'saves';title=source/'CUSA00626';title.mkdir(parents=True)
            backups=root/'backups';slot=title/'Slot1';slot.write_bytes(b'progress 1')
            first=save_backup.snapshot(source,'CUSA00626',backup_root=backups,keep=2)
            self.assertEqual(first['status'],'created')
            self.assertEqual(save_backup.snapshot(source,'CUSA00626',backup_root=backups)['status'],'unchanged')
            for number in (2,3):
                slot.write_bytes(f'progress {number}'.encode())
                save_backup.snapshot(source,'CUSA00626',backup_root=backups,keep=2)
            managed=save_backup.snapshots(source,'CUSA00626',backups)
            self.assertEqual(len(managed),2)
            self.assertFalse(Path(first['path']).exists())
            self.assertEqual(slot.read_bytes(),b'progress 3')
            for path,_ in managed:save_backup.verify(path,'CUSA00626')

    def test_corrupt_or_user_modified_backups_are_retained_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'saves';title=source/'CUSA00626';title.mkdir(parents=True)
            backups=root/'backups';(title/'Slot1').write_bytes(b'progress')
            first=Path(save_backup.snapshot(source,'CUSA00626',backup_root=backups)['path'])
            (first/'notes.txt').write_text('keep this recovery point')
            with self.assertRaises(ValueError):save_backup.verify(first,'CUSA00626')
            second=save_backup.snapshot(source,'CUSA00626',backup_root=backups,keep=1)
            self.assertEqual(second['status'],'created');self.assertTrue(first.exists())
            (Path(second['path'])/'files/Slot1').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):save_backup.verify(Path(second['path']),'CUSA00626')
            self.assertEqual((title/'Slot1').read_bytes(),b'progress')

    def test_profiles_are_separate_and_links_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();backups=root/'backups'
            for name in ('main','isolated'):
                title=root/name/'CUSA00626';title.mkdir(parents=True);(title/'Slot1').write_text(name)
                save_backup.snapshot(root/name,'CUSA00626',backup_root=backups,keep=1)
            self.assertEqual(len(save_backup.snapshots(root/'main','CUSA00626',backups)),1)
            self.assertEqual(len(save_backup.snapshots(root/'isolated','CUSA00626',backups)),1)
            (root/'main/CUSA00626/Slot1').unlink();(root/'main/CUSA00626/Slot1').symlink_to(root/'isolated/CUSA00626/Slot1')
            with self.assertRaises(ValueError):save_backup.snapshot(root/'main','CUSA00626',backup_root=backups)
            self.assertIsNone(save_backup.snapshot(root/'missing','CUSA00626',backup_root=backups))

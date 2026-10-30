"""Primitive di apply su POSIX: inserimento esclusivo, sostituzione con backup, volumi di rete."""
import _shortpath  # noqa: F401
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from kit.dashboard import ontology_apply
from kit.dashboard.contracts import ContractError


@unittest.skipIf(os.name == 'nt', 'Percorso POSIX')
class Posix(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_move_new_refuses_a_target_recreated_by_an_external_writer(self):
        staged, target = self.root / 'staged', self.root / 'target'
        staged.write_bytes(b'nuovo')
        target.write_bytes(b'esterno')
        with self.assertRaises(ontology_apply.ContractError) as caught:
            ontology_apply._move_new(staged, target)
        self.assertEqual(caught.exception.code, 'recovery_conflict')
        self.assertEqual(target.read_bytes(), b'esterno')
        self.assertEqual(staged.read_bytes(), b'nuovo')

    def test_move_new_moves_the_staged_file(self):
        staged, target = self.root / 'staged', self.root / 'target'
        staged.write_bytes(b'nuovo')
        ontology_apply._move_new(staged, target)
        self.assertEqual(target.read_bytes(), b'nuovo')
        self.assertFalse(staged.exists())

    def test_move_new_without_hard_links_falls_back_to_rename_only_when_target_is_absent(self):
        staged, target = self.root / 'staged', self.root / 'target'
        staged.write_bytes(b'nuovo')
        with mock.patch('os.link', side_effect=OSError(ontology_apply.errno.EPERM, 'no link')):
            ontology_apply._move_new(staged, target)
        self.assertEqual(target.read_bytes(), b'nuovo')

    def test_replace_keeps_the_displaced_bytes_in_the_backup(self):
        target, staged, backup = self.root / 'nota.md', self.root / 'staged', self.root / 'displaced'
        target.write_bytes(b'vecchio')
        staged.write_bytes(b'nuovo')
        ontology_apply._replace(target, staged, backup)
        self.assertEqual((target.read_bytes(), backup.read_bytes()), (b'nuovo', b'vecchio'))
        self.assertFalse(staged.exists())

    def test_network_filesystems_are_refused_and_local_ones_accepted(self):
        for kind in ('nfs4', 'cifs', 'fuse.sshfs'):
            with self.subTest(kind=kind), mock.patch.object(ontology_apply, '_filesystem', return_value=kind):
                with self.assertRaises(ContractError) as caught:
                    ontology_apply._local_volume(self.root)
                self.assertEqual(caught.exception.code, 'apply_platform_unavailable')
        for kind in ('ext4', 'overlay', 'tmpfs', None):
            with self.subTest(kind=kind), mock.patch.object(ontology_apply, '_filesystem', return_value=kind):
                ontology_apply._local_volume(self.root)

    def test_filesystem_type_is_read_from_mountinfo_with_the_longest_mount_point(self):
        info = ('1 0 8:1 / / rw - ext4 /dev/sda1 rw\n2 1 0:5 / %s rw - nfs4 srv:/x rw\n' % self.root)
        with mock.patch.object(sys, 'platform', 'linux'), mock.patch.object(Path, 'read_text', return_value=info):
            self.assertEqual(ontology_apply._filesystem(self.root), 'nfs4')

    def test_macos_mount_output_is_parsed_and_network_volumes_are_found(self):
        output = ('/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n'
                  '/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled, nobrowse)\n'
                  '//ada@nas.local/vault on /Volumes/vault (smbfs, nodev, nosuid, mounted by ada)\n'
                  'nas:/export on /Volumes/nfs share (nfs, nodev)\n')
        self.assertEqual(ontology_apply._mounts_darwin(output),
                         [('/', 'apfs'), ('/System/Volumes/Data', 'apfs'), ('/Volumes/vault', 'smbfs'), ('/Volumes/nfs share', 'nfs')])
        done = subprocess.CompletedProcess([], 0, stdout=output.encode('utf-8'))
        with mock.patch.object(sys, 'platform', 'darwin'), mock.patch('subprocess.run', return_value=done) as run, \
                mock.patch.object(Path, 'resolve', return_value=Path('/Volumes/vault/Teseo')):
            self.assertEqual(ontology_apply._filesystem(self.root), 'smbfs')
        self.assertEqual(run.call_args.args[0], ['/sbin/mount'])
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_macos_without_a_readable_mount_table_has_no_check(self):
        with mock.patch.object(sys, 'platform', 'darwin'), mock.patch('subprocess.run', side_effect=OSError('no mount')):
            self.assertIsNone(ontology_apply._filesystem(self.root))
            ontology_apply._local_volume(self.root)

    def test_directories_are_synced_after_a_replace_and_the_backup_first(self):
        target, staged, backup = self.root / 'nota.md', self.root / 'sub' / 'staged', self.root / 'sub' / 'displaced'
        (self.root / 'sub').mkdir()
        target.write_bytes(b'vecchio')
        staged.write_bytes(b'nuovo')
        seen = []
        with mock.patch.object(ontology_apply, '_fsync_directory', side_effect=seen.append):
            ontology_apply._replace(target, staged, backup)
        self.assertEqual(seen[0], backup.parent)
        self.assertEqual(set(seen[1:]), {target.parent, staged.parent})

    def test_fsync_directory_ignores_filesystems_that_cannot_sync_directories_but_not_real_errors(self):
        import errno
        with mock.patch('os.fsync', side_effect=OSError(errno.EINVAL, 'no')):
            ontology_apply._fsync_directory(self.root)
        with mock.patch('os.fsync', side_effect=OSError(errno.EIO, 'disco')), self.assertRaises(OSError):
            ontology_apply._fsync_directory(self.root)
        ontology_apply._fsync_directory(self.root / 'inesistente')


if __name__ == '__main__':
    unittest.main()

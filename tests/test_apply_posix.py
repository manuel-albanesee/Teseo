"""Primitive di apply su POSIX: inserimento esclusivo, sostituzione con backup, volumi di rete."""
import _shortpath  # noqa: F401
import os
from pathlib import Path
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
        self.root = Path(self.temp.name)

    def test_move_new_refuses_a_target_recreated_by_an_external_writer(self):
        staged, target = self.root / 'staged', self.root / 'target'
        staged.write_bytes(b'nuovo')
        target.write_bytes(b'esterno')
        with self.assertRaises(FileExistsError):
            ontology_apply._move_new(staged, target)
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
        with mock.patch.object(Path, 'read_text', return_value=info):
            self.assertEqual(ontology_apply._filesystem(self.root), 'nfs4')


if __name__ == '__main__':
    unittest.main()

"""Installazione nuova, upgrade con backup e registro locale esplicito."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import installa
from kit.dashboard.contracts import ContractError
from kit.dashboard.readonly import VaultRegistry
from kit.dashboard.registry_store import RegistryStore
from kit.graph.graph_db import graph_reference

ROOT = Path(__file__).resolve().parents[1]


class Distribution(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='teseo distribution ')
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.root = self.directory / 'vault'

    def install(self, **options):
        with contextlib.redirect_stdout(io.StringIO()):
            return installa.installa(self.root, skill='no', client='codex', **options)

    def hashes(self):
        return {path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob('*') if path.is_file()}

    def test_new_dashboard_install_and_upgrade_preserve_notes_personal_data_and_backup_runtime(self):
        self.assertEqual(self.install(dashboard=True, esempio=True), 0)
        manifest = (self.root / '.teseo/project.json').read_bytes()
        reference = graph_reference(self.root / '.graph/graph.sqlite')
        self.assertTrue(reference.generation)
        self.assertTrue((self.root / '.graph/teseo_dashboard.py').is_file())
        self.assertTrue((self.root / '.graph/dashboard/jobs.py').is_file())
        old = b'# customized old UI\n'
        (self.root / '.graph/dashboard/ui_script.py').write_bytes(old)
        (self.root / '.graph/memoria.sqlite').write_bytes(b'personal bytes: do not open')
        (self.root / 'raw/private.txt').write_text('Immutable source', encoding='utf-8')
        protected = {name: digest for name, digest in self.hashes().items()
                     if name.startswith(('wiki/', 'raw/')) or name in ('.teseo/project.json', '.graph/memoria.sqlite', 'Wiki reference.md')}
        self.assertEqual(self.install(aggiorna=True, dashboard=True), 0)
        self.assertEqual((self.root / '.teseo/project.json').read_bytes(), manifest)
        current = self.hashes()
        for path, digest in protected.items():
            self.assertEqual(current[path], digest, path)
        backups = list((self.root / '.graph_backup').glob('*/dashboard/ui_script.py'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old)
        self.assertEqual((self.root / '.graph/dashboard/ui_script.py').read_bytes(),
                         (ROOT / 'kit/dashboard/ui_script.py').read_bytes())

    def test_legacy_is_not_adopted_even_with_update_flag(self):
        self.assertEqual(self.install(esempio=True), 0)
        before = self.hashes()
        with self.assertRaises(ValueError):
            self.install(aggiorna=True, dashboard=True)
        self.assertEqual(self.hashes(), before)
        self.assertFalse((self.root / '.teseo/project.json').exists())

    def test_unsupported_python_fails_before_creating_vault(self):
        with mock.patch.object(installa.sys, 'version_info', (3, 9)), \
                mock.patch.object(installa.sys, 'argv', ['installa.py', str(self.root)]), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                installa.main()
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.root.exists())

    def test_registry_restart_is_explicit_and_does_not_modify_attached_vault(self):
        self.assertEqual(self.install(dashboard=True), 0)
        before = self.hashes()
        path = self.directory / 'vaults.json'
        registry = VaultRegistry(path)
        try:
            descriptor = registry.attach(str(self.root))
            with self.assertRaises(ContractError) as error:
                VaultRegistry(path)
            self.assertEqual(error.exception.code, 'registry_busy')
        finally:
            registry.close()
        content = path.read_bytes()
        self.assertNotIn(b'token', content)
        restored = VaultRegistry(path)
        try:
            self.assertEqual(restored.list()[0]['vault_id'], descriptor['vault_id'])
            self.assertEqual(restored.restore_issues, [])
        finally:
            restored.close()
        self.assertEqual(self.hashes(), before)
        self.assertEqual(path.read_bytes(), content)

    def test_registry_failed_save_rolls_back_memory_and_preserves_previous_file(self):
        self.assertEqual(self.install(esempio=True), 0)
        path = self.directory / 'vaults.json'
        registry = VaultRegistry(path)
        try:
            with mock.patch.object(RegistryStore, 'write', side_effect=OSError('disk full')):
                with self.assertRaises(ContractError) as error:
                    registry.attach(str(self.root))
            self.assertEqual(error.exception.code, 'registry_unavailable')
            self.assertEqual(registry.list(), [])
            self.assertFalse(path.exists())
            registry.attach(str(self.root))
            previous = path.read_bytes()
            with mock.patch('kit.dashboard.registry_store.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(ContractError):
                    registry.attach(str(self.root))
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(len(registry.list()), 1)
            # Explicit reattach after a local identity change must replace the
            # stale binding, rather than persist two identities for one path.
            (self.root / '.teseo').mkdir(exist_ok=True)
            (self.root / '.teseo/project.json').write_bytes(
                (ROOT / 'tests/fixtures/dashboard/project-v1.json').read_bytes())
            current = registry.attach(str(self.root))
            self.assertEqual([item['vault_id'] for item in registry.list()], [current['vault_id']])
            self.assertEqual(len(json.loads(path.read_bytes())['vaults']), 1)
        finally:
            registry.close()

    def test_registry_restore_rejects_replaced_identity_and_malformed_input(self):
        self.assertEqual(self.install(dashboard=True), 0)
        path = self.directory / 'vaults.json'
        registry = VaultRegistry(path)
        registry.attach(str(self.root))
        registry.close()
        manifest = self.root / '.teseo/project.json'
        data = json.loads(manifest.read_bytes())
        data['vault_id'] = 'cb781bae-ed03-4574-8a37-17d1222f7eb3'
        manifest.write_text(json.dumps(data), encoding='utf-8')
        before = path.read_bytes()
        restored = VaultRegistry(path)
        try:
            self.assertEqual(restored.list(), [])
            self.assertEqual(restored.restore_issues[0]['code'], 'vault_identity_changed')
            self.assertEqual(path.read_bytes(), before)
        finally:
            restored.close()
        path.write_bytes(b'{"format_version":1,"vaults":[],"code":"never execute"}')
        with self.assertRaises(ContractError):
            VaultRegistry(path)
        path.write_bytes(b'{"format_version":1,"vaults":[]}')
        valid = VaultRegistry(path)  # failed parsing released the lock
        valid.close()


if __name__ == '__main__':
    unittest.main()

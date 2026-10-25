"""Real Git receive transactions: adoption, stale previews and recovery gates."""
import unittest
from unittest.mock import patch

import test_sync_pipeline as pipeline
from kit.dashboard.contracts import ContractError
from kit.dashboard.receiver import Receiver
from kit.dashboard.receiver_apply import ReceiverApplyService
from kit.dashboard.storage import VaultLock, capture_snapshot


class Preview(unittest.TestCase):
    def test_diff_is_inert_bounded_and_reports_incomplete_review(self):
        from kit.dashboard.receiver import _preview
        from kit.dashboard.storage import Snapshot, SnapshotFile
        base = Snapshot((SnapshotFile('wiki/Anna.md', b'Originale\n'),))
        candidate = Snapshot((SnapshotFile('wiki/Anna.md', b'<script>inert</script>\n'),))
        result = _preview(base, candidate)
        self.assertIn('+<script>inert</script>', result['diff'])
        self.assertTrue(result['complete'])
        large = Snapshot((SnapshotFile('wiki/Anna.md', b'x'*30000),))
        result = _preview(base, large)
        self.assertLessEqual(len(result['diff']), 20000)
        self.assertTrue(result['truncated'])


class Receive(unittest.TestCase):
    def setUp(self):
        self.fixture = pipeline.Pipeline()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.vault = self.fixture.vault
        self.receiver = Receiver(self.fixture.service.registry, self.fixture.service)
        self.addCleanup(self.receiver.close)
        self.service = ReceiverApplyService(self.fixture.service.registry, self.fixture.service, self.receiver)
        self.fixture.peer_commit('Anna', 'Ricevuta da remoto')
        pending = self.receiver.check(self.vault)
        self.assertEqual(pending['state'], 'pending', pending)
        self.body = dict(exclusive_confirmed=True, expected_head=pending['base_head'],
                         pending_oid=pending['pending_oid'], expected_digest=pending['candidate_digest'])

    def test_adoption_updates_files_index_ref_and_emits_only_vault_update(self):
        import sqlite3
        from kit.dashboard.graph_service import rebuild, graph_reference
        old=rebuild(self.root)
        reader=sqlite3.connect(old.path)
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        reader.execute('SELECT count(*) FROM sqlite_master').fetchone()
        personal=self.root/'.teseo/local/personal.sqlite'
        personal.write_bytes(b'personal state stays local')
        result = self.service.apply(self.vault, self.body)
        self.assertEqual(result['state'], 'current', result)
        self.assertEqual(self.fixture.git('rev-parse', 'HEAD', cwd=self.root), self.body['pending_oid'])
        self.assertEqual(self.fixture.git('status', '--porcelain', cwd=self.root), '')
        self.assertIn('Ricevuta da remoto', (self.root/'wiki/Anna.md').read_text())
        self.assertEqual(result['update_event']['type'], 'vault.updated')
        self.assertFalse((self.root/'.git/index.lock').exists())
        self.assertNotEqual(graph_reference(self.root/'.graph/graph.sqlite').generation,old.generation)
        self.assertEqual(reader.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(personal.read_bytes(),b'personal state stays local')
        self.assertEqual(self.service.apply(self.vault, self.body), result)
        self.assertEqual(self.receiver.check(self.vault)['state'], 'up_to_date')
        from kit.dashboard.shared_migration import _connection
        with _connection(self.root/'.teseo/local/operations.sqlite') as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='validated_events'").fetchone()
            if exists:self.assertEqual(db.execute('SELECT count(*) FROM validated_events').fetchone()[0], 0)

    def test_dirty_live_notes_are_preserved(self):
        self.fixture.page(self.root, 'Anna', 'Modifica esterna')
        before = capture_snapshot(self.root).digest
        with self.assertRaises(ContractError):
            self.service.apply(self.vault, self.body)
        self.assertEqual(capture_snapshot(self.root).digest, before)
        self.assertEqual(self.fixture.git('rev-parse', 'HEAD', cwd=self.root), self.fixture.base)

    def test_modified_candidate_is_rejected_without_live_changes(self):
        from pathlib import Path
        candidate = Path(self.receiver._load(self.root)['candidate']['root'])
        self.fixture.page(candidate, 'Anna', 'Candidato alterato')
        with self.assertRaises(ContractError):
            self.service.apply(self.vault, self.body)
        self.assertEqual(capture_snapshot(self.root).digest, self.fixture.before.digest)

    def test_interrupted_file_replace_blocks_writers_until_finish(self):
        with patch('kit.dashboard.receiver_apply._replace', side_effect=OSError('injected')):
            interrupted = self.service.apply(self.vault, self.body)
        self.assertEqual(interrupted['state'], 'recovery_required', interrupted)
        with self.assertRaises(ContractError) as error:
            with VaultLock(self.root):
                self.fail('Writer admitted during receive recovery')
        self.assertEqual(error.exception.code, 'recovery_required')
        result = self.service.recover(self.vault, dict(self.body, action='finish'))
        self.assertEqual(result['state'], 'current', result)
        self.assertEqual(self.fixture.git('status', '--porcelain', cwd=self.root), '')

    def test_external_edit_after_interruption_is_never_overwritten(self):
        with patch('kit.dashboard.receiver_apply._replace', side_effect=OSError('injected')):
            self.service.apply(self.vault, self.body)
        self.fixture.page(self.root, 'Anna', 'Salvataggio esterno successivo')
        result = self.service.recover(self.vault, dict(self.body, action='finish'))
        self.assertEqual(result['state'], 'recovery_required', result)
        self.assertIn('Salvataggio esterno successivo', (self.root/'wiki/Anna.md').read_text())
        self.assertEqual(self.fixture.git('rev-parse', 'HEAD', cwd=self.root), self.fixture.base)

    def test_terminal_lock_cleanup_replays_without_new_revision(self):
        with patch.object(self.service, '_release', side_effect=OSError('injected')):
            result = self.service.apply(self.vault, self.body)
        self.assertEqual(result['state'], 'recovery_required', result)
        revision = self.receiver._load(self.root)['revision']
        result = self.service.recover(self.vault, dict(self.body, action='finish'))
        self.assertEqual(result['state'], 'current', result)
        self.assertEqual(self.receiver._load(self.root)['revision'], revision)
        self.assertFalse((self.root/'.git/index.lock').exists())


if __name__ == '__main__':
    unittest.main()

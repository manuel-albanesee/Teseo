"""ECC fault injection: receive preserves foreign bytes and completes its journal."""
import _shortpath  # noqa: F401
import os
from pathlib import Path
import shutil
import stat
import time
import unittest
from unittest.mock import patch

import test_sync_pipeline as pipeline
from kit.dashboard import graph_service, receiver_apply
from kit.dashboard.contracts import ContractError, file_hash
from kit.dashboard.receiver import Receiver
from kit.dashboard.receiver_apply import ReceiverApplyService
from kit.dashboard.shared_service import SharedService
from kit.dashboard.storage import VaultLock, capture_snapshot


class SimulatedCrash(BaseException):
    pass


class ReceiveFaults(unittest.TestCase):
    def setUp(self):
        self.fixture = pipeline.Pipeline()
        self.fixture.setUp()
        # Own cleanup here: tempfile's recursive PermissionError handling can
        # loop indefinitely on Windows Git objects held by a scanner.
        self.fixture.tmp._finalizer.detach()
        self.addCleanup(self.cleanup_fixture)
        self.root = self.fixture.root
        self.vault = self.fixture.vault
        self.sync = self.fixture.service
        self.receiver = Receiver(self.sync.registry, self.sync)
        self.addCleanup(self.receiver.close)
        self.service = ReceiverApplyService(self.sync.registry, self.sync, self.receiver)
        self.fixture.peer_commit('Bruno', 'Ricezione per fault injection')
        pending = self.receiver.check(self.vault)
        self.assertEqual(pending['state'], 'pending', pending)
        self.body = dict(exclusive_confirmed=True, expected_head=pending['base_head'],
                         pending_oid=pending['pending_oid'], expected_digest=pending['candidate_digest'])

    def cleanup_fixture(self):
        target = self.fixture.home.resolve()
        if target.parent != Path.cwd().resolve() or not target.name.startswith('teseo-publisher-'):
            raise ValueError('Unexpected receive fixture cleanup path')

        def unlock(function, path, error):
            if not isinstance(error[1], PermissionError) or os.stat(path).st_mode & stat.S_IWRITE:
                raise error[1]
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)

        for attempt in range(21):
            try:
                shutil.rmtree(target, onerror=unlock)
                return
            except PermissionError:
                if attempt == 20:
                    raise
                time.sleep(.25)

    def recover(self, action='finish'):
        return self.service.recover(self.vault, dict(self.body, action=action))

    def assert_barriers(self):
        with self.assertRaises(ContractError) as error:
            with VaultLock(self.root):
                self.fail('Cooperative writer admitted during receive recovery')
        self.assertEqual(error.exception.code, 'recovery_required')
        with self.assertRaises(ContractError) as error:
            SharedService(self.sync.registry).answers(self.vault)
        self.assertEqual(error.exception.code, 'recovery_required')

    def assert_current(self, result):
        self.assertEqual(result['state'], 'current', result)
        self.assertEqual(self.fixture.git('rev-parse', 'HEAD', cwd=self.root), self.body['pending_oid'])
        self.assertEqual(self.fixture.git('status', '--porcelain', cwd=self.root), '')
        self.assertEqual(capture_snapshot(self.root).digest, self.body['expected_digest'])
        self.assertEqual(self.receiver._load(self.root)['last_applied_oid'], self.body['pending_oid'])
        self.assertEqual(self.receiver._config(self.root)['B'], self.body['pending_oid'])
        self.assertFalse((self.root / '.git/index.lock').exists())

    def test_metadata_write_failure_remains_blocked_until_finish(self):
        save = self.receiver._save

        def fail_current(root, record):
            if record.get('state') == 'current':
                raise OSError('injected receiver metadata failure')
            return save(root, record)

        with patch.object(self.receiver, '_save', side_effect=fail_current):
            interrupted = self.service.apply(self.vault, self.body)
        self.assertEqual(interrupted['state'], 'recovery_required', interrupted)
        self.assert_barriers()
        self.assert_current(self.recover())

    def test_external_head_arriving_before_cas_is_preserved(self):
        repo = self.sync._repo(self.root)
        tree = repo.run('rev-parse', self.fixture.base + '^{tree}').strip()
        foreign = repo.run('commit-tree', tree, '-p', self.fixture.base, input='Foreign HEAD to preserve\n').strip()
        check = self.service._check
        injected = []

        def move_after_index(root, current_repo, record, base, candidate):
            live = check(root, current_repo, record, base, candidate)
            if not injected and file_hash(root / '.git/index') == record['index_target']:
                current_repo.run('update-ref', 'refs/heads/team', foreign, record['B'])
                injected.append(True)
            return live

        with patch.object(self.service, '_check', side_effect=move_after_index):
            interrupted = self.service.apply(self.vault, self.body)
        self.assertTrue(injected)
        self.assertEqual(interrupted['state'], 'recovery_required', interrupted)
        self.assertEqual(repo.head(), foreign)
        self.assert_barriers()
        self.assertEqual(self.recover()['state'], 'recovery_required')
        self.assertEqual(repo.head(), foreign)

    def test_missing_index_after_failed_replace_can_finish(self):
        replace = receiver_apply._replace
        displaced = []

        def lose_index(target, staged, backup):
            if target == self.root / '.git/index':
                os.rename(target, backup)
                displaced.append(backup)
                raise OSError('injected failure after index displacement')
            return replace(target, staged, backup)

        with patch('kit.dashboard.receiver_apply._replace', side_effect=lose_index):
            interrupted = self.service.apply(self.vault, self.body)
        self.assertEqual(interrupted['state'], 'recovery_required', interrupted)
        self.assertFalse((self.root / '.git/index').exists())
        self.assertTrue(displaced[0].is_file())
        self.assert_barriers()
        self.assert_current(self.recover())

    def test_partial_note_replacement_can_rollback_without_losing_remote_candidate(self):
        replace = receiver_apply._replace

        def stop_after_note(target, staged, backup):
            replace(target, staged, backup)
            if target == self.root / 'wiki/Bruno.md':
                raise OSError('injected stop after actual note replacement')

        with patch('kit.dashboard.receiver_apply._replace', side_effect=stop_after_note):
            interrupted = self.service.apply(self.vault, self.body)
        self.assertEqual(interrupted['state'], 'recovery_required', interrupted)
        self.assertIn('Ricezione', (self.root / 'wiki/Bruno.md').read_text())
        self.assert_barriers()
        rolled_back = self.recover('rollback')
        self.assertEqual(rolled_back['state'], 'rolled_back', rolled_back)
        self.assertEqual(capture_snapshot(self.root).digest, self.fixture.before.digest)
        self.assertEqual(self.fixture.git('rev-parse', 'HEAD', cwd=self.root), self.fixture.base)
        self.assertEqual(self.fixture.git('status', '--porcelain', cwd=self.root), '')
        self.assertEqual(self.receiver._load(self.root)['pending_oid'], self.body['pending_oid'])
        self.assertFalse((self.root / '.git/index.lock').exists())

    def test_revert_to_base_during_rebuild_cannot_be_declared_current(self):
        rebuild = graph_service.rebuild
        before = (self.root / 'wiki/Bruno.md').read_bytes()

        def revert_during_rebuild(root, *args, **kwargs):
            result = rebuild(root, *args, **kwargs)
            if Path(root) == self.root:
                (self.root / 'wiki/Bruno.md').write_bytes(before)
            return result

        with patch('kit.dashboard.graph_service.rebuild', side_effect=revert_during_rebuild):
            interrupted = self.service.apply(self.vault, self.body)
        self.assertEqual(interrupted['state'], 'recovery_required', interrupted)
        self.assertEqual((self.root / 'wiki/Bruno.md').read_bytes(), before)
        self.assert_barriers()
        self.assert_current(self.recover())

    def test_orphan_preparation_can_retry_with_untouched_live_files(self):
        persist = self.service._persist

        def stop_after_snapshot(root, prefix, snapshot):
            persist(root, prefix, snapshot)
            raise OSError('injected preparation crash before receive journal')

        with patch.object(self.service, '_persist', side_effect=stop_after_snapshot):
            with self.assertRaises(OSError):
                self.service.apply(self.vault, self.body)
        self.assertIsNone(self.service._load(self.root))
        self.assertEqual(capture_snapshot(self.root).digest, self.fixture.before.digest)
        self.assert_current(self.service.apply(self.vault, self.body))

    def test_process_crash_after_terminal_journal_releases_only_owned_lock_on_replay(self):
        with patch.object(self.service, '_release', side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.service.apply(self.vault, self.body)
        self.assertEqual(self.service._load(self.root)['state'], 'current')
        self.assertEqual(self.service.status(self.vault)['state'], 'recovery_required')
        revision = self.receiver._load(self.root)['revision']
        self.assert_barriers()
        self.assert_current(self.recover())
        self.assertEqual(self.receiver._load(self.root)['revision'], revision)


if __name__ == '__main__':
    unittest.main()

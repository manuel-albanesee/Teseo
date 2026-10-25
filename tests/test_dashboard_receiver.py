"""Receiver scheduling and readonly gates with an injected clock and transport."""
from pathlib import Path
import tempfile
import threading
import unittest
from uuid import uuid4

from kit.dashboard.contracts import ContractError, canonical_json
from kit.dashboard.storage import capture_snapshot
from kit.dashboard.sync_service import SyncService
from kit.dashboard.shared_migration import _connection
from kit.dashboard.storage import Journal, VaultLock
from kit.dashboard.receiver import Receiver


class Repository:
    def __init__(self, root):
        self.root = root
        self.oid = 'a' * 40
        self.remote = self.oid
        self.dirty = False
        self.error = None
        self.fetches = 0
        self.stages = 0
    def head(self): return self.oid
    def clean(self): return not self.dirty
    def inspect(self): return dict(head=self.oid, branch='team', remote_url='https://github.com/example/data.git', tracked_violations=[])
    def fetch(self, remote, branch):
        self.fetches += 1
        if self.error: raise ContractError(self.error, 'secret must not escape')
        return self.remote
    def is_ancestor(self, a, b): return a == b or a == 'a' * 40
    def audit_history(self, oid): return {'history_audited': True}
    def tree(self, oid): return {f.path: f.data for f in capture_snapshot(self.root).files}
    def snapshot(self, oid):
        self.stages += 1
        return dict(oid=oid, root=str(self.root))


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = str(uuid4())
        (self.root / 'wiki').mkdir()
        (self.root / '.teseo').mkdir()
        (self.root / 'wiki/Anna.md').write_text('Anna', encoding='utf8')
        (self.root / 'Wiki reference.md').write_text('Schema', encoding='utf8')
        (self.root / '.teseo/project.json').write_bytes(canonical_json(dict(format_version=1,schema_version=1,event_version=1,vault_id=self.vault,minimum_kit_version='1.0.0',shared_paths=['wiki/','raw/','Wiki reference.md','index.md','log.md','.teseo/shared/'])))
        self.registry = type('Registry', (), {'root': lambda _, v: self.root, 'list': lambda _: [{'vault_id': self.vault}]})()
        self.repo = Repository(self.root)
        self.sync = SyncService(self.registry, repository_factory=lambda root: self.repo)
        self.now = 1000
        self.receiver = Receiver(self.registry, self.sync, clock=lambda: self.now, jitter=lambda: 0)
        self.addCleanup(self.receiver.close)
    def configure(self):
        with self.sync._db(self.root) as db:
            self.sync._schema(db)
            config = dict(remote='origin',branch='team',remote_url='https://github.com/example/data.git',vault_id=self.vault,B=self.repo.oid,base_digest=capture_snapshot(self.root).digest,raw_paths=[])
            db.execute('INSERT INTO config VALUES(1,?)', (canonical_json(config),))
    def test_status_is_readonly_and_poll_is_opt_in(self):
        result = self.receiver.status(self.vault)
        self.assertTrue(result['paused'])
        self.assertFalse(result['automatic'])
        self.assertFalse((self.root / '.teseo/local').exists())
        self.receiver.start(); self.receiver.request_stop(); self.receiver.close()
        self.assertEqual(self.repo.fetches, 0)
    def test_same_oid_is_noop_without_staging(self):
        self.configure()
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'up_to_date')
        self.assertEqual(result['last_applied_oid'], self.repo.oid)
        self.receiver.check(self.vault)
        self.assertEqual(self.repo.stages, 0)
    def test_remote_ahead_stages_without_changing_live_notes_or_head(self):
        self.configure(); before = capture_snapshot(self.root).digest
        self.repo.remote = 'b' * 40
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'pending')
        self.assertEqual(result['pending_oid'], self.repo.remote)
        self.assertEqual(result['last_applied_oid'], 'a' * 40)
        self.assertEqual(capture_snapshot(self.root).digest, before)
        self.assertEqual(self.repo.oid, 'a' * 40)
        self.receiver.check(self.vault)
        self.assertEqual(self.repo.stages, 1)
    def test_dirty_keeps_pending_but_defers_staging(self):
        self.configure(); self.repo.remote = 'b' * 40; self.repo.dirty = True
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'waiting_idle')
        self.assertEqual(result['pending_oid'], self.repo.remote)
        self.assertEqual(self.repo.stages, 0)
    def test_offline_backoff_redacts_error_and_auth_suspends(self):
        self.configure(); self.repo.error = 'git_network'
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'offline')
        self.assertGreater(result['next_check_at'], self.now)
        self.assertNotIn('secret', str(result))
        old = result['backoff']; self.now += old
        result = self.receiver.check(self.vault)
        self.assertGreater(result['backoff'], old)
        self.repo.error = 'git_auth'
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'auth_required')
        self.assertTrue(result['paused'])
    def test_pending_survives_restart_pause_and_resume(self):
        self.configure(); self.repo.remote = 'b' * 40
        self.receiver.check(self.vault)
        self.receiver.pause(self.vault)
        restarted = Receiver(self.registry, self.sync, clock=lambda: self.now, jitter=lambda: 0)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.status(self.vault)['pending_oid'], self.repo.remote)
        resumed = restarted.resume(self.vault, {'interval_seconds': 30})
        self.assertFalse(resumed['paused']); self.assertFalse(resumed['automatic'])
    def test_divergence_and_rewind_require_resolution(self):
        self.configure(); self.repo.remote = 'b' * 40
        self.receiver.check(self.vault)
        self.repo.remote = 'a' * 40
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'diverged')
        self.assertEqual(result['pending_oid'], 'b' * 40)
        self.repo.oid = 'c' * 40; self.repo.remote = 'd' * 40
        self.assertEqual(self.receiver.check(self.vault)['state'], 'diverged')
    def test_invalid_interval_and_unknown_fields_rejected_before_writes(self):
        for body in ({'interval_seconds': True}, {'interval_seconds': 29}, {'interval_seconds': 3601}, {'automatic': True}):
            with self.assertRaises(ContractError): self.receiver.resume(self.vault, body)
        self.assertFalse((self.root / '.teseo/local').exists())

    def test_clock_poll_debounces_suspend_and_pause(self):
        self.configure(); self.receiver._poll_once()
        self.assertEqual(self.repo.fetches, 0)
        self.receiver.resume(self.vault, {'interval_seconds': 30})
        self.receiver._poll_once(); self.receiver._poll_once()
        self.assertEqual(self.repo.fetches, 1)
        self.now += 10000
        self.receiver._poll_once(); self.receiver._poll_once()
        self.assertEqual(self.repo.fetches, 2)
        self.receiver.pause(self.vault); self.now += 10000
        self.receiver._poll_once()
        self.assertEqual(self.repo.fetches, 2)

    def test_auth_suspension_survives_scheduling_until_explicit_resume(self):
        self.configure(); self.receiver.resume(self.vault)
        self.repo.error = 'git_auth'; self.receiver._poll_once()
        self.now += 20000; self.repo.error = None
        self.receiver._poll_once()
        self.assertEqual(self.repo.fetches, 1)
        self.receiver.resume(self.vault); self.receiver._poll_once()
        self.assertEqual(self.repo.fetches, 2)

    def test_pending_note_job_and_publisher_defer_with_remote_oid_kept(self):
        self.configure(); self.repo.remote = 'b' * 40
        with self.sync._mutex, VaultLock(self.root) as lock, Journal(lock) as journal:
            journal.create('lint', {}, 'receiver-busy-test', capture_snapshot(self.root), initial={'state': 'awaiting_client'})
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'waiting_idle')
        self.assertEqual(result['pending_oid'], self.repo.remote)
        self.assertEqual(self.repo.stages, 0)

    def test_pending_publisher_defers_without_replacing_notes(self):
        self.configure(); self.repo.remote = 'b' * 40
        with self.sync._db(self.root) as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (str(uuid4()), 'publish-pending', 'hash', canonical_json({'state': 'waiting_network'})))
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'waiting_idle')
        self.assertEqual(result['pending_oid'], self.repo.remote)

    def test_two_manual_checks_do_not_overlap_fetch(self):
        self.configure()
        entered = threading.Event(); release = threading.Event(); calls = []
        def blocked_fetch(remote, branch):
            calls.append(True); entered.set(); release.wait(3)
            return self.repo.remote
        self.repo.fetch = blocked_fetch
        results = []; failures = []
        def run():
            try: results.append(self.receiver.check(self.vault))
            except BaseException as error: failures.append(error)
        first = threading.Thread(target=run); second = threading.Thread(target=run)
        first.start(); self.assertTrue(entered.wait(3)); second.start()
        self.assertEqual(len(calls), 1)
        release.set(); first.join(5); second.join(5)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertFalse(failures); self.assertEqual(len(results), 2)

    def test_status_reports_receive_recovery_without_writing(self):
        self.configure()
        path = self.root / '.teseo/local/receive.sqlite'
        with _connection(path) as db:
            db.execute('CREATE TABLE transactions(record BLOB NOT NULL)')
            db.execute('INSERT INTO transactions VALUES(?)', (canonical_json({'state': 'recovery_required'}),))
        before = path.read_bytes()
        result = self.receiver.status(self.vault)
        self.assertEqual(result['state'], 'recovery_required')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.repo.fetches, 0)

    def test_local_untracked_changes_never_establish_applied_baseline(self):
        self.configure(); self.repo.dirty = True
        (self.root / 'wiki/Anna.md').write_text('Editor', encoding='utf8')
        result = self.receiver.check(self.vault)
        self.assertIsNone(result['last_applied_oid'])
        self.assertEqual(result['state'], 'waiting_idle')

    def test_staged_tree_mismatch_is_incompatible_and_keeps_live_data(self):
        self.configure(); self.repo.remote = 'b' * 40
        self.repo.tree = lambda oid: {'wiki/Anna.md': b'Other data'}
        before = capture_snapshot(self.root).digest
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'incompatible')
        self.assertEqual(capture_snapshot(self.root).digest, before)
        self.assertEqual(self.repo.oid, 'a' * 40)

    def test_shutdown_waits_for_active_fetch_and_does_not_stage_after_stop(self):
        self.configure(); self.receiver.resume(self.vault)
        entered = threading.Event(); release = threading.Event()
        self.repo.remote = 'b' * 40
        def blocked_fetch(remote, branch):
            entered.set(); release.wait(3)
            return self.repo.remote
        self.repo.fetch = blocked_fetch
        self.receiver.start(); self.assertTrue(entered.wait(3))
        self.receiver.request_stop()
        closer = threading.Thread(target=self.receiver.close); closer.start()
        self.assertTrue(closer.is_alive())
        release.set(); closer.join(5)
        self.assertFalse(closer.is_alive())
        self.assertFalse(self.receiver.status(self.vault)['service_active'])
        self.assertEqual(self.repo.stages, 0)

    def test_new_oid_clears_previous_candidate_when_new_revision_is_busy(self):
        self.configure(); self.repo.remote = 'b' * 40
        self.receiver.check(self.vault)
        self.repo.is_ancestor = lambda a, b: a == b or a == 'a' * 40 or (a == 'b' * 40 and b == 'c' * 40)
        self.repo.remote = 'c' * 40; self.repo.dirty = True
        result = self.receiver.check(self.vault)
        self.assertEqual(result['state'], 'waiting_idle')
        record = self.receiver._load(self.root)
        self.assertIsNone(record['candidate'])
        self.assertIsNone(record['candidate_digest'])

    def test_terminal_receive_with_owned_index_lock_still_reports_recovery(self):
        self.configure()
        (self.root / '.git').mkdir()
        (self.root / '.git/index.lock').write_bytes(b'receive-marker')
        with _connection(self.root / '.teseo/local/receive.sqlite') as db:
            db.execute('CREATE TABLE transactions(record BLOB NOT NULL)')
            db.execute('INSERT INTO transactions VALUES(?)', (canonical_json({'state': 'current', 'index_lock_marker': 'receive-marker'}),))
        self.assertEqual(self.receiver.status(self.vault)['state'], 'recovery_required')

    def test_default_clock_and_jitter_persist_integer_timestamps(self):
        self.configure()
        receiver = Receiver(self.registry, self.sync)
        self.addCleanup(receiver.close)
        resumed = receiver.resume(self.vault)
        self.assertIs(type(resumed['next_check_at']), int)
        result = receiver.check(self.vault)
        self.assertEqual(result['state'], 'up_to_date')
        self.assertIs(type(result['last_fetch_at']), int)
        self.assertIs(type(result['next_check_at']), int)
        self.repo.error = 'git_network'
        result = receiver.check(self.vault)
        self.assertEqual(result['state'], 'offline')
        self.assertIs(type(result['next_check_at']), int)

    def test_readonly_legacy_status_prefers_registry_root(self):
        def incompatible_operation_root(vault):
            raise ContractError('vault_readonly', 'Legacy vault has no manifest')
        self.registry.operation_root = incompatible_operation_root
        self.assertTrue(self.receiver.status(self.vault)['paused'])
        self.assertFalse((self.root / '.teseo/local').exists())

    def test_status_falls_back_to_operation_root_during_partial_apply(self):
        self.registry.operation_root = lambda vault: self.root
        self.registry.root = lambda vault: (_ for _ in ()).throw(ContractError('vault_readonly', 'Schema missing during apply'))
        self.assertTrue(self.receiver.status(self.vault)['paused'])


if __name__ == '__main__': unittest.main()

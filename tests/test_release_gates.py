"""Release gates: merge di index/log, push rifiutato/protetto, scrittori concorrenti, candidati ostili.

Git reali (remoto bare locale), vault reali, nessun mock dell'unità sotto test.
"""
import _shortpath  # noqa: F401
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import unittest

import test_dashboard_operations as ops
import test_sync_pipeline as pipeline
from kit.dashboard.contracts import ContractError, SUPPORTED_VERSIONS, canonical_json, parse_json
from kit.dashboard.receiver import Receiver
from kit.dashboard.receiver_apply import ReceiverApplyService
from kit.dashboard.storage import Journal, VaultLock, capture_snapshot
from kit.dashboard.sync_validation import validate_integration

ROOT = Path(__file__).resolve().parents[1]
INDEX, LOG = '# Indice\nTesta: uno\n\nCorpo\n\nCoda: uno\n', '# Log\n- avvio\n'


class Env(unittest.TestCase):
    """Due cloni (root/peer) e remoto bare del fixture di pipeline, con index.md e log.md condivisi."""

    def setUp(self):
        self.p = pipeline.Pipeline()
        self.p.setUp()
        self.addCleanup(self.p.doCleanups)
        self.addCleanup(self.force_remove, Path(self.p.tmp.name))  # oggetti Git read-only: ritenta dopo cleanup
        self.root, self.peer, self.remote, self.vault = self.p.root, self.p.peer, self.p.remote, self.p.vault
        self.service = self.p.service
        self.pushed = self.remote / 'received.log'

    @staticmethod
    def force_remove(folder):
        def writable(function, path, error):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)
        if folder.exists():
            import shutil
            shutil.rmtree(folder, onerror=writable)

    def seed(self):
        """index.md e log.md entrano nella base condivisa; la configurazione è rifatta su quella base."""
        (self.root / 'index.md').write_text(INDEX, encoding='utf-8', newline='\n')
        (self.root / 'log.md').write_text(LOG, encoding='utf-8', newline='\n')
        self.p.git('add', '--', 'index.md', 'log.md', cwd=self.root)
        self.p.git('commit', '-m', 'indice e log', cwd=self.root)
        self.p.git('push', 'origin', 'team', cwd=self.root)
        self.p.git('pull', '--ff-only', 'origin', 'team', cwd=self.peer)
        self.p.base = self.git('rev-parse', 'HEAD', cwd=self.root)
        self.service.configure(self.vault, dict(remote='origin', branch='team', visibility='private', mode='direct',
                                                raw_paths=[], share_confirmed=True, expected_head=self.p.base))
        self.p.before = capture_snapshot(self.root)

    def git(self, *args, cwd=None):
        return self.p.git(*args, cwd=cwd or self.root)

    def tip(self):
        return self.git('rev-parse', 'refs/heads/team', cwd=self.remote)

    def ancestor(self, old, new):
        return subprocess.run(['git', 'merge-base', '--is-ancestor', old, new], cwd=self.root).returncode == 0

    def peer_write(self, relative, data, message='peer', mode=None):
        """Commit del peer con byte esatti; con mode forza il bit di esecuzione/symlink nell'indice."""
        target = self.peer / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.p.git('add', '--', relative, cwd=self.peer)
        if mode:
            self.p.git('update-index', '--chmod=+x', '--', relative, cwd=self.peer)
        self.p.git('commit', '-m', message, cwd=self.peer)
        self.p.git('push', 'origin', 'team', cwd=self.peer)
        return self.git('rev-parse', 'HEAD', cwd=self.peer)

    def edit(self, relative, old, new, base=None):
        base = base or self.root
        (base / relative).write_text((base / relative).read_text(encoding='utf-8').replace(old, new), encoding='utf-8', newline='\n')

    def remote_hook(self, body):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_bytes(('#!/bin/sh\ncat >> received.log\n' + body).encode('utf-8'))
        hook.chmod(0o755)

    def decide(self, body, result):
        return self.service.resolve(self.vault, dict(idempotency_key=body['idempotency_key'], exclusive_confirmed=True,
                                                    human_decision_key=result['validation']['key']))


class IndexLogMerge(Env):
    def setUp(self):
        super().setUp()
        self.seed()

    def test_disjoint_index_edits_merge_without_loss_but_need_human_decision_and_reach_remote_once_decided(self):
        self.edit('index.md', 'Testa: uno', 'Testa: locale')
        body = self.p.validated()
        self.peer_write('index.md', (INDEX.replace('Coda: uno', 'Coda: remota')).encode())
        before = self.tip()
        result = self.service.publish(self.vault, body)
        self.assertEqual(result['state'], 'needs_decision', result)  # index.md è globale: mai auto-pubblicato
        self.assertEqual(self.tip(), before)
        merged = (Path(result['candidate_path']) / 'index.md').read_text(encoding='utf-8')
        self.assertIn('Testa: locale', merged)
        self.assertIn('Coda: remota', merged)
        self.assertIn('index.md', result['validation']['scope'])
        done = self.decide(body, result)
        self.assertEqual(done['state'], 'converged', done)
        final = self.git('show', 'refs/heads/team:index.md', cwd=self.remote)
        self.assertTrue(all(x in final for x in ('Testa: locale', 'Coda: remota')))
        self.assertEqual((self.root / 'index.md').read_text(encoding='utf-8'), final + '\n' if not final.endswith('\n') else final)
        self.assertTrue(self.ancestor(before, self.tip()))  # fast-forward del remoto, nessuna riscrittura

    def test_concurrent_log_appends_conflict_and_both_sides_bytes_survive(self):
        self.edit('log.md', '- avvio\n', '- avvio\n- locale\n')
        body = self.p.validated()
        remote_commit = self.peer_write('log.md', (LOG + '- remoto\n').encode())
        result = self.service.publish(self.vault, body)
        self.assertEqual((result['state'], result['error']['code']), ('needs_resolution', 'git_conflict'), result)
        self.assertEqual(self.tip(), remote_commit)  # nessun push, nessun force
        self.assertEqual((self.root / 'log.md').read_text(encoding='utf-8'), LOG + '- locale\n')
        self.assertEqual(self.git('rev-parse', 'HEAD'), result['L'])
        stage = (Path(result['error']['path']) / 'log.md').read_text(encoding='utf-8')
        self.assertTrue('- locale' in stage and '- remoto' in stage and '<<<<<<<' in stage)
        self.assertEqual(self.git('show', remote_commit + ':log.md', cwd=self.remote), (LOG + '- remoto').rstrip())
        # La risoluzione revisionata (unione) è validata e pubblicata senza perdere nessuna riga.
        (Path(result['error']['path']) / 'log.md').write_text(LOG + '- locale\n- remoto\n', encoding='utf-8', newline='\n')
        digest = capture_snapshot(result['error']['path']).digest
        resume = dict(idempotency_key=body['idempotency_key'], exclusive_confirmed=True, resolution_digest=digest)
        result = self.service.resolve(self.vault, resume)
        self.assertEqual(result['state'], 'needs_decision', result)
        done = self.service.resolve(self.vault, dict(resume, human_decision_key=result['validation']['key']))
        self.assertEqual(done['state'], 'converged', done)
        final = self.git('show', 'refs/heads/team:log.md', cwd=self.remote)
        self.assertEqual(final.splitlines(), ['# Log', '- avvio', '- locale', '- remoto'])
        self.assertTrue(self.ancestor(remote_commit, self.tip()))

    def test_same_line_index_conflict_preserves_local_remote_and_candidate_variants(self):
        self.edit('index.md', 'Testa: uno', 'Testa: locale')
        body = self.p.validated()
        remote_commit = self.peer_write('index.md', INDEX.replace('Testa: uno', 'Testa: remota').encode())
        local_bytes = (self.root / 'index.md').read_bytes()
        result = self.service.publish(self.vault, body)
        self.assertEqual((result['state'], result['error']['code']), ('needs_resolution', 'git_conflict'), result)
        self.assertEqual(self.tip(), remote_commit)
        self.assertEqual((self.root / 'index.md').read_bytes(), local_bytes)
        stage = (Path(result['error']['path']) / 'index.md').read_text(encoding='utf-8')
        self.assertTrue('Testa: locale' in stage and 'Testa: remota' in stage)
        self.assertEqual(self.git('show', remote_commit + ':index.md', cwd=self.remote), INDEX.replace('Testa: uno', 'Testa: remota').rstrip())
        # Marker di conflitto lasciati nel candidato non superano mai la risoluzione.
        digest = capture_snapshot(result['error']['path']).digest
        failed = self.service.resolve(self.vault, dict(idempotency_key=body['idempotency_key'], exclusive_confirmed=True, resolution_digest=digest))
        self.assertEqual((failed['state'], failed['error']['code']), ('needs_resolution', 'git_conflict'), failed)
        self.assertEqual(self.tip(), remote_commit)

    def test_isolated_merge_is_deterministic_and_validator_sees_all_lines(self):
        self.edit('index.md', 'Testa: uno', 'Testa: locale')
        body = self.p.validated()
        self.peer_write('index.md', INDEX.replace('Coda: uno', 'Coda: remota').encode())
        first = self.service.publish(self.vault, body)
        merged = (Path(first['candidate_path']) / 'index.md').read_bytes()
        self.assertEqual(merged, INDEX.replace('Testa: uno', 'Testa: locale').replace('Coda: uno', 'Coda: remota').encode())
        self.assertEqual(self.service.publish(self.vault, body)['C'], first['C'])  # idempotente: stesso candidato, nessun secondo push
        self.assertEqual(self.pushed.exists(), False)


class PushRejection(Env):
    def advance(self, label):
        """Il remoto avanza fra fetch e push: eseguito dal validatore, ultimo passo prima del push."""
        self.peer_write('wiki/Bruno.md', ('---\ntipo: persona\n---\nRemoto ' + label + '\n').encode())

    def publish_with(self, hook):
        self.p.page(self.root, 'Anna', 'Locale')
        body = self.p.validated()
        self.service.validator = lambda *a, **k: (hook(), validate_integration(*a, **k))[1]
        return body, self.service.publish(self.vault, body)

    def test_remote_advancing_before_push_is_retried_bounded_and_never_forced(self):
        self.remote_hook('')
        self.git('config', 'receive.denyNonFastForwards', 'true', cwd=self.remote)
        calls = []
        body, result = self.publish_with(lambda: (calls.append(1), self.advance('uno') if len(calls) == 1 else None))
        self.assertEqual(result['state'], 'converged', result)
        self.assertEqual((len(calls), result['attempts']), (2, 2))
        self.assertEqual(self.tip(), result['C'])
        final = self.git('ls-tree', '-r', '--name-only', self.tip(), cwd=self.remote)
        self.assertIn('wiki/Bruno.md', final)
        self.assertIn('Remoto uno', self.git('show', self.tip() + ':wiki/Bruno.md', cwd=self.remote))
        self.assertIn('Locale', self.git('show', self.tip() + ':wiki/Anna.md', cwd=self.remote))
        updates = [line.split() for line in self.pushed.read_text().splitlines()]
        for old, new, _ in updates:  # ogni aggiornamento del remoto è un fast-forward
            self.assertTrue(set(old) == {'0'} or self.ancestor(old, new), (old, new))
        self.assertEqual(updates[-1][1], result['C'])

    def test_persistent_remote_races_stop_at_three_attempts_and_preserve_everything(self):
        self.remote_hook('')
        calls = []
        body, result = self.publish_with(lambda: (calls.append(1), self.advance(str(len(calls)))))
        self.assertEqual(result['state'], 'retry_exhausted', result)
        self.assertEqual((len(calls), result['attempts']), (3, 3))
        self.assertEqual(self.tip(), self.git('rev-parse', 'HEAD', cwd=self.peer))  # solo i commit del peer
        self.assertNotEqual(self.tip(), result['C'])
        self.assertTrue(self.ancestor(self.p.base, self.tip()))
        self.assertEqual(len(self.pushed.read_text().splitlines()), 3)  # tre push del peer, nessuno del publisher
        self.assertEqual(self.git('rev-parse', 'HEAD'), result['L'])  # checkpoint locale intatto
        self.assertIn('Locale', (self.root / 'wiki/Anna.md').read_text(encoding='utf-8'))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_protected_branch_pauses_for_approval_keeps_checkpoint_and_resumes_without_force(self):
        self.remote_hook('echo "protected branch" >&2\nexit 1\n')
        before = self.tip()
        self.p.page(self.root, 'Anna', 'Locale')
        body = self.p.validated()
        result = self.service.publish(self.vault, body)
        self.assertEqual((result['state'], result['error']['code']), ('needs_approval', 'git_policy'), result)
        self.assertEqual(self.tip(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), result['L'])
        self.assertNotEqual(result['L'], self.p.base)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertIn('Locale', (self.root / 'wiki/Anna.md').read_text(encoding='utf-8'))
        self.assertEqual(len(self.pushed.read_text().splitlines()), 1)
        self.assertFalse(any('+' in line.split()[0] for line in self.pushed.read_text().splitlines()))
        self.remote_hook('')  # la protezione viene rimossa dal responsabile del remoto
        done = self.service.resolve(self.vault, dict(idempotency_key=body['idempotency_key'], exclusive_confirmed=True))
        self.assertEqual(done['state'], 'converged', done)
        self.assertEqual((done['L'], self.tip()), (result['L'], done['C']))  # stesso checkpoint, nessun commit duplicato
        self.assertTrue(self.ancestor(before, self.tip()))


class WriterConcurrency(unittest.TestCase):
    request_timeout = 30
    setUp, stop, request, manifest, hashes = ops.Operations.setUp, ops.Operations.stop, ops.Operations.request, ops.Operations.manifest, ops.Operations.hashes
    attach, get, submit, complete, receipt = ops.Operations.attach, ops.Operations.get, ops.Operations.submit, ops.Operations.complete, ops.Operations.receipt
    apply, prepared = ops.Operations.apply, ops.Operations.prepared

    def lint(self, key):
        return {'kind': 'lint', 'inputs': [], 'scope': ['wiki/'], 'adapter': 'fake', 'idempotency_key': key,
                'base_content_digest': capture_snapshot(self.root).digest}

    def holder(self):
        """Secondo scrittore reale: un processo che tiene il lock kernel del vault finché non chiude stdin."""
        code = ('import sys;sys.path.insert(0,sys.argv[2])\nfrom kit.dashboard.storage import VaultLock\n'
                'with VaultLock(sys.argv[1]):\n print("locked",flush=True);sys.stdin.read()\n')
        process = subprocess.Popen([sys.executable, '-c', code, str(self.root), str(ROOT)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT))
        self.addCleanup(lambda: (process.stdin.close(), process.wait(30), process.stdout.close(), process.stderr.close()))
        self.assertEqual(process.stdout.readline().strip(), b'locked', process.stderr.read1() if process.poll() else '')
        return process

    def test_two_submitters_are_serialized_one_active_one_queued_and_both_recorded(self):
        self.server.skills.adapters['fake'] = ops.FakeAdapter()
        results, barrier = [], threading.Barrier(2)
        def writer(key):
            barrier.wait()
            results.append(self.request('POST', self.base + 'operations', self.lint(key))[:3:2])
        threads = [threading.Thread(target=writer, args=(k,)) for k in ('writer_a_001', 'writer_b_001')]
        [t.start() for t in threads]
        [t.join(60) for t in threads]
        self.assertEqual(sorted(status for status, _ in results), [202, 202], results)
        states = sorted(json.loads(raw)['state'] for _, raw in results)
        self.assertEqual(states, ['awaiting_client', 'queued'])  # mai due cicli attivi sulla stessa base
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            records = [journal.get(row[0]) for row in journal.db.execute('SELECT operation_id FROM operations')]
        self.assertEqual(sorted(r['request']['idempotency_key'] for r in records), ['writer_a_001', 'writer_b_001'])
        self.assertEqual(sum('handoff' in r for r in records), 1)

    def test_second_process_holding_the_vault_lock_yields_vault_busy_and_loses_nothing(self):
        self.server.skills.adapters['fake'] = ops.FakeAdapter()
        before = capture_snapshot(self.root).digest
        process = self.holder()
        status, _, raw = self.request('POST', self.base + 'operations', self.lint('blocked_writer'))
        self.assertEqual(status, 409, raw)
        self.assertEqual(json.loads(raw)['error']['code'], 'vault_busy')
        self.assertEqual(capture_snapshot(self.root).digest, before)
        process.stdin.close()
        self.assertEqual(process.wait(30), 0)
        with VaultLock(self.root) as lock, Journal(lock) as journal:  # il rifiuto non ha registrato alcun ciclo
            self.assertEqual(journal.db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)
        status, _, raw = self.request('POST', self.base + 'operations', self.lint('blocked_writer'))
        self.assertEqual((status, json.loads(raw)['state']), (202, 'awaiting_client'), raw)

    @unittest.skipUnless(os.name == 'nt', 'Apply manuale Windows')
    def test_second_lint_cannot_overwrite_the_first_applied_note(self):
        first = self.prepared()
        second = self.submit('lint_second_002', kind='lint')
        self.assertEqual(second['state'], 'queued')
        applied = self.apply(first)
        self.assertEqual(applied['state'], 'succeeded', applied)
        bruno = (self.root / 'wiki/Bruno.md').read_bytes()
        self.assertIn(b'Modifica revisionata.', bruno)
        self.server.skills.dispatch(self.vault_id, {})
        late = self.get('operations/' + second['operation_id'])[2]
        self.assertEqual((late['state'], late['error']['code']), ('blocked_external_change', 'blocked_external_change'), late)
        self.assertEqual((self.root / 'wiki/Bruno.md').read_bytes(), bruno)  # nessun lost update
        self.assertEqual(self.get('operations/' + first['operation_id'])[2]['state'], 'succeeded')  # entrambi gli esiti registrati


class HostileCandidates(Env):
    def check(self):
        receiver = Receiver(self.service.registry, self.service)
        self.addCleanup(receiver.close)
        return receiver, receiver.check(self.vault)

    def assert_untouched(self, before):
        self.assertEqual((self.git('rev-parse', 'HEAD'), capture_snapshot(self.root).digest), before)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertFalse(any(self.root.rglob('EXECUTED*')), 'nessun file ricevuto è stato eseguito')
        self.assertFalse((self.root / '.teseo/local/git-candidates').exists(), 'nessun candidato importato')

    def reject(self, path, data, mode=None):
        before = (self.git('rev-parse', 'HEAD'), capture_snapshot(self.root).digest)
        self.peer_write(path, data(parse_json((self.root / '.teseo/project.json').read_bytes())), 'ostile', mode)
        receiver, status = self.check()
        self.assertEqual(status['state'], 'incompatible', status)
        self.assertIn(status['error']['code'], ('git_history_policy', 'unsupported_version', 'kit_too_old'))
        self.assertIsNone(status['preview'])
        self.assertIsNone(status.get('candidate_digest'))
        self.assert_untouched(before)
        # L'apply non ha nulla da adottare: mai su una revisione ostile, nemmeno con parametri forzati.
        body = dict(exclusive_confirmed=True, expected_head=before[0], pending_oid=self.tip(), expected_digest='0' * 64)
        with self.assertRaises(ContractError):
            ReceiverApplyService(self.service.registry, self.service, receiver).apply(self.vault, body)
        self.assert_untouched(before)

    def test_publisher_integration_refuses_hostile_remote_without_staging_or_push(self):
        self.p.page(self.root, 'Anna', 'Locale')
        body = self.p.validated()
        remote_commit = self.peer_write('raw/run.py', b"open('EXECUTED','w').write('x')\n", 'script')
        result = self.service.publish(self.vault, body)
        self.assertEqual(result['state'], 'needs_resolution', result)
        self.assertIn(result['error']['code'], ('git_tracked_policy', 'git_unsafe_tree'))
        self.assertEqual(self.tip(), remote_commit)
        self.assertFalse(any(self.root.rglob('EXECUTED*')))
        self.assertFalse((self.root / '.teseo/local/git-candidates').exists())
        self.assertEqual(self.git('rev-parse', 'HEAD'), result['L'])


SCRIPT = b"open('EXECUTED','w').write('x')" + bytes([10])
CASES = {'manifest_' + field: ('.teseo/project.json', lambda m, f=field: canonical_json(dict(m, **{f: SUPPORTED_VERSIONS[f] + 1})), None)
         for field in SUPPORTED_VERSIONS}
CASES.update(kit_too_old=('.teseo/project.json', lambda m: canonical_json(dict(m, minimum_kit_version='99.0.0')), None),
             modo_eseguibile=('wiki/Anna.md', lambda m: b'# A' + bytes([10]), 'x'))
CASES.update({'script_' + name.replace('.', '_'): ('raw/' + name, lambda m: SCRIPT, None) for name in ('run.py', 'run.js', 'run.bat')})
CASES.update(script_in_wiki=('wiki/run.py', lambda m: SCRIPT, None))
for _label, (_path, _data, _mode) in CASES.items():
    setattr(HostileCandidates, 'test_rejected_before_import_' + _label,
            lambda self, a=(_path, _data, _mode): self.reject(*a))


if __name__ == '__main__':
    unittest.main()

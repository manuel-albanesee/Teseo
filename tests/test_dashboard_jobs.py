"""Rebuild HTTP reali e iniezione guasti: preservare dati e ultima generazione."""
import json
import threading
import time
import unittest
from unittest import mock

import test_dashboard_readonly as fixture
from kit.dashboard import graph_service
from kit.dashboard.contracts import ContractError
from kit.dashboard.jobs import RebuildCoordinator, TERMINAL
from kit.dashboard.storage import VaultLock, Journal, capture_snapshot


class Jobs(unittest.TestCase):
    stop = fixture.ReadonlyHTTP.stop
    request = fixture.ReadonlyHTTP.request
    manifest = fixture.ReadonlyHTTP.manifest
    hashes = fixture.ReadonlyHTTP.hashes
    attach = fixture.ReadonlyHTTP.attach

    def setUp(self):
        fixture.ReadonlyHTTP.setUp(self)
        self.manifest()
        self.page = self.root / 'wiki/Anna.md'
        self.page.write_text('---\ntipo: persona\n---\nAnna', encoding='utf-8')
        self.identifier = self.attach()['vault_id']
        self.base = '/api/v1/vaults/' + self.identifier

    def payload(self, key='request_0001', expected=None):
        return {'idempotency_key': key, 'expected_content_revision': expected}

    def submit(self, payload=None, **options):
        status, _, body = self.request('POST', self.base + '/rebuild', payload or self.payload(), **options)
        return status, json.loads(body)

    def operation(self, identifier):
        status, _, body = self.request('GET', self.base + '/operations/' + identifier)
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def finish(self, identifier):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            record = self.operation(identifier)
            if record['state'] in TERMINAL:
                return record
            time.sleep(.02)
        self.fail('Job non concluso')

    def test_success_no_note_writes_no_code_execution_and_durable_idempotency(self):
        before = self.hashes()
        expected = capture_snapshot(self.root).digest
        status, job = self.submit(self.payload(expected=expected))
        self.assertEqual(status, 202, job)
        result = self.finish(job['operation_id'])
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(result['content_revision'], expected)
        for path, digest in before.items():
            self.assertEqual(self.hashes()[path], digest, path)
        self.assertFalse((self.root / 'EXECUTED').exists())
        other = RebuildCoordinator(self.server.registry)
        try:
            replay = other.submit(self.identifier, self.payload(expected=expected))
            self.assertEqual(replay, result)
            with self.assertRaises(ValueError) as conflict:
                other.submit(self.identifier, self.payload(expected='b' * 64))
            self.assertEqual(conflict.exception.code, 'idempotency_conflict')
        finally:
            other.close()
        self.assertEqual(len(list((self.root / '.teseo/local/snapshots').iterdir())), 1)
        status, conflict = self.submit(self.payload(expected='a' * 64))
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict['error']['code'], 'idempotency_conflict')

    def test_failed_build_keeps_old_generation_and_returns_parse_problem(self):
        graph_service.rebuild(self.root)
        marker = self.root / '.teseo/local/graph-current.json'
        previous = marker.read_bytes()
        self.page.write_text('---\ntipo: [broken\n---\n', encoding='utf-8')
        status, job = self.submit()
        self.assertEqual(status, 202, job)
        result = self.finish(job['operation_id'])
        self.assertEqual(result['state'], 'failed', result)
        self.assertEqual(result['error']['code'], 'graph_parse_failed')
        self.assertIn('Anna', result['error']['message'])
        self.assertEqual(marker.read_bytes(), previous)
        status, _, data = self.request('GET', self.base + '/graph')
        self.assertEqual(status, 200, data)

    def test_active_job_duplicate_busy_status_and_cooperative_shutdown(self):
        graph_service.rebuild(self.root)
        self.page.write_text('---\ntipo: persona\n---\nNuovo', encoding='utf-8')
        marker = self.root / '.teseo/local/graph-current.json'
        previous = marker.read_bytes()
        entered, release = threading.Event(), threading.Event()
        real = graph_service.rebuild

        def held(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test timeout')
            return real(*args, **kwargs)

        with mock.patch.object(graph_service, 'rebuild', side_effect=held):
            try:
                status, job = self.submit()
                self.assertEqual(status, 202, job)
                self.assertTrue(entered.wait(3))
                status, duplicate = self.submit()
                self.assertEqual(status, 202, duplicate)
                self.assertEqual(duplicate['operation_id'], job['operation_id'])
                self.assertEqual(self.submit(self.payload('request_0002'))[0], 409)
                # Simulate completed history filling the bounded cache while
                # this first job remains active, then submit a different vault.
                for index in range(255):
                    self.server.operations._requests[(self.identifier, f'history_{index}')] = (f'old_{index}', '')
                other = self.root / 'other-vault'
                (other / 'wiki').mkdir(parents=True)
                (other / '.teseo').mkdir()
                (other / 'Wiki reference.md').write_text('Schema', encoding='utf-8')
                (other / 'wiki/Altra.md').write_text('---\ntipo: persona\n---\nAltra', encoding='utf-8')
                manifest = json.loads((self.root / '.teseo/project.json').read_bytes())
                manifest['vault_id'] = '11111111-1111-4111-8111-111111111111'
                (other / '.teseo/project.json').write_text(json.dumps(manifest), encoding='utf-8')
                other_id = self.server.registry.attach(str(other))['vault_id']
                self.server.operations.submit(other_id, self.payload())
                status, duplicate = self.submit()
                self.assertEqual(status, 202, duplicate)
                self.assertEqual(duplicate['operation_id'], job['operation_id'])
                self.assertLessEqual(len(self.server.operations._requests), 256)
                status, _, data = self.request('GET', self.base + '/status')
                self.assertEqual(status, 200, data)
                state = json.loads(data)
                self.assertTrue(state['busy'])
                self.assertEqual(state['busy_scope'], 'service')
                self.assertTrue(state['capabilities']['rebuild'])
                self.assertEqual(self.request('GET', self.base + '/graph')[0], 200)
                self.assertEqual(self.request('POST', '/api/v1/shutdown', {})[0], 202)
                with self.assertRaises(ContractError) as stopped:
                    self.server.operations.submit(self.identifier, self.payload('request_0003'))
                self.assertEqual(stopped.exception.code, 'service_stopping')
            finally:
                release.set()
            deadline = time.monotonic() + 5
            while self.server.operations.activity(self.identifier)['busy'] and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual(self.server.operations.get(self.identifier, job['operation_id'])['state'], 'cancelled')
            self.thread.join(3)
            self.assertFalse(self.thread.is_alive())
        self.assertEqual(marker.read_bytes(), previous)

    def test_external_edit_during_build_is_blocked(self):
        first = graph_service.rebuild(self.root)
        self.page.write_text('---\ntipo: persona\n---\nBuild candidate', encoding='utf-8')
        real = graph_service._check_database
        edited = False

        def edit(path):
            nonlocal edited
            real(path)
            if not edited:
                edited = True
                self.page.write_text('---\ntipo: persona\n---\nExternal edit', encoding='utf-8')

        with mock.patch.object(graph_service, '_check_database', side_effect=edit):
            _, job = self.submit()
            record = self.finish(job['operation_id'])
        self.assertEqual(record['state'], 'blocked_external_change', record)
        self.assertIn('External edit', self.page.read_text(encoding='utf-8'))
        self.assertIn(first.generation, (self.root / '.teseo/local/graph-current.json').read_text())

    def test_stale_expected_revision_never_builds(self):
        with mock.patch.object(graph_service, 'rebuild', side_effect=AssertionError('never build')):
            status, record = self.submit(self.payload(expected='a' * 64))
        self.assertEqual(status, 202)
        self.assertEqual(record['state'], 'blocked_external_change')
        self.assertFalse((self.root / '.teseo/local/graph-current.json').exists())

    def test_semantic_failure_exposes_bounded_details_without_publishing(self):
        self.page.write_text('---\ntipo: persona\nusa: "[[Assente]]"\n---\nAnna', encoding='utf-8')
        status, job = self.submit()
        self.assertEqual(status, 202, job)
        result = self.finish(job['operation_id'])
        self.assertEqual(result['state'], 'failed', result)
        self.assertEqual(result['error']['code'], 'graph_validation_failed')
        self.assertIn('Assente', ' '.join(result['error']['details']))
        self.assertFalse((self.root / '.teseo/local/graph-current.json').exists())

    def test_interrupted_record_is_readonly_recovery_without_replay(self):
        with VaultLock(self.root) as lock, Journal(lock) as journal:
            record = journal.create('rebuild', {'expected_content_revision': None}, 'request_0001', capture_snapshot(self.root))
            journal.transition(record['operation_id'], 'waiting_lock')
            journal.transition(record['operation_id'], 'running')
        before = self.hashes()
        self.assertEqual(self.operation(record['operation_id'])['state'], 'recovery_required')
        self.assertEqual(self.hashes(), before)
        _, replay = self.submit()
        self.assertEqual(replay['operation_id'], record['operation_id'])
        self.assertEqual(replay['state'], 'recovery_required')
        self.assertFalse((self.root / '.teseo/local/graph-current.json').exists())
        _, new = self.submit(self.payload('request_0002'))
        self.assertEqual(self.finish(new['operation_id'])['state'], 'succeeded')

    def test_security_validation_legacy_lock_and_unknown_operation(self):
        for options in ({'csrf': False}, {'authenticated': False}, {'headers': {'Origin': 'https://example.com'}}):
            self.assertEqual(self.submit(**options)[0], 403)
        for payload in ({'idempotency_key': 'tiny', 'expected_content_revision': None},
                        {'idempotency_key': 'request_0001', 'expected_content_revision': '../escape'},
                        {'idempotency_key': 'request_0001', 'expected_content_revision': None, 'shell': 'run'}):
            self.assertEqual(self.submit(payload)[0], 400)
        with VaultLock(self.root):
            self.assertEqual(self.submit()[0], 409)
        self.assertEqual(self.request('GET', self.base + '/operations/no-such-id')[0], 404)
        (self.root / '.teseo/project.json').unlink()
        legacy = self.attach()['vault_id']
        self.assertEqual(self.request('POST', '/api/v1/vaults/' + legacy + '/rebuild', self.payload())[0], 422)

    def test_shutdown_requires_csrf_and_closes_listener_loop(self):
        self.assertEqual(self.request('POST', '/api/v1/shutdown', {}, csrf=False)[0], 403)
        self.assertEqual(self.request('POST', '/api/v1/shutdown', {})[0], 202)
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())


if __name__ == '__main__':
    unittest.main()

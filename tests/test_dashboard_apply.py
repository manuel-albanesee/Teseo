"""Apply/recovery reale (Windows e POSIX): snapshot, crash, race e preservazione delle note."""
import _shortpath  # noqa: F401
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard import ontology_apply
from kit.dashboard.contracts import ContractError
from kit.dashboard.graph_service import rebuild
from kit.dashboard.ontology_migrations import migrate
from kit.dashboard.storage import capture_snapshot, VaultLock


class Apply(unittest.TestCase):
    setUp = fixture.Queries.setUp
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get

    def preview(self, patch=None):
        payload = {'base_content_digest': capture_snapshot(self.root).digest,
            'idempotency_key': 'preview_' + str(time.time_ns()),
            'patch': patch or [{'op': 'adopt_types'}]}
        status, _, data = self.request('POST', self.base+'ontology/preview', payload)
        self.assertEqual(status, 200, data)
        return json.loads(data)

    def payload(self, preview, selected=None):
        return {'preview_id': preview['preview_id'], 'proposal_hash': preview['proposal_hash'],
                'selected_migrations': selected or [], 'idempotency_key': 'apply_request_001',
                'mode': 'manual_paused', 'external_writers_paused': True, 'semantic_reviewed': True}

    def submit(self, preview, payload=None, **kwargs):
        status, _, data = self.request('POST', self.base+'ontology/apply', payload or self.payload(preview),
            headers={'If-Match':'"'+preview['base_content_digest']+'"'}, **kwargs)
        return status, json.loads(data)

    def finish(self, identifier):
        for _ in range(400):
            status, _, body = self.get('operations/'+identifier)
            self.assertEqual(status, 200, body)
            if body['state'] in ('succeeded', 'failed', 'rolled_back', 'recovery_required'):
                # recovery_required may be a snapshot taken between worker release and deregistration.
                if not self.server.applies.active(self.vault_id):
                    return body
            time.sleep(.25)
        self.fail('Operazione non terminata')

    def recover(self, identifier, action):
        body = {'action': action, 'mode':'manual_paused', 'external_writers_paused':True, 'semantic_reviewed':True}
        status, _, data = self.request('POST', self.base+'operations/'+identifier+'/recover', body,
            headers={'If-Match':'"'+capture_snapshot(self.root,allow_missing_schema=True).digest+'"'})
        self.assertEqual(status, 202, data)
        return self.finish(json.loads(data)['operation_id'])

    def test_schema_apply_success_durable_replay_and_personal_raw_unchanged(self):
        preview = self.preview()
        before = self.hashes()
        status, record = self.submit(preview)
        self.assertEqual(status, 202, record)
        result = self.finish(record['operation_id'])
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(result['checkpoint']['changed_files'], ['Wiki reference.md'])
        self.assertFalse(result['checkpoint']['external_exclusion'])
        self.assertEqual(self.submit(preview)[1], result)
        for path, digest in before.items():
            if path != 'Wiki reference.md' and not path.startswith('.teseo/local/'):
                self.assertEqual(self.hashes()[path], digest, path)
        self.assertIn(b'## Tipi ammessi', (self.root/'Wiki reference.md').read_bytes())
        self.assertEqual(self.get('ontology')[1]['ETag'] is not None, True)

    def test_selected_property_rename_migrates_only_key_preserving_body_comments_newlines(self):
        original = self.page.read_bytes().replace(b'usa:', b'usa:')
        preview = self.preview([{'op':'adopt_types'},{'op':'rename_relation','name':'usa','to':'utilizza'}])
        suggestion = preview['migration_suggestions'][0]
        self.assertIn('diff', suggestion)
        payload = self.payload(preview, [suggestion['migration_id']])
        status, record = self.submit(preview, payload)
        self.assertEqual(status, 202, record)
        self.assertEqual(self.finish(record['operation_id'])['state'], 'succeeded')
        self.assertEqual(self.page.read_bytes(), original.replace(b'\nusa:', b'\nutilizza:', 1))

    def test_partial_or_unknown_migration_selection_rejected_before_live_writes(self):
        preview = self.preview([{'op':'adopt_types'},{'op':'rename_relation','name':'usa','to':'utilizza'}])
        before = capture_snapshot(self.root).digest
        self.assertEqual(self.submit(preview)[1]['error']['code'], 'migration_invalid')
        self.assertEqual(self.submit(preview, self.payload(preview, ['unknown']))[0], 400)
        self.assertEqual(capture_snapshot(self.root).digest, before)

    def test_expired_stale_wrong_hash_if_match_and_missing_confirmations_fail(self):
        preview = self.preview()
        before = capture_snapshot(self.root).digest
        payload = self.payload(preview)
        payload['external_writers_paused'] = False
        self.assertEqual(self.submit(preview, payload)[0], 422)
        payload = self.payload(preview);payload['proposal_hash']='0'*64
        self.assertEqual(self.submit(preview,payload)[1]['error']['code'],'preview_stale')
        status, _, _ = self.request('POST',self.base+'ontology/apply',self.payload(preview))
        self.assertEqual(status,428)
        self.page.write_bytes(self.page.read_bytes()+b'\nExternal edit')
        self.assertEqual(self.submit(preview)[1]['error']['code'],'preview_stale')
        self.assertNotEqual(capture_snapshot(self.root).digest,before)

    def test_interrupted_replace_has_explicit_finish_or_rollback_and_old_marker(self):
        for action in ('finish','rollback'):
            preview = self.preview()
            original = (self.root/'Wiki reference.md').read_bytes()
            marker = (self.root/'.teseo/local/graph-current.json').read_bytes()
            with mock.patch.object(ontology_apply,'_replace',side_effect=OSError('fault')):
                status, record = self.submit(preview,dict(self.payload(preview),idempotency_key='fault_'+action))
                self.assertEqual(status,202,record)
                interrupted=self.finish(record['operation_id'])
            self.assertEqual(interrupted['state'],'recovery_required',interrupted)
            self.assertEqual((self.root/'.teseo/local/graph-current.json').read_bytes(),marker)
            with self.assertRaises(ContractError) as error:
                rebuild(self.root)
            self.assertEqual(error.exception.code,'recovery_required')
            result=self.recover(record['operation_id'],action)
            self.assertEqual(result['state'],'succeeded' if action=='finish' else 'rolled_back',result)
            if action=='rollback':
                self.assertEqual((self.root/'Wiki reference.md').read_bytes(),original)
            else:
                # Restore the synthetic schema for the second independent scenario.
                (self.root/'Wiki reference.md').write_bytes(original);rebuild(self.root)

    def test_race_between_check_and_replace_keeps_foreign_bytes_and_blocks_recovery(self):
        preview=self.preview();real=ontology_apply._replace
        def race(target,staged,backup):
            target.write_bytes(b'Foreign editor data, preserve exactly')
            return real(target,staged,backup)
        with mock.patch.object(ontology_apply,'_replace',side_effect=race):
            _,record=self.submit(preview);result=self.finish(record['operation_id'])
        self.assertEqual(result['state'],'recovery_required',result)
        self.assertEqual(result['error']['code'],'recovery_conflict')
        copies=list((self.root/'.teseo/local/transactions').rglob('displaced'))
        self.assertTrue(any(path.read_bytes()==b'Foreign editor data, preserve exactly' for path in copies))
        self.assertEqual(self.recover(record['operation_id'],'rollback')['error']['code'],'recovery_conflict')

    def test_recovery_never_overwrites_further_external_edit(self):
        preview=self.preview()
        with mock.patch.object(ontology_apply,'_replace',side_effect=OSError('fault')):
            _,record=self.submit(preview);self.finish(record['operation_id'])
        self.page.write_bytes(b'External change after failure')
        before=self.hashes()
        self.assertEqual(self.recover(record['operation_id'],'finish')['error']['code'],'recovery_conflict')
        self.assertEqual(self.page.read_bytes(),b'External change after failure')

    def test_native_backup_crash_window_is_recoverable(self):
        preview=self.preview();real=ontology_apply._replace
        def interrupted(target,staged,backup):
            real(target,staged,backup)
            raise OSError('crash after rename before checkpoint')
        with mock.patch.object(ontology_apply,'_replace',side_effect=interrupted):
            _,record=self.submit(preview);result=self.finish(record['operation_id'])
        self.assertEqual(result['state'],'recovery_required')
        self.assertEqual(self.recover(record['operation_id'],'rollback')['state'],'rolled_back')

    def test_get_is_readonly_and_shared_events_are_never_applied(self):
        directory=self.root/'.teseo/shared/events';directory.mkdir(parents=True)
        (directory/'event.json').write_text('{"opaque":true}',encoding='utf-8')
        preview=self.preview();before=capture_snapshot(self.root).digest
        self.assertEqual(self.submit(preview)[1]['error']['code'],'shared_mapping_unavailable')
        self.assertEqual(capture_snapshot(self.root).digest,before)
        self.assertFalse(self.get('status')[2]['capabilities']['ontology_apply_automatic'])

    def test_concurrent_duplicate_and_conflict_share_one_operation(self):
        preview=self.preview()
        entered,release=__import__('threading').Event(),__import__('threading').Event()
        real=ontology_apply.execute
        def held(*args,**kwargs):
            entered.set();release.wait(10);return real(*args,**kwargs)
        with mock.patch.object(ontology_apply,'execute',side_effect=held):
            try:
                status,first=self.submit(preview);self.assertEqual(status,202,first)
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.submit(preview)[1]['operation_id'],first['operation_id'])
                different=dict(self.payload(preview),selected_migrations=['different'])
                self.assertEqual(self.submit(preview,different)[1]['error']['code'],'idempotency_conflict')
            finally:release.set()
            self.assertEqual(self.finish(first['operation_id'])['state'],'succeeded')

    def test_active_recovery_is_not_reported_as_terminal_before_worker_finishes(self):
        preview=self.preview()
        with mock.patch.object(ontology_apply,'execute',side_effect=OSError('prepare only')):
            _,record=self.submit(preview);self.finish(record['operation_id'])
        import threading
        entered,release=threading.Event(),threading.Event()
        real=ontology_apply.execute
        def held(*args,**kwargs):
            entered.set();release.wait(10);return real(*args,**kwargs)
        with mock.patch.object(ontology_apply,'execute',side_effect=held):
            body={'action':'rollback','mode':'manual_paused','external_writers_paused':True,'semantic_reviewed':True}
            try:
                status,_,_=self.request('POST',self.base+'operations/'+record['operation_id']+'/recover',body,
                    headers={'If-Match':'"'+capture_snapshot(self.root).digest+'"'})
                self.assertEqual(status,202)
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.get('operations/'+record['operation_id'])[2]['state'],'running')
            finally:release.set()
            self.assertEqual(self.finish(record['operation_id'])['state'],'rolled_back')

    def test_real_process_crash_after_first_note_replace_rolls_back(self):
        preview=self.preview([{'op':'adopt_types'},{'op':'rename_relation','name':'usa','to':'utilizza'}])
        payload=self.payload(preview,[preview['migration_suggestions'][0]['migration_id']])
        original=self.page.read_bytes()
        with mock.patch.object(ontology_apply,'execute',side_effect=OSError('prepare only')):
            _,record=self.submit(preview,payload);self.finish(record['operation_id'])
        script='''
import os,sys
from kit.dashboard import ontology_apply as a
from kit.dashboard.storage import Journal,VaultLock
real=a._replace
def crash(*args):
    real(*args)
    os._exit(23)
a._replace=crash
with VaultLock(sys.argv[1]) as lock,Journal(lock) as journal:
    a.execute(journal,sys.argv[2])
'''
        child=subprocess.run([sys.executable,'-c',script,str(self.root),record['operation_id']],cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=20)
        self.assertEqual(child.returncode,23,child.stderr.decode('utf-8','replace'))
        self.assertNotEqual(self.page.read_bytes(),original)
        self.assertEqual(self.recover(record['operation_id'],'rollback')['state'],'rolled_back')
        self.assertEqual(self.page.read_bytes(),original)

    def test_missing_schema_after_native_partial_failure_remains_recoverable(self):
        preview=self.preview()
        original=(self.root/'Wiki reference.md').read_bytes()
        def partial(target,staged,backup):
            os.rename(target,backup)
            raise OSError('ReplaceFile error 1177 simulation')
        with mock.patch.object(ontology_apply,'_replace',side_effect=partial):
            _,record=self.submit(preview);self.finish(record['operation_id'])
        self.assertFalse((self.root/'Wiki reference.md').exists())
        from kit.dashboard.readonly import VaultRegistry
        other=VaultRegistry()
        self.assertEqual(other.attach(str(self.root))['compatibility'],'recovery_required')
        before=self.hashes()
        status,_,records=self.get('operations')
        self.assertEqual(status,200,records)
        self.assertEqual(records['operations'][0]['operation_id'],record['operation_id'])
        self.assertEqual(self.hashes(),before)
        self.assertEqual(self.recover(record['operation_id'],'rollback')['state'],'rolled_back')
        self.assertEqual((self.root/'Wiki reference.md').read_bytes(),original)

    def test_apply_auth_csrf_and_expiry_guards(self):
        preview=self.preview()
        for options in ({'authenticated':False},{'csrf':False}):
            self.assertEqual(self.submit(preview,**options)[0],403)
        self.server.previews._cache={key:(0,value[1],value[2]) for key,value in self.server.previews._cache.items()}
        self.assertEqual(self.submit(preview)[1]['error']['code'],'preview_stale')

    def test_platform_gate_cooperative_lock_does_not_exclude_external_writer(self):
        original=self.page.read_bytes()
        with VaultLock(self.root):
            child=subprocess.run([sys.executable,'-c',
                'from pathlib import Path;import sys;Path(sys.argv[1]).write_bytes(b"external writer under cooperative lock")',
                str(self.page)],capture_output=True,timeout=10)
            self.assertEqual(child.returncode,0,child.stderr.decode('utf-8','replace'))
            self.assertNotEqual(self.page.read_bytes(),original)
        self.assertFalse(self.get('status')[2]['capabilities']['external_writer_exclusion'])
        self.assertFalse(self.get('status')[2]['capabilities']['ontology_apply_automatic'])


class ByteMigrations(unittest.TestCase):
    def test_type_scalar_quotes_bom_crlf_and_opaque_body(self):
        raw='\ufeff---\r\ntipo: "persona" # conserva\r\n---\r\nTesto persona intatto'.encode()
        item={'kind':'rename_type','from':'persona','to':'individuo','page':'wiki/Anna.md'}
        self.assertEqual(migrate(raw,item),raw.replace(b'"persona"',b'"individuo"',1))

    def test_duplicate_quoted_keys_and_anchors_are_manual(self):
        item={'kind':'rename_relation','from':'usa','to':'utilizza','page':'wiki/Anna.md'}
        for raw in ('---\nusa: "[[A]]"\n"usa": "[[B]]"\n---\n', '---\nusa: &x "[[A]]"\n---\n'):
            with self.assertRaises(ContractError):migrate(raw.encode(),item)

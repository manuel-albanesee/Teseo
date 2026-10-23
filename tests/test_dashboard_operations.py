"""Cicli skill: HTTP reale, copia isolata, ricevute e nessun client AI avviato."""
import json
from pathlib import Path
import unittest
import sqlite3
import time
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard.client_receipt import create_receipt
from kit.dashboard.storage import capture_snapshot
from kit.dashboard import ontology_apply


class FakeAdapter:
    def prepare(self,workspace,request_path,request,phase):
        return {'workspace':str(workspace),'request_path':str(request_path),'phase':phase,'mode':'deterministic_test'}

    def cancel(self,record):
        return {'cancelled':True}


class Operations(unittest.TestCase):
    setUp=fixture.Queries.setUp
    stop=fixture.Queries.stop
    request=fixture.Queries.request
    manifest=fixture.Queries.manifest
    hashes=fixture.Queries.hashes
    attach=fixture.Queries.attach
    get=fixture.Queries.get

    def submit(self,key='operation_001',kind='ingest_lint',adapter='fake',scope=None):
        self.server.skills.adapters['fake']=FakeAdapter()
        body={'kind':kind,'inputs':['raw/fonte.py'] if kind=='ingest_lint' else [],
              'scope':scope or ['wiki/','Wiki reference.md','index.md','log.md'],
              'base_content_digest':capture_snapshot(self.root).digest,'adapter':adapter,'idempotency_key':key}
        status,_,raw=self.request('POST',self.base+'operations',body)
        self.assertEqual(status,202,raw)
        return json.loads(raw)

    def receipt(self,record,outcome='succeeded',reason=''):
        return create_receipt(record['handoff']['request_path'],outcome,reason)

    def complete(self,record,receipt=None,status=200):
        code,_,raw=self.request('POST',self.base+'operations/'+record['operation_id']+'/complete',{'receipt':receipt or self.receipt(record)})
        self.assertEqual(code,status,raw)
        return json.loads(raw)

    def test_dispatch_snapshot_phase_receipt_and_durable_duplicate(self):
        before=capture_snapshot(self.root).digest
        first=self.submit()
        self.assertEqual(first['state'],'awaiting_client')
        self.assertEqual(first['phase'],'ingest')
        self.assertEqual(self.submit()['operation_id'],first['operation_id'])
        self.assertEqual(capture_snapshot(self.root).digest,before)
        receipt=self.receipt(first)
        next_phase=self.complete(first,receipt)
        self.assertEqual(next_phase['phase'],'lint')
        self.assertEqual(next_phase['phases']['ingest'],'succeeded')
        self.assertEqual(self.complete(first,receipt),next_phase)
        changed=dict(receipt,reason='different')
        self.complete(first,changed,status=409)
        self.assertNotIn(receipt['token'],json.dumps(next_phase))

    def test_forged_and_changed_manifest_receipts_rejected(self):
        first=self.submit()
        receipt=self.receipt(first)
        self.complete(first,dict(receipt,token='forged'),status=403)
        self.complete(first,dict(receipt,files={}),status=409)
        self.assertEqual(self.get('operations/'+first['operation_id'])[2]['phase'],'ingest')

    def test_queue_cancel_and_explicit_refusal_without_relaunch(self):
        first=self.submit()
        second=self.submit('operation_002',kind='lint')
        self.assertEqual(second['state'],'queued')
        paused=self.complete(first,self.receipt(first,'awaiting_user','Serve consenso'))
        self.assertEqual(paused['state'],'awaiting_user')
        status,_,raw=self.request('POST',self.base+'operations/'+first['operation_id']+'/resume',{'decision':'refuse'})
        self.assertEqual(status,200,raw)
        self.assertEqual(json.loads(raw)['state'],'cancelled')
        self.assertEqual(self.get('operations/'+second['operation_id'])[2]['state'],'awaiting_client')
        self.assertFalse(self.get('operations/'+first['operation_id'])[2]['publication_eligible'])

    def test_failed_lint_does_not_inherit_ingest_success(self):
        first=self.submit()
        lint=self.complete(first)
        failed=self.complete(lint,self.receipt(lint,'failed','Lint fallito'))
        self.assertEqual(failed['phases'],{'ingest':'succeeded','lint':'failed'})
        self.assertEqual(failed['state'],'failed')
        self.assertFalse(failed['publication_eligible'])

    def test_auth_and_no_fake_adapter_from_default_api(self):
        status,_,_=self.request('POST',self.base+'operations',{},authenticated=False)
        self.assertEqual(status,403)
        status,_,_=self.request('POST',self.base+'operations',{},csrf=False)
        self.assertEqual(status,403)
        self.assertNotIn('fake',self.server.skills.adapters)

    def test_stop_does_not_certify_pending_client(self):
        first=self.submit()
        self.server.skills.request_stop()
        status,_,_=self.request('POST',self.base+'operations/'+first['operation_id']+'/complete',{'receipt':self.receipt(first)})
        self.assertEqual(status,503)
        self.assertEqual(self.get('operations/'+first['operation_id'])[2]['state'],'awaiting_client')
        self.assertFalse(self.get('operations/'+first['operation_id'])[2]['publication_eligible'])

    def prepared(self,new_page=False,scope=None):
        job=self.submit(kind='lint',scope=scope)
        workspace=Path(job['handoff']['workspace'])
        note=workspace/'wiki/Bruno.md'
        note.write_bytes(note.read_bytes()+b'\nModifica revisionata.\n')
        if new_page:
            (workspace/'wiki/Nuova.md').write_text('---\ntipo: persona\n---\n[[Bruno]]',encoding='utf-8')
        result=self.complete(job)
        self.assertEqual(result['state'],'prepared',result)
        self.assertFalse(result['publication_eligible'])
        return result

    def apply(self,job):
        status,_,raw=self.request('POST',self.base+'operations/'+job['operation_id']+'/apply',
             {'mode':'manual_paused','external_writers_paused':True,'semantic_reviewed':True},
             headers={'If-Match':'"'+job['base_content_digest']+'"'})
        self.assertEqual(status,202,raw)
        for _ in range(120):
            if not self.server.applies.active(self.vault_id):break
            time.sleep(.1)
        return self.get('operations/'+job['operation_id'])[2]

    def test_full_ingest_lint_prepares_without_live_mutations_then_apply_emits_one_event(self):
        before=capture_snapshot(self.root).digest
        job=self.submit()
        lint=self.complete(job)
        workspace=Path(lint['handoff']['workspace'])
        note=workspace/'wiki/Bruno.md';note.write_bytes(note.read_bytes()+b'\nOutput ingest e lint.\n')
        ready=self.complete(lint)
        self.assertEqual(ready['state'],'prepared',ready)
        self.assertEqual(capture_snapshot(self.root).digest,before)
        self.assertFalse(ready['publication_eligible'])
        result=self.apply(ready)
        self.assertEqual(result['state'],'succeeded',result)
        self.assertTrue(result['publication_eligible'])
        self.assertTrue(result['validation']['checks']['synthesis'])
        self.assertEqual(self.apply(result)['state'],'succeeded')
        db=sqlite3.connect(self.root/'.teseo/local/operations.sqlite')
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM validated_events').fetchone()[0],1)
            event=json.loads(db.execute('SELECT event FROM validated_events').fetchone()[0])
            self.assertEqual(event['type'],'operation.validated')
            self.assertEqual(event['manifest']['files'][0]['path'],'wiki/Bruno.md')
        finally:db.close()

    def test_raw_mutation_out_of_scope_alias_and_link_errors_block_preparation(self):
        cases=[('raw/fonte.py',b'altered','immutable_raw_changed'),
               ('wiki/Bruno.md',b'---\ntipo: persona\n---\n[[Missing]]','candidate_invalid'),
               ('index.md',b'foreign scope','scope_violation'),
               ('wiki/Bruno.md',b'---\ntipo: persona\naliases: [Anni]\n---\nBruno','candidate_invalid')]
        for index,(path,data,error) in enumerate(cases):
            job=self.submit('invalid_case_'+str(index),kind='lint',scope=['wiki/'])
            (Path(job['handoff']['workspace'])/path).write_bytes(data)
            failed=self.complete(job)
            self.assertEqual(failed['state'],'failed',failed)
            self.assertEqual(failed['error']['code'],error,failed)
            self.assertFalse(failed['publication_eligible'])

    def test_external_change_between_validation_and_apply_never_overwrites(self):
        job=self.prepared()
        self.page.write_bytes(b'External change to preserve')
        status,_,raw=self.request('POST',self.base+'operations/'+job['operation_id']+'/apply',
             {'mode':'manual_paused','external_writers_paused':True,'semantic_reviewed':True},
             headers={'If-Match':'"'+job['base_content_digest']+'"'})
        self.assertEqual(status,409,raw)
        self.assertEqual(self.page.read_bytes(),b'External change to preserve')

    def test_new_note_crash_and_rollback_preserve_added_bytes_in_backup(self):
        before=capture_snapshot(self.root).digest
        job=self.prepared(new_page=True)
        from kit.dashboard import graph_service
        real=graph_service.rebuild
        def fault(root,*args,**kwargs):
            if root==self.root: raise OSError('fault after all Markdown writes')
            return real(root,*args,**kwargs)
        with mock.patch.object(graph_service,'rebuild',side_effect=fault):
            interrupted=self.apply(job)
        self.assertEqual(interrupted['state'],'recovery_required')
        self.assertTrue((self.root/'wiki/Nuova.md').exists())
        status,_,raw=self.request('POST',self.base+'operations/'+job['operation_id']+'/recover',
            {'action':'rollback','mode':'manual_paused','external_writers_paused':True,'semantic_reviewed':True},
            headers={'If-Match':'"'+capture_snapshot(self.root).digest+'"'})
        self.assertEqual(status,202,raw)
        for _ in range(120):
            if not self.server.applies.active(self.vault_id):break
            time.sleep(.1)
        self.assertEqual(self.get('operations/'+job['operation_id'])[2]['state'],'rolled_back')
        self.assertEqual(capture_snapshot(self.root).digest,before)

    def test_shared_response_receipt_rejected_and_synthesis_invalid(self):
        job=self.submit(kind='lint')
        receipt=self.receipt(job);receipt['processed_response_ids']=['answer-1']
        self.complete(job,receipt,status=422)
        workspace=Path(job['handoff']['workspace'])
        (workspace/'wiki/Nuova.md').write_text('---\ntipo: persona\ntags: [entropia]\n---\nSenza avviso [[Bruno]]',encoding='utf-8')
        failed=self.complete(job)
        self.assertEqual(failed['state'],'failed')
        self.assertEqual(failed['error']['code'],'synthesis_invalid')

    def test_partial_lint_and_duplicate_after_new_coordinator_are_explicit(self):
        job=self.prepared(scope=['wiki/Bruno.md'])
        self.assertEqual(job['validation']['lint_scope'],'partial')
        self.assertIn('human review',job['validation']['semantic_assurance'])
        from kit.dashboard.operations import SkillCoordinator
        other=SkillCoordinator(self.server.registry,{'fake':FakeAdapter()})
        self.server.skills=other
        self.assertEqual(self.submit(kind='lint',scope=['wiki/Bruno.md'])['operation_id'],job['operation_id'])

    def test_manifest_deletion_new_raw_and_workspace_scripts_are_not_authorized(self):
        cases=[('manifest','manifest_changed'),('delete','page_mapping_unavailable'),('raw','input_not_selected')]
        for index,(mode,code) in enumerate(cases):
            job=self.submit('boundary_case_'+str(index),kind='lint')
            workspace=Path(job['handoff']['workspace'])
            if mode=='manifest':
                path=workspace/'.teseo/project.json';value=json.loads(path.read_bytes());value['label']='changed';path.write_text(json.dumps(value),encoding='utf-8')
            elif mode=='delete':(workspace/'wiki/Bruno.md').unlink()
            else:(workspace/'raw/new.txt').write_bytes(b'not selected')
            result=self.complete(job)
            self.assertEqual(result['error']['code'],code,result)
        job=self.submit('workspace_script_case',kind='lint')
        workspace=Path(job['handoff']['workspace']);(workspace/'.graph').mkdir()
        (workspace/'.graph/build_graph.py').write_text("raise RuntimeError('never execute')",encoding='utf-8')
        self.assertEqual(self.complete(job)['state'],'prepared')

    def test_timeout_and_explicit_continue_consume_new_phase_capability(self):
        job=self.submit()
        old=self.receipt(job,'awaiting_user','Serve dialogo')
        paused=self.complete(job,old)
        status,_,raw=self.request('POST',self.base+'operations/'+job['operation_id']+'/resume',{'decision':'continue'})
        self.assertEqual(status,200,raw)
        continued=json.loads(raw)
        self.assertNotEqual(self.receipt(continued)['token'],old['token'])
        self.assertEqual(self.complete(continued)['phase'],'lint')
        from kit.dashboard.storage import VaultLock,Journal
        with VaultLock(self.root) as lock,Journal(lock) as journal:
            record=journal.get(job['operation_id']);record['expires_at']=0;journal._save(record)
        result=self.complete(continued)
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['error']['code'],'operation_timeout')

    def test_initial_job_configuration_is_atomic_and_persistent(self):
        job=self.submit()
        from kit.dashboard.storage import VaultLock,Journal
        with VaultLock(self.root) as lock,Journal(lock) as journal:
            record=journal.get(job['operation_id'])
            self.assertEqual(record['request']['adapter'],'fake')
            self.assertIn('receipts',record)
            self.assertEqual(record['phases']['ingest'],'awaiting_client')
        from kit.dashboard.operations import SkillCoordinator
        fresh=SkillCoordinator(self.server.registry,{'fake':FakeAdapter()})
        old=self.server.skills;self.server.skills=fresh
        self.assertEqual(self.complete(job)['phase'],'lint')
        self.assertFalse(fresh._stop)

    def test_receipt_route_has_explicit_larger_bound_without_expanding_job_requests(self):
        job=self.submit()
        receipt=self.receipt(job);receipt['checks']={'client_report':'x'*17000}
        self.assertEqual(self.complete(job,receipt)['phase'],'lint')
        status,_,_=self.request('POST',self.base+'operations',{'padding':'x'*17000})
        self.assertEqual(status,400)

    def test_failure_before_atomic_event_commit_remains_recoverable(self):
        job=self.prepared()
        from kit.dashboard.storage import Journal
        with mock.patch.object(Journal,'complete_skill',side_effect=OSError('event transaction unavailable')):
            interrupted=self.apply(job)
        self.assertEqual(interrupted['state'],'recovery_required')
        self.assertFalse(interrupted['publication_eligible'])
        status,_,raw=self.request('POST',self.base+'operations/'+job['operation_id']+'/recover',
            {'action':'finish','mode':'manual_paused','external_writers_paused':True,'semantic_reviewed':True},
            headers={'If-Match':'"'+capture_snapshot(self.root).digest+'"'})
        self.assertEqual(status,202,raw)
        for _ in range(120):
            if not self.server.applies.active(self.vault_id):break
            time.sleep(.1)
        completed=self.get('operations/'+job['operation_id'])[2]
        self.assertEqual(completed['state'],'succeeded',completed)
        self.assertTrue(completed['publication_eligible'])

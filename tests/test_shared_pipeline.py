"""Checkpoint note/eventi: UUID espliciti, risposte sopraggiunte e recovery."""
import _shortpath  # noqa: F401
import json
from contextlib import closing
from pathlib import Path
import subprocess
import sqlite3
import sys
import time
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

import test_dashboard_operations as fixture
from kit.dashboard.client_receipt import create_receipt
from kit.dashboard.contracts import canonical_json, ContractError
from kit.dashboard.shared_state import snapshot_events, validate_snapshot
from kit.dashboard.storage import capture_snapshot, Journal


class SharedPipeline(unittest.TestCase):
    # Full snapshot + synthesis validation is synchronous and has a 60s service bound.
    request_timeout=30
    setUp=fixture.Operations.setUp
    stop=fixture.Operations.stop
    request=fixture.Operations.request
    manifest=fixture.Operations.manifest
    hashes=fixture.Operations.hashes
    attach=fixture.Operations.attach
    get=fixture.Operations.get
    submit=fixture.Operations.submit
    complete=fixture.Operations.complete
    receipt=fixture.Operations.receipt
    apply=fixture.Operations.apply

    def answer(self,text='Anna decide',question=None,key=None):
        result=self.server.shared.record(self.vault_id,{'question_id':question,'question_text':'Chi decide?',
            'pages':['Anna Rossi'],'text':text,'idempotency_key':key or str(uuid4()),'share_confirmed':True})
        state=self.server.shared.answers(self.vault_id)
        return next(a for a in state['answers'] if a['event_id'] in result['event_ids'])

    def candidate(self,job,text):
        workspace=Path(job['handoff']['workspace'])
        path=workspace/'wiki/Anna Rossi.md'
        path.write_bytes(path.read_bytes()+('\n'+text+'\n').encode('utf-8'))
        return workspace

    def selected_receipt(self,job,ids):
        return create_receipt(job['handoff']['request_path'],'succeeded',answer_ids=ids,operation_id=job['operation_id'])

    def recover(self,job,action):
        code,_,raw=self.request('POST',self.base+'operations/'+job['operation_id']+'/recover',
            {'action':action,'mode':'manual_paused','external_writers_paused':True,'semantic_reviewed':True},
            headers={'If-Match':'"'+capture_snapshot(self.root).digest+'"'})
        self.assertEqual(code,202,raw)
        for _ in range(150):
            if not self.server.applies.active(self.vault_id):break
            time.sleep(.1)
        return self.get('operations/'+job['operation_id'])[2]

    def test_new_answer_during_lint_stays_pending_and_checkpoint_binds_selected_uuid(self):
        first=self.answer()
        job=self.submit(kind='lint')
        self.candidate(job,first['text'])
        later=self.answer('Bruno decide',first['question_id'])
        receipt=self.selected_receipt(job,[first['entity_id']])
        prepared=self.complete(job,receipt)
        self.assertEqual(prepared['state'],'prepared',prepared)
        self.assertNotEqual(prepared['base_content_digest'],job['base_content_digest'])
        self.assertEqual(self.complete(job,receipt)['operation_id'],job['operation_id'])
        result=self.apply(prepared)
        self.assertEqual(result['state'],'succeeded',result)
        answers={a['entity_id']:a for a in self.server.shared.answers(self.vault_id)['answers']}
        self.assertEqual(answers[first['entity_id']]['state'],'consolidated')
        self.assertTrue(answers[first['entity_id']]['applied'])
        self.assertEqual(answers[later['entity_id']]['state'],'archived')
        self.assertFalse(answers[later['entity_id']]['applied'])
        events=snapshot_events(capture_snapshot(self.root),self.vault_id)
        markers=[e for e in events if e['kind']=='answer.consolidated']
        self.assertEqual(len(markers),1)
        self.assertEqual(markers[0]['payload']['answer_ids'],[first['entity_id']])
        self.assertEqual(markers[0]['payload']['checkpoint_id'],result['checkpoint']['checkpoint_id'])

    def test_notes_and_sources_must_support_selected_response(self):
        first=self.answer()
        job=self.submit(kind='lint')
        self.candidate(job,'Testo diverso dalla risposta')
        result=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        self.assertEqual(result['state'],'failed',result)
        self.assertEqual(result['error']['code'],'answer_not_supported')
        self.assertEqual(len(snapshot_events(capture_snapshot(self.root),self.vault_id)),2)

    def test_live_note_change_or_new_decision_blocks_rebase(self):
        first=self.answer()
        job=self.submit(kind='lint');self.candidate(job,first['text'])
        state=self.server.shared.answers(self.vault_id)
        self.server.shared.decision(self.vault_id,{'question_id':first['question_id'],'heads':state['questions'][0]['heads'],
            'decision':'accepted','reason':'Nuova decisione da rispettare','idempotency_key':'decision_late_001','share_confirmed':True})
        result=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        self.assertEqual(result['state'],'blocked_external_change',result)
        job=self.submit('new_cycle_002',kind='lint');self.candidate(job,first['text'])
        self.page.write_bytes(self.page.read_bytes()+b'\nForeign edit')
        result=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        self.assertEqual(result['state'],'blocked_external_change',result)

    def test_client_may_not_write_shared_events_and_unknown_ids_are_rejected(self):
        first=self.answer()
        job=self.submit(kind='lint')
        workspace=self.candidate(job,first['text'])
        event_path=next((workspace/'.teseo/shared/events').glob('*.json'))
        event=json.loads(event_path.read_bytes());event['created_at']='2025-01-01T00:00:00Z';event_path.write_bytes(canonical_json(event))
        result=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        self.assertEqual(result['error']['code'],'event_write_forbidden')
        job=self.submit('unknown_uuid_002',kind='lint');self.candidate(job,first['text'])
        result=self.complete(job,self.selected_receipt(job,[str(uuid4())]),status=422)
        self.assertEqual(result['error']['code'],'invalid_response_ids')

    def test_crash_before_checkpoint_never_marks_answers_applied_and_rollback_rebuilds_cache(self):
        first=self.answer();before=capture_snapshot(self.root).digest
        job=self.submit(kind='lint');self.candidate(job,first['text'])
        ready=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        with mock.patch.object(Journal,'complete_skill',side_effect=OSError('checkpoint unavailable')):
            interrupted=self.apply(ready)
        self.assertEqual(interrupted['state'],'recovery_required')
        with self.assertRaises(ContractError):self.server.shared.answers(self.vault_id)
        rolled=self.recover(ready,'rollback')
        self.assertEqual(rolled['state'],'rolled_back')
        self.assertEqual(capture_snapshot(self.root).digest,before)
        self.assertEqual(self.server.shared.answers(self.vault_id)['answers'][0]['state'],'archived')
        self.assertEqual(self.server.shared.import_state(self.vault_id,{})['event_count'],2)

    def test_projection_failure_after_marker_can_replay_without_reapplying_notes(self):
        first=self.answer();job=self.submit(kind='lint');self.candidate(job,first['text'])
        ready=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        with mock.patch('kit.dashboard.shared_state.rebuild_projection',side_effect=OSError('cache unavailable')):
            result=self.apply(ready)
        self.assertEqual(result['state'],'succeeded')
        before=capture_snapshot(self.root).digest
        self.assertTrue(self.server.shared.answers(self.vault_id)['answers'][0]['applied'])
        self.assertEqual(self.server.shared.import_state(self.vault_id,{})['answers'][0]['state'],'consolidated')
        self.assertEqual(capture_snapshot(self.root).digest,before)

    def test_client_deleted_during_helper_is_detected(self):
        job=self.submit(kind='lint');workspace=self.candidate(job,'Revisione')
        def helper(*args,**kwargs):
            (workspace/'wiki/Équipe.md').unlink()
            return subprocess.CompletedProcess([],0,b'{}',b'')
        with mock.patch('kit.dashboard.operations.subprocess.run',side_effect=helper):
            result=self.complete(job)
        self.assertEqual(result['state'],'blocked_external_change',result)

    def test_http_requires_consent_session_and_csrf(self):
        body={'question_id':None,'question_text':'Chi?','pages':['Anna Rossi'],'text':'Anna','idempotency_key':'answer_http_001','share_confirmed':False}
        for kwargs in ({'authenticated':False},{'csrf':False}):
            code,_,_=self.request('POST',self.base+'answers',body,**kwargs);self.assertEqual(code,403)
        code,_,_=self.request('POST',self.base+'answers',body);self.assertEqual(code,422)
        body['share_confirmed']=True
        code,_,_=self.request('POST',self.base+'answers',body);self.assertEqual(code,201)
        self.assertEqual(self.get('answers')[2]['answers'][0]['text'],'Anna')

    def test_bulk_consolidation_cli_is_disabled_before_database_access(self):
        script=Path(__file__).resolve().parents[1]/'kit/graph/domande.py'
        result=subprocess.run([sys.executable,str(script),'--consolida','--db',str(self.root/'does-not-exist.sqlite')],capture_output=True,timeout=15)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'consolida-id',result.stderr)
        self.assertFalse((self.root/'does-not-exist.sqlite').exists())

    def test_competing_consolidations_require_causal_review_and_new_validated_checkpoint(self):
        first=self.answer()
        original=next(e for e in snapshot_events(capture_snapshot(self.root),self.vault_id) if e['kind']=='answer.recorded')
        for digest in ('a'*64,'b'*64):
            event=dict(original,event_id=str(uuid4()),operation_id=str(uuid4()),kind='answer.consolidated',
                parents=[original['event_id']],payload={'answer_ids':[first['entity_id']],
                    'note_hashes':{'wiki/Anna Rossi.md':digest},'checkpoint_id':str(uuid4())})
            (self.root/'.teseo/shared/events'/(event['event_id']+'.json')).write_bytes(canonical_json(event))
        state=self.server.shared.answers(self.vault_id)
        self.assertEqual(state['answers'][0]['state'],'needs_decision')
        self.server.shared.decision(self.vault_id,{'question_id':first['question_id'],'heads':state['questions'][0]['heads'],
            'decision':'accepted','reason':'Revisionare e attestare la nota risultante','idempotency_key':'review_parallel_001','share_confirmed':True})
        job=self.submit(kind='lint');self.candidate(job,first['text'])
        ready=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        self.assertEqual(ready['state'],'prepared',ready)
        self.assertEqual(self.apply(ready)['state'],'succeeded')
        final=self.server.shared.answers(self.vault_id)
        self.assertEqual(final['answers'][0]['state'],'consolidated')
        self.assertFalse(final['conflicts'])

    def test_clean_clone_rebuilds_same_shared_state_and_graph_without_personal_databases(self):
        first=self.answer();job=self.submit(kind='lint');self.candidate(job,first['text'])
        ready=self.complete(job,self.selected_receipt(job,[first['entity_id']]))
        self.assertEqual(self.apply(ready)['state'],'succeeded')
        source=capture_snapshot(self.root)
        from kit.dashboard.graph_service import rebuild
        with tempfile.TemporaryDirectory(prefix='teseo shared clone ') as folder:
            clone=Path(folder);(clone/'wiki').mkdir();(clone/'.graph').mkdir()
            for item in source.files:
                path=clone/item.path;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(item.data)
            rebuilt=rebuild(clone)
            self.assertEqual(rebuilt.content_revision,source.digest)
            from kit.dashboard.graph_service import graph_reference
            reference=graph_reference(self.root/'.graph/graph.sqlite')
            with closing(sqlite3.connect(reference.path)) as left,closing(sqlite3.connect(rebuilt.path)) as right:
                for table in ('entities','relations','aliases'):
                    self.assertCountEqual(left.execute('SELECT * FROM '+table).fetchall(),right.execute('SELECT * FROM '+table).fetchall())
            self.assertEqual(validate_snapshot(source),validate_snapshot(capture_snapshot(clone)))
            self.assertFalse((clone/'.graph/memoria.sqlite').exists())
            self.assertFalse((clone/'.graph/domande.sqlite').exists())

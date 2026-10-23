"""Cicli skill: HTTP reale, copia isolata, ricevute e nessun client AI avviato."""
import json
from pathlib import Path
import unittest
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard.client_receipt import create_receipt
from kit.dashboard.storage import capture_snapshot


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

"""Regressioni del DAG condiviso: eventi sono dati, mai autorità temporale."""
import copy
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from kit.dashboard.contracts import ContractError, canonical_json
from kit.dashboard.storage import Snapshot, SnapshotFile
from kit.dashboard.shared_state import validate_event, project, snapshot_events, import_events

V = str(uuid4())
Q = str(uuid4())

def event(kind, payload, *, entity=None, question=Q, parents=()):
    return dict(format_version=1, vault_id=V, event_id=str(uuid4()), kind=kind,
                entity_id=entity or question, question_id=question, operation_id=str(uuid4()),
                author_id=str(uuid4()), created_at='2026-10-23T10:00:00Z',
                parents=list(parents), payload=payload)

def registration():
    return event('question.registered', {'text':'Chi?', 'anchors':[{'page':'Anna','signal':'manca_referente','legacy_key':'q1'}]})

class SharedState(unittest.TestCase):
    def test_causal_answer_resolution_survives_deferral_but_not_a_new_answer(self):
        q=registration()
        a=event('answer.recorded',{'text':'Anna','pages':['Anna'],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']])
        b=event('answer.recorded',{'text':'Bruno','pages':['Anna'],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']])
        decision=event('question.decided',{'decision':'accepted','reason':'Revisione umana'},parents=[a['event_id'],b['event_id']])
        deferred=event('question.deferred',{'reason':'Servono altri dati'},parents=[decision['event_id']])
        state=project([q,a,b,decision,deferred],V)
        self.assertEqual(state['questions'][0]['state'],'deferred')
        self.assertFalse(state['conflicts'])
        newer=event('answer.recorded',{'text':'Cristina','pages':['Anna'],'source':'nota-utente'},entity=str(uuid4()),parents=[deferred['event_id']])
        self.assertEqual(project([q,a,b,decision,deferred,newer],V)['questions'][0]['state'],'needs_decision')
    def test_order_independent_and_distinct_answers(self):
        q=registration(); a=event('answer.recorded', {'text':'Anna','pages':['Anna'],'source':'nota-utente'}, entity=str(uuid4()), parents=[q['event_id']]); b=copy.deepcopy(a); b['event_id']=str(uuid4()); b['entity_id']=str(uuid4()); b['payload']['text']='Bruno'
        expected=project([q,a,b],V)
        self.assertEqual(len(expected['answers']),2)
        self.assertTrue(expected['conflicts'])
        for seed in range(10):
            items=[q,a,b,a]; random.Random(seed).shuffle(items)
            self.assertEqual(project(items,V),expected)
    def test_pending_propagates_and_complete_candidate_rejects(self):
        q=registration(); a=event('answer.recorded', {'text':'A','pages':[],'source':'nota-utente'}, entity=str(uuid4()), parents=[q['event_id']]); d=event('question.deferred',{'reason':'poi'},parents=[a['event_id']])
        self.assertEqual(set(project([a,d],V)['pending']),{a['event_id'],d['event_id']})
        with self.assertRaises(ContractError): project([a,d],V,allow_pending=False)
        self.assertFalse(project([q,a,d],V)['pending'])
    def test_conflicting_defers_resolved_causally(self):
        q=registration(); one=event('question.deferred',{'reason':'x'},parents=[q['event_id']]); two=event('question.deferred',{'reason':'x'},parents=[q['event_id']]); p=project([q,one,two],V)
        self.assertEqual(p['questions'][0]['defer_count'],1)
        self.assertEqual(p['questions'][0]['state'],'needs_decision')
        resolution=event('question.decided',{'decision':'reopen','reason':'ora'},parents=[one['event_id'],two['event_id']]); p=project([resolution,two,q,one],V)
        self.assertFalse(p['conflicts']); self.assertEqual(p['questions'][0]['state'],'open')
    def test_bad_ids_versions_duplicates_cycles_and_causal_reference(self):
        q=registration()
        for field,value in [('event_id','../x'),('vault_id',str(uuid4())),('format_version',2),('created_at','yesterday')]:
            bad=copy.deepcopy(q); bad[field]=value
            with self.assertRaises(ContractError): project([bad],V)
        bad=copy.deepcopy(q); bad['payload']['text']='changed'
        with self.assertRaises(ContractError): project([q,bad],V)
        q['parents']=[q['event_id']]
        with self.assertRaises(ContractError): project([q],V)
        q=registration(); a=event('answer.recorded',{'text':'x','pages':[],'source':'nota-utente'},entity=str(uuid4()))
        with self.assertRaises(ContractError): project([q,a],V)
    def test_consolidation_only_selected_and_competing_conflict(self):
        q=registration(); a=event('answer.recorded',{'text':'x','pages':['Anna'],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); b=event('answer.recorded',{'text':'later','pages':[],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); c=event('answer.consolidated',{'answer_ids':[a['entity_id']],'note_hashes':{'wiki/Anna.md':'a'*64},'checkpoint_id':str(uuid4())},entity=a['entity_id'],parents=[a['event_id']]); p=project([q,a,b,c],V)
        self.assertEqual({x['entity_id']:x['state'] for x in p['answers']}[a['entity_id']],'consolidated')
        self.assertEqual({x['entity_id']:x['state'] for x in p['answers']}[b['entity_id']],'archived')
        d=copy.deepcopy(c); d['event_id']=str(uuid4()); d['payload']['note_hashes']['wiki/Anna.md']='b'*64
        p=project([q,a,c,d],V); self.assertEqual(p['answers'][0]['state'],'needs_decision')
    def test_rename_maps_historical_pages_without_mutation(self):
        q=registration(); a=event('answer.recorded',{'text':'x','pages':['Anna'],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); r=event('page.renamed',{'from':'Anna','to':'Annina'},parents=[a['event_id']]); p=project([r,q,a],V)
        self.assertEqual(p['answers'][0]['pages'],['Annina']); self.assertEqual(a['payload']['pages'],['Anna']); self.assertEqual(p['renames'],{'Anna':'Annina'})
    def test_import_idempotent_atomic_and_pending_later_completed(self):
        q=registration(); a=event('answer.recorded',{'text':'x','pages':[],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'shared.sqlite'; p=import_events(path,[a],V); self.assertTrue(p['pending'])
            p=import_events(path,[q],V); self.assertFalse(p['pending']); self.assertEqual(import_events(path,[a,q],V),p)
            bad=copy.deepcopy(q); bad['payload']['text']='evil'
            with self.assertRaises(ContractError): import_events(path,[bad],V)
            db=sqlite3.connect(path)
            try: self.assertEqual(db.execute('SELECT count(*) FROM applied_events').fetchone()[0],2)
            finally: db.close()
    def test_payload_strict_and_bounded(self):
        q=registration()
        for payload in ({'text':'x','anchors':[],'command':'run'}, {'text':'x'*20000,'anchors':[]}):
            bad=copy.deepcopy(q); bad['payload']=payload
            with self.assertRaises(ContractError): validate_event(bad,V)
        with self.assertRaises(ContractError): validate_event(q,V,'wrong.json')


    def test_canonical_snapshot_and_filename_are_mandatory(self):
        q=registration(); path='.teseo/shared/events/'+q['event_id']+'.json'
        snap=Snapshot((SnapshotFile(path,canonical_json(q)),))
        self.assertEqual(snapshot_events(snap,V),[q])
        with self.assertRaises(ContractError): snapshot_events(Snapshot((SnapshotFile(path,canonical_json(q).rstrip()),)),V)
        with self.assertRaises(ContractError): snapshot_events(Snapshot((SnapshotFile('.teseo/shared/events/'+str(uuid4())+'.json',canonical_json(q)),)),V)
    def test_causal_supersession_and_answer_decision(self):
        q=registration(); a=event('answer.recorded',{'text':'A','pages':[],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); b=event('answer.recorded',{'text':'B','pages':[],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); d=event('question.decided',{'decision':'accepted','reason':'B confermato'},parents=[a['event_id'],b['event_id']]); p=project([q,a,b,d],V)
        self.assertFalse(p['conflicts']); self.assertEqual(p['questions'][0]['state'],'closed'); self.assertEqual(len(p['answers']),2)
        s=event('answer.superseded',{'replacement_id':b['entity_id']},entity=a['entity_id'],parents=[a['event_id'],b['event_id']]); p=project([q,a,b,s],V)
        self.assertFalse(p['conflicts']); self.assertEqual(next(x for x in p['answers'] if x['entity_id']==a['entity_id'])['state'],'superseded')
        s['parents']=[a['event_id']]
        with self.assertRaises(ContractError): project([q,a,b,s],V)
    def test_cycles_missing_and_registration_entity_collision(self):
        q=registration(); d=event('question.deferred',{'reason':'x'},parents=[q['event_id']]); q['parents']=[d['event_id'],str(uuid4())]
        with self.assertRaises(ContractError): project([q,d],V)
        q=registration(); r=copy.deepcopy(q); r['event_id']=str(uuid4())
        with self.assertRaises(ContractError): project([q,r],V)
        r=event('page.renamed',{'from':'A','to':'B'}); s=event('page.renamed',{'from':'B','to':'A'},parents=[r['event_id']])
        with self.assertRaises(ContractError): project([r,s],V)
    def test_rename_conflict_and_invalid_payloads(self):
        q=registration(); r=event('page.renamed',{'from':'A','to':'B'},parents=[q['event_id']]); s=event('page.renamed',{'from':'A','to':'C'},parents=[q['event_id']]); p=project([r,s,q],V)
        self.assertEqual(p['conflicts'][0]['kind'],'page.rename'); self.assertEqual(p['renames'],{})
        cases=[('answer.recorded',{'text':'x','pages':['../x'],'source':'nota-utente'}),('answer.consolidated',{'answer_ids':[str(uuid4())],'checkpoint_id':str(uuid4()),'note_hashes':{'raw/x':'a'*64}}),('question.decided',{'decision':'execute','reason':'x'}),('question.registered',{'text':'x','anchors':[{'page':'A','signal':'x','exec':'bad'}]})]
        for kind,payload in cases:
            with self.assertRaises(ContractError): validate_event(event(kind,payload),V)
    def test_discard_and_defer_have_no_implicit_answer(self):
        q=registration(); d=event('synthesis.discarded',{'question':'Chi?','reason':'non utile','pages':['Anna']},entity=str(uuid4()),parents=[q['event_id']]); p=project([q,d],V)
        self.assertEqual(p['answers'],[]); self.assertEqual(p['event_count'],2)
        self.assertEqual(p['questions'][0]['history'][0]['payload']['reason'],'non utile')

    def test_complete_snapshot_validation_and_cache_rollback(self):
        from kit.dashboard.shared_state import validate_snapshot, rebuild_projection
        q=registration(); a=event('answer.recorded',{'text':'A','pages':[],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); entries=tuple(SnapshotFile('.teseo/shared/events/'+e['event_id']+'.json',canonical_json(e)) for e in [q,a]); snap=Snapshot(entries)
        self.assertEqual(validate_snapshot(snap,V)['event_count'],2)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cache.sqlite'; rebuild_projection(path,[q,a],V)
            p=rebuild_projection(path,[q],V); self.assertEqual(p['answers'],[])
            db=sqlite3.connect(path)
            try: self.assertEqual(db.execute('SELECT count(*) FROM applied_events').fetchone()[0],1)
            finally: db.close()
            bad=copy.deepcopy(q); bad['payload']['text']='collision'
            with self.assertRaises(ContractError): rebuild_projection(path,[bad],V)

    def test_invalid_empty_vault_and_untyped_decision_are_contract_errors(self):
        with self.assertRaises(ContractError): project([], '../vault')
        with self.assertRaises(ContractError): validate_event(event('question.decided',{'decision':[],'reason':'x'}),V)

    def test_question_heads_include_answers_for_explicit_resolution(self):
        q=registration(); a=event('answer.recorded',{'text':'A','pages':[],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); b=event('answer.recorded',{'text':'B','pages':[],'source':'nota-utente'},entity=str(uuid4()),parents=[q['event_id']]); p=project([q,a,b],V)
        self.assertEqual(p['questions'][0]['heads'],sorted([a['event_id'],b['event_id']]))

    def test_answer_identity_cannot_reuse_question_uuid(self):
        q=registration(); another=event('question.registered',{'text':'Altro?','anchors':[]},question=str(uuid4()))
        for identity in (q['question_id'],another['question_id']):
            a=event('answer.recorded',{'text':'A','pages':[],'source':'nota-utente'},entity=identity,parents=[q['event_id']])
            with self.assertRaises(ContractError) as error: project([q,a,another],V)
            self.assertEqual(error.exception.code,'entity_collision')

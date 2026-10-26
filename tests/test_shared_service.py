"""Shared API service: explicit consent, durable retries and immutable events."""
import _shortpath  # noqa: F401
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from kit.dashboard.contracts import ContractError, canonical_json
from kit.dashboard.shared_service import SharedService
from kit.dashboard.shared_migration import _connection


class Registry:
    def __init__(self, root): self.path = root
    def root(self, vault): return self.path


class Service(unittest.TestCase):
    def test_publication_is_separate_and_uses_only_persisted_push_receipt(self):
        import hashlib
        self.service.record(self.vault,self.body())
        events=self.root/'.teseo/shared/events'
        answer=next(json.loads(p.read_bytes()) for p in events.glob('*.json') if json.loads(p.read_bytes())['kind']=='answer.recorded')
        note=self.root/'wiki/Anna.md';note.write_bytes(b'Anna')
        operation=str(uuid4())
        marker=dict(answer,event_id=str(uuid4()),operation_id=operation,kind='answer.consolidated',parents=[answer['event_id']],
                    payload={'answer_ids':[answer['entity_id']],'note_hashes':{'wiki/Anna.md':hashlib.sha256(b'Anna').hexdigest()},'checkpoint_id':str(uuid4())})
        (events/(marker['event_id']+'.json')).write_bytes(canonical_json(marker))
        self.assertEqual(self.service.answers(self.vault)['answers'][0]['publication'],'unknown')
        with _connection(self.root/'.teseo/local/sync.sqlite') as db:
            db.execute('CREATE TABLE jobs(operation_id TEXT PRIMARY KEY,data BLOB NOT NULL)')
            db.execute('INSERT INTO jobs VALUES (?,?)',(operation,canonical_json({'published_oid':'a'*40,'state':'published_pending_local_adoption'})))
        result=self.service.answers(self.vault)['answers'][0]
        self.assertTrue(result['applied']);self.assertEqual(result['publication'],'published')
        self.assertEqual(result['published_oid'],'a'*40)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = str(uuid4())
        (self.root / '.teseo').mkdir()
        (self.root / 'wiki').mkdir()
        (self.root / 'Wiki reference.md').write_text('Schema', encoding='utf-8')
        (self.root / '.teseo/project.json').write_bytes(canonical_json({
            'format_version': 1, 'schema_version': 1, 'event_version': 1,
            'vault_id': self.vault, 'minimum_kit_version': '1.0.0',
            'shared_paths': ['wiki/', 'raw/', 'Wiki reference.md', 'index.md', 'log.md', '.teseo/shared/']}))
        self.service = SharedService(Registry(self.root))

    def body(self, key='answer-key-1'):
        return dict(question_id=None, question_text='Chi?', pages=['Anna'], text='Anna',
                    idempotency_key=key, share_confirmed=True)

    def test_get_is_readonly_and_answers_require_explicit_consent(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        self.assertEqual(self.service.answers(self.vault)['answers'], [])
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))
        body = self.body(); body['share_confirmed'] = False
        with self.assertRaises(ContractError): self.service.record(self.vault, body)

    def test_explicit_deferral_is_causal_and_duplicate_does_not_increment(self):
        self.service.record(self.vault,self.body())
        question=self.service.answers(self.vault)['questions'][0]
        body={'question_id':question['question_id'],'heads':question['heads'],'decision':'defer',
              'reason':'Servono dati dall’autore','idempotency_key':'defer-explicit-001','share_confirmed':True}
        first=self.service.decision(self.vault,body)
        self.assertEqual(first,self.service.decision(self.vault,body))
        state=self.service.answers(self.vault)['questions'][0]
        self.assertEqual(state['state'],'deferred')
        self.assertEqual(state['defer_count'],1)

    def test_record_replays_same_events_and_conflicting_key_is_rejected(self):
        first = self.service.record(self.vault, self.body())
        again = SharedService(Registry(self.root)).record(self.vault, self.body())
        self.assertEqual(first, again)
        self.assertEqual(len(list((self.root / '.teseo/shared/events').glob('*.json'))), 2)
        self.assertEqual(len(self.service.answers(self.vault)['answers']), 1)
        body = self.body(); body['text'] = 'Bruno'
        with self.assertRaises(ContractError) as caught: self.service.record(self.vault, body)
        self.assertEqual(caught.exception.code, 'idempotency_conflict')

    def test_partial_append_retry_finishes_without_losing_existing_event(self):
        import kit.dashboard.shared_service as module
        real = module.os.link
        calls = []
        def interrupted(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2: raise OSError('simulated process interruption')
            return real(*args, **kwargs)
        with mock.patch.object(module.os, 'link', interrupted):
            with self.assertRaises(OSError): self.service.record(self.vault, self.body())
        self.service.record(self.vault, self.body())
        self.assertEqual(len(self.service.answers(self.vault)['answers']), 1)

    def test_decision_resolves_using_current_heads_and_import_rebuilds_exact_set(self):
        self.service.record(self.vault, self.body())
        state = self.service.answers(self.vault)
        question = state['questions'][0]
        self.service.decision(self.vault, dict(question_id=question['question_id'], heads=question['heads'],
            decision='closed', reason='Verificato', idempotency_key='decision-key', share_confirmed=True))
        self.assertEqual(self.service.answers(self.vault)['questions'][0]['state'], 'closed')
        self.service.import_state(self.vault, {})
        for p in (self.root / '.teseo/shared/events').glob('*.json'): p.unlink()
        rebuilt = self.service.import_state(self.vault, {})
        self.assertEqual(rebuilt['answers'], [])

    def test_awaiting_client_allows_new_answer_but_partial_apply_blocks(self):
        local = self.root / '.teseo/local'
        local.mkdir()
        with _connection(local / 'operations.sqlite') as db:
            db.execute('CREATE TABLE operations(operation_id PRIMARY KEY,record BLOB)')
            db.execute('INSERT INTO operations VALUES(?,?)', ('job', canonical_json({'state':'awaiting_client'})))
        self.service.record(self.vault, self.body())
        with _connection(local / 'operations.sqlite') as db:
            db.execute('UPDATE operations SET record=?', (canonical_json({'state':'applying'}),))
        with self.assertRaises(ContractError): self.service.answers(self.vault)
        with self.assertRaises(ContractError): self.service.record(self.vault, self.body('next-key'))

    def test_service_export_requires_selection_and_never_reads_personal_memory(self):
        (self.root / '.graph').mkdir()
        personal = self.root / '.graph/memoria.sqlite'
        personal.write_bytes(b'PRIVATE NOT A DATABASE')
        source = self.root / '.graph/domande.sqlite'
        with _connection(source) as db:
            db.execute('CREATE TABLE risposte(id INTEGER PRIMARY KEY,chiave,segnale,domanda,risposta,pagine)')
            db.execute("INSERT INTO risposte VALUES(1,'ref|Anna|','referente','Chi?','Anna','Anna')")
        before = source.read_bytes()
        preview = self.service.preview(self.vault, {})
        body = dict(preview_id=preview['preview_id'], selection_ids=[], idempotency_key='empty-key', share_confirmed=True)
        self.assertEqual(self.service.export(self.vault, body)['event_ids'], [])
        self.assertEqual(self.service.answers(self.vault)['answers'], [])
        body['selection_ids'] = [preview['rows'][0]['selection_id']]; body['idempotency_key']='selected-key'
        result = self.service.export(self.vault, body)
        self.assertEqual(result, self.service.export(self.vault, body))
        self.assertEqual(len(self.service.answers(self.vault)['answers']), 1)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(personal.read_bytes(), b'PRIVATE NOT A DATABASE')

    def test_malformed_pages_are_controlled_contract_error(self):
        for pages in (None, 'Anna', ['../secret']):
            with self.subTest(pages=pages):
                body=self.body(); body['pages']=pages
                with self.assertRaises(ContractError): self.service.record(self.vault, body)

    def test_historical_consolidation_retains_state_after_notes_evolve(self):
        import hashlib
        self.service.record(self.vault, self.body())
        state = self.service.answers(self.vault)
        answer = state['answers'][0]
        eventsdir = self.root / '.teseo/shared/events'
        originals = [json.loads(path.read_bytes()) for path in eventsdir.glob('*.json')]
        original = next(e for e in originals if e['kind']=='answer.recorded')
        marker = dict(original, event_id=str(uuid4()), operation_id=str(uuid4()),
            kind='answer.consolidated', parents=[original['event_id']], payload={
                'answer_ids':[answer['entity_id']], 'checkpoint_id':str(uuid4()),
                'note_hashes':{'wiki/Anna.md':hashlib.sha256(b'old').hexdigest()}})
        (eventsdir / (marker['event_id']+'.json')).write_bytes(canonical_json(marker))
        (self.root / 'wiki/Anna.md').write_bytes(b'new')
        unknown = self.service.answers(self.vault)['answers'][0]
        self.assertEqual(unknown['state'], 'consolidated')
        self.assertIsNone(unknown['applied'])
        self.assertEqual(unknown['verification'], 'historical_unverified')
        with _connection(self.root / '.teseo/local/operations.sqlite') as db:
            db.execute('CREATE TABLE operations(operation_id PRIMARY KEY,record BLOB)')
            db.execute('INSERT INTO operations VALUES(?,?)',
                (marker['operation_id'], canonical_json({'state':'succeeded'})))
        known = self.service.answers(self.vault)['answers'][0]
        self.assertEqual(known['state'], 'consolidated')
        self.assertTrue(known['applied'])
        self.assertTrue(known['notes_changed_since_checkpoint'])

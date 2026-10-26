"""Selective legacy migration: preserve original databases and local identity."""
import _shortpath  # noqa: F401
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from kit.dashboard.contracts import ContractError
from kit.dashboard.shared_migration import LegacyMigration, _connection


class Migration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.graph').mkdir()
        self.db = self.root / '.graph/domande.sqlite'
        with _connection(self.db) as db:
            db.executescript("""
                CREATE TABLE risposte(id INTEGER PRIMARY KEY, chiave, segnale, domanda, risposta, pagine, quando, consolidata);
                CREATE TABLE aperte(chiave PRIMARY KEY, segnale, pagina, testo, stato, fino_al, rinvii);
                CREATE TABLE scartate(domanda PRIMARY KEY, motivo, quando, pagine);
                CREATE TABLE poste(sessione, testo);
                INSERT INTO risposte VALUES(1,'referente|A|','referente','Who?','Anna','A · B','2026-01-01',0);
                INSERT INTO risposte VALUES(2,'referente|A|','referente','Who?','Anna','A','2026-01-01',0);
                INSERT INTO aperte VALUES('referente|A|','referente','A','Who?','rinviata','2027-01-01',2);
                INSERT INTO scartate VALUES('What?', 'No evidence', '2026-01-01', '["A"]');
                INSERT INTO poste VALUES('private-session','PRIVATE');
            """)
        (self.root / '.graph/memoria.sqlite').write_bytes(b'PERSONAL DB NEVER OPEN')
        self.vault, self.author = str(uuid4()), str(uuid4())
        self.service = LegacyMigration(self.root, self.vault, self.author)

    def test_selected_export_repeats_identity_preserves_original_and_excludes_personal(self):
        original = self.db.read_bytes()
        preview = self.service.preview()
        self.assertEqual(preview['exclusions']['poste'], 1)
        self.assertTrue(preview['copied_source_warning'])
        self.assertEqual(len(preview['rows']), 4)
        selected = [r['selection_id'] for r in preview['rows'] if r['table'] == 'risposte']
        self.assertEqual(self.service.export([], preview['preview_id']), [])
        events = self.service.export(selected, preview['preview_id'])
        self.assertEqual(events, self.service.export(selected, preview['preview_id']))
        answers = [e for e in events if e['kind'] == 'answer.recorded']
        self.assertEqual(len(answers), 2)
        self.assertNotEqual(answers[0]['entity_id'], answers[1]['entity_id'])
        self.assertEqual(len({e['question_id'] for e in answers}), 1)
        self.assertNotIn('PRIVATE', str(events))
        self.assertEqual(self.db.read_bytes(), original)
        self.assertEqual((self.root / '.graph/memoria.sqlite').read_bytes(), b'PERSONAL DB NEVER OPEN')
        self.assertTrue((self.root / preview['backup_manifest_path']).is_file())
        again = LegacyMigration(self.root, self.vault, self.author)
        self.assertEqual(events, again.export(selected, preview['preview_id']))
        self.assertFalse((self.root / '.teseo/shared').exists())

    def test_source_changed_or_unknown_selection_is_blocked(self):
        preview = self.service.preview()
        with self.assertRaises(ContractError):
            self.service.export(['not-an-id'], preview['preview_id'])
        with _connection(self.db) as db:
            db.execute("UPDATE risposte SET risposta='Changed' WHERE id=1")
        with self.assertRaises(ContractError) as caught:
            self.service.export([preview['rows'][0]['selection_id']], preview['preview_id'])
        self.assertEqual(caught.exception.code, 'legacy_preview_stale')

    def test_copied_database_does_not_merge_answer_ids(self):
        preview = self.service.preview()
        row = next(r for r in preview['rows'] if r['table'] == 'risposte')
        first = self.service.export([row['selection_id']], preview['preview_id'])
        other = self.root / 'clone'
        (other / '.graph').mkdir(parents=True)
        shutil.copyfile(self.db, other / '.graph/domande.sqlite')
        service = LegacyMigration(other, self.vault, self.author)
        new = service.preview()
        selection = next(r for r in new['rows'] if r['table'] == 'risposte')
        second = service.export([selection['selection_id']], new['preview_id'])
        self.assertNotEqual(first[-1]['entity_id'], second[-1]['entity_id'])

    def test_backup_includes_committed_wal_and_decisions_are_explicit(self):
        db = sqlite3.connect(self.db)
        self.addCleanup(db.close)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute("UPDATE risposte SET risposta='WAL answer' WHERE id=1")
        db.commit()
        preview = self.service.preview()
        self.assertIn('WAL answer', str(preview['rows']))
        rows = [r['selection_id'] for r in preview['rows'] if r['table'] != 'risposte']
        events = self.service.export(rows, preview['preview_id'])
        self.assertEqual({e['kind'] for e in events}, {'question.registered', 'question.deferred', 'synthesis.discarded'})
        db.execute("UPDATE risposte SET risposta='New WAL answer' WHERE id=1")
        db.commit()
        with self.assertRaises(ContractError):
            self.service.export(rows, preview['preview_id'])

    def test_invalid_legacy_data_is_not_persisted_as_export(self):
        with _connection(self.db) as db:
            db.execute("UPDATE risposte SET pagine='../../secret' WHERE id=1")
        preview = self.service.preview()
        selected = next(r['selection_id'] for r in preview['rows'] if r['table']=='risposte' and r['row_id']=='1')
        with self.assertRaises(ContractError):
            self.service.export([selected], preview['preview_id'])
        with _connection(self.service.mapping) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM exports').fetchone()[0], 0)

    def test_selected_deferral_history_preserves_count_and_replay(self):
        from kit.dashboard.shared_state import project
        preview=self.service.preview()
        selected=[row['selection_id'] for row in preview['rows'] if row['table']=='aperte']
        events=self.service.export(selected,preview['preview_id'])
        self.assertEqual(project(events,self.vault)['questions'][0]['defer_count'],2)
        self.assertEqual(events,self.service.export(selected,preview['preview_id']))
        self.assertEqual(project(events+events,self.vault)['questions'][0]['defer_count'],2)

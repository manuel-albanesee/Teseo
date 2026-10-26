"""Selective export from a consistent legacy backup; original SQLite stays local.

This module prepares events only. Publication belongs to the shared coordinator.
Unknown provenance is deliberately a new local UUID, never a content-derived ID.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import UUID, uuid4, uuid5

from .contracts import ContractError, canonical_json
from .storage import _ensure_ignored, _local_directory, _no_link
from .shared_state import validate_event


@contextmanager
def _connection(*args, **kwargs):
    db = sqlite3.connect(*args, **kwargs)
    try:
        with db:
            yield db
    finally:
        db.close()


def _pages(value):
    if not value:
        return []
    if value.startswith('['):
        try:
            values = json.loads(value)
        except ValueError as error:
            raise ContractError('legacy_invalid', 'Elenco pagine legacy non valido') from error
    else:
        values = value.split(' · ')
    if not isinstance(values, list) or any(not isinstance(p, str) for p in values):
        raise ContractError('legacy_invalid', 'Elenco pagine legacy non valido')
    return list(dict.fromkeys(p.strip() for p in values if p.strip()))


class LegacyMigration:
    """Explicit row selection with durable UUID/event mapping and stale-source gate."""

    def __init__(self, root: Path, vault_id: str, author_id: str):
        self.root = Path(root).resolve(strict=True)
        self.vault_id, self.author_id = str(UUID(vault_id)), str(UUID(author_id))
        local = _local_directory(self.root)
        _ensure_ignored(local)
        self.local = local / 'shared-migration'
        _no_link(self.local)
        self.local.mkdir(exist_ok=True)
        self.mapping = self.local / 'local.sqlite'
        _no_link(self.mapping)
        self.source = self.root / '.graph/domande.sqlite'
        _no_link(self.root / '.graph')
        _no_link(self.source)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sources(identity TEXT PRIMARY KEY, provenance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS exports(identity TEXT NOT NULL, selection TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, events TEXT NOT NULL, PRIMARY KEY(identity, selection));
                CREATE TABLE IF NOT EXISTS registrations(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            ''')

    def _db(self):
        for suffix in ('', '-journal', '-wal', '-shm'):
            _no_link(Path(str(self.mapping) + suffix))
        return _connection(self.mapping, timeout=5)

    def _identity(self):
        _no_link(self.source)
        for suffix in ('-wal', '-shm', '-journal'):
            _no_link(Path(str(self.source) + suffix))
        try:
            stat = self.source.stat()
        except OSError as error:
            raise ContractError('legacy_missing', 'Database domande legacy assente') from error
        if not self.source.is_file() or stat.st_size > 128 * 1024 * 1024:
            raise ContractError('legacy_invalid', 'Database legacy non valido o troppo grande')
        # A copied database on another clone acquires a new local identity. No claim
        # is made that this proves historical provenance of an already copied DB.
        return hashlib.sha256(f'{self.vault_id}:{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns if not stat.st_ino else ""}'.encode()).hexdigest()

    def _backup(self, directory):
        identity = self._identity()
        path = directory / 'domande.sqlite'
        _no_link(path)
        try:
            with _connection(self.source.as_uri() + '?mode=ro', uri=True, timeout=3) as source:
                source.execute('PRAGMA query_only=ON')
                with _connection(path) as target:
                    deadline = time.monotonic() + 10
                    def progress(status, remaining, total):
                        if time.monotonic() > deadline or total > 32768:
                            raise ContractError('legacy_invalid', 'Backup legacy troppo grande o occupato')
                    source.backup(target, pages=128, progress=progress, sleep=.01)
            if self._identity() != identity:
                raise ContractError('legacy_preview_stale', 'Identità database cambiata durante il backup')
            with _connection(path) as backup:
                if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ContractError('legacy_invalid', 'Backup SQLite non valido')
                # Hash the logical backup, including committed WAL data. It is local
                # only and deliberately includes excluded records for freshness.
                digest = hashlib.sha256()
                for line in backup.iterdump():
                    digest.update(line.encode('utf-8'))
                    digest.update(b'\n')
                return identity, digest.hexdigest()
        except sqlite3.Error as error:
            raise ContractError('legacy_invalid', 'Impossibile leggere il backup legacy') from error

    def preview(self):
        preview_id = str(uuid4())
        directory = self.local / preview_id
        directory.mkdir()
        identity, digest = self._backup(directory)
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO sources VALUES(?, ?)', (identity, str(uuid4())))
            provenance = db.execute('SELECT provenance FROM sources WHERE identity=?', (identity,)).fetchone()[0]
        rows, exclusions = [], {}
        with _connection(directory / 'domande.sqlite') as backup:
            backup.row_factory = sqlite3.Row
            tables = {r[0] for r in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in sorted(tables):
                quoted = '"' + table.replace('"', '""') + '"'
                if table not in ('risposte', 'aperte', 'scartate'):
                    exclusions[table] = backup.execute(f'SELECT COUNT(*) FROM {quoted}').fetchone()[0]
                    continue
                values = backup.execute(f'SELECT rowid AS _row_id, * FROM {quoted} ORDER BY rowid LIMIT 1001').fetchall()
                if len(values) > 1000:
                    raise ContractError('legacy_invalid', 'Troppe righe legacy per una preview')
                for row in values:
                    fields = dict(row)
                    row_id = str(fields.pop('_row_id'))
                    eligible = table != 'aperte' or fields.get('stato') == 'rinviata'
                    selection = str(uuid5(UUID(provenance), table + ':' + row_id))
                    rows.append({'selection_id': selection, 'table': table, 'row_id': row_id,
                                 'shareable': eligible, 'fields': fields})
        manifest = {'preview_id': preview_id, 'vault_id': self.vault_id, 'source_identity': identity,
                    'source_provenance': provenance, 'source_digest': digest, 'base_identity': identity,
                    'base_digest': digest, 'rows': rows, 'exclusions': exclusions,
                    'personal_memory': 'excluded_without_opening', 'copied_source_warning': True,
                    'backup_manifest_path': (directory / 'manifest.json').relative_to(self.root).as_posix()}
        manifest_bytes=canonical_json(manifest)
        if len(manifest_bytes)>2*1024*1024:
            raise ContractError('legacy_preview_limit','Preview oltre 2 MiB: preparare una selezione legacy più piccola su copia')
        (directory / 'manifest.json').write_bytes(manifest_bytes)
        with self._db() as db:
            db.execute('INSERT INTO previews VALUES(?, ?)', (preview_id, json.dumps(manifest)))
        return manifest

    def export(self, selection_ids: list[str], preview_id: str) -> list[dict]:
        if not isinstance(preview_id,str):
            raise ContractError('legacy_preview_stale','Identità preview non valida')
        if not isinstance(selection_ids, list) or any(not isinstance(i, str) for i in selection_ids) or len(set(selection_ids)) != len(selection_ids):
            raise ContractError('legacy_selection_invalid', 'Selezione legacy non valida')
        with self._db() as db:
            saved = db.execute('SELECT data FROM previews WHERE id=?', (preview_id,)).fetchone()
        if saved is None:
            raise ContractError('legacy_preview_stale', 'Preview legacy sconosciuta')
        preview = json.loads(saved[0])
        if preview['vault_id'] != self.vault_id:
            raise ContractError('legacy_preview_stale', 'Vault della preview diverso')
        rows = {r['selection_id']: r for r in preview['rows']}
        if any(i not in rows or not rows[i]['shareable'] for i in selection_ids):
            raise ContractError('legacy_selection_invalid', 'Selezionare solo righe condivisibili della preview')
        check = self.local / str(uuid4())
        check.mkdir()
        try:
            identity, digest = self._backup(check)
        finally:
            # Only this owned freshness backup is disposable; the review backup stays.
            for child in check.iterdir():
                child.unlink()
            check.rmdir()
        if identity != preview['source_identity'] or digest != preview['source_digest']:
            raise ContractError('legacy_preview_stale', 'Database legacy cambiato: rigenerare la preview')
        events: dict = {}
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            for selection in sorted(selection_ids):
                row = rows[selection]
                fingerprint = hashlib.sha256(canonical_json(row)).hexdigest()
                cached = db.execute('SELECT fingerprint,events FROM exports WHERE identity=? AND selection=?', (identity, selection)).fetchone()
                if cached:
                    if cached[0] != fingerprint:
                        raise ContractError('legacy_export_changed', 'Riga già esportata modificata: revisione esplicita richiesta')
                    generated = json.loads(cached[1])
                else:
                    generated = self._events(preview, row)
                    registration = generated[0]
                    db.execute('INSERT OR IGNORE INTO registrations VALUES(?,?)',
                               (registration['event_id'], json.dumps(registration)))
                    generated[0] = json.loads(db.execute('SELECT data FROM registrations WHERE id=?',
                                                        (registration['event_id'],)).fetchone()[0])
                    # Validate JSON constraints before persisting identity mappings.
                    for event in generated:
                        validate_event(event, self.vault_id)
                    db.execute('INSERT INTO exports VALUES(?,?,?,?)', (identity, selection, fingerprint, json.dumps(generated)))
                for event in generated:
                    existing = events.setdefault(event['event_id'], event)
                    if existing != event:
                        raise ContractError('legacy_invalid', 'Identità domanda legacy incoerente')
        return sorted(events.values(), key=lambda event: (event['kind'] != 'question.registered', event['event_id']))

    def _events(self, preview, row):
        fields, table = row['fields'], row['table']
        for name in ('chiave','segnale','domanda','risposta','pagine','pagina','testo','motivo','fino_al'):
            if fields.get(name) is not None and not isinstance(fields[name], str):
                raise ContractError('legacy_invalid', 'Campo legacy testuale non valido')
        namespace = UUID(preview['source_provenance'])
        key = fields.get('chiave') or table + ':' + row['row_id']
        question = str(uuid5(namespace, 'question:' + key))
        question_event = str(uuid5(namespace, 'question-event:' + key))
        entity = str(uuid5(namespace, 'entity:' + table + ':' + row['row_id']))
        operation = str(uuid5(namespace, 'operation:' + table + ':' + row['row_id']))
        # Informational timestamp is fixed for stable replay across selections.
        created = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        pages = _pages(fields.get('pagine') or fields.get('pagina') or '')
        text = fields.get('domanda') or fields.get('testo') or key
        signal = fields.get('segnale') or 'scartata'
        anchor = [{'page': page, 'signal': signal, 'legacy_key': key} for page in pages]
        if not anchor:
            anchor = [{'page': '(vault)', 'signal': signal, 'legacy_key': key}]
        def event(event_id, kind, entity_id, payload, parents):
            return {'format_version': 1, 'vault_id': self.vault_id, 'event_id': event_id,
                    'kind': kind, 'entity_id': entity_id, 'question_id': question,
                    'operation_id': operation if kind != 'question.registered' else str(uuid5(namespace, 'question-operation:' + key)),
                    'author_id': self.author_id, 'created_at': created, 'parents': parents, 'payload': payload}
        # First explicit registration is frozen locally; later selections reuse it.
        registered = event(question_event, 'question.registered', question,
                           {'text': text, 'anchors': anchor}, [])
        if table == 'risposte':
            kind, payload = 'answer.recorded', {'text': fields.get('risposta') or '', 'pages': pages, 'source': 'nota-utente'}
        elif table == 'scartate':
            kind, payload = 'synthesis.discarded', {'question': text, 'reason': fields.get('motivo') or '', 'pages': pages}
        else:
            kind, payload = 'question.deferred', {'reason': 'Rinvio legacy selezionato; fino al ' + str(fields.get('fino_al') or '')}
            entity = question
            count=fields.get('rinvii',1)
            if type(count) is not int or not 1<=count<=128:
                raise ContractError('legacy_invalid','Conteggio rinvii legacy non valido; revisionare la copia')
            generated=[registered];parent=question_event
            for index in range(1,count+1):
                identifier=str(uuid5(namespace,'event:'+table+':'+row['row_id'])) if index==count else str(uuid5(namespace,'event:'+table+':'+row['row_id']+':history:'+str(index)))
                generated.append(event(identifier,kind,entity,{'reason':payload['reason']+'; import storico '+str(index)+'/'+str(count)},[parent]))
                parent=identifier
            return generated
        record = event(str(uuid5(namespace, 'event:' + table + ':' + row['row_id'])), kind, entity, payload, [question_event])
        return [registered, record]

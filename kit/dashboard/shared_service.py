"""Explicit shared mutations; personal SQLite is never consulted by answer reads."""
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from .contracts import ContractError, canonical_json, content_hash, parse_json
from .shared_migration import LegacyMigration, _connection
from .shared_state import project, snapshot_events, _list, _page, _text, _uuid
from .storage import VaultLock, capture_snapshot, _local_directory, _ensure_ignored, _no_link


def author_id(root):
    """Stable pseudonym for this local checkout; callers hold the vault lock."""
    local = _local_directory(root)
    _ensure_ignored(local)
    path = local / 'shared-author.json'
    _no_link(path)
    if not path.exists():
        with path.open('xb') as stream: stream.write(canonical_json({'author_id': str(uuid4())}))
    from .shared_state import _uuid
    with path.open('rb') as stream: data = stream.read(65537)
    if len(data) > 65536: raise ContractError('invalid_author', 'Identità autore locale troppo grande')
    return _uuid(parse_json(data)['author_id'])


class SharedService:
    def __init__(self, registry):
        self.registry = registry

    def _root(self, vault_id):
        root = self.registry.root(vault_id)
        self._readable(root)
        return root

    def _readable(self, root):
        # Awaiting a client may legitimately collect new answers. Only partially
        # applied note candidates make current shared state unsafe to read.
        path = root / '.teseo/local/operations.sqlite'
        _no_link(root / '.teseo/local')
        for suffix in ('','-journal','-wal','-shm'): _no_link(Path(str(path)+suffix))
        if not path.exists(): return
        with _connection(path.as_uri() + '?mode=ro', uri=True) as db:
            for (raw,) in db.execute('SELECT record FROM operations'):
                record = parse_json(raw)
                if record.get('state') in {'applying', 'recovery_required'}:
                    raise ContractError('recovery_required', 'Completare il recovery delle note prima dello stato condiviso')

    def answers(self, vault_id, parameters=None):
        if parameters:
            raise ContractError('invalid_parameters', 'Parametri risposte non supportati')
        root = self._root(vault_id)
        snapshot = capture_snapshot(root)
        events = snapshot_events(snapshot, vault_id)
        state = project(events, vault_id)
        by_id = {e['event_id']: e for e in events}
        publications = {}
        sync_journal=root/'.teseo/local/sync.sqlite'
        for suffix in ('','-journal','-wal','-shm'): _no_link(Path(str(sync_journal)+suffix))
        if sync_journal.exists():
            with _connection(sync_journal.as_uri()+'?mode=ro',uri=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
                    for operation_id,data in db.execute('SELECT operation_id,data FROM jobs'):
                        publication=parse_json(data).get('published_oid')
                        if publication:publications[operation_id]=publication
        for answer in state['answers']:
            answer['publication'] = 'unknown'
            answer['applied'] = False
            if answer['state'] != 'consolidated': continue
            markers = [by_id[i] for i in answer['heads'] if by_id[i]['kind'] == 'answer.consolidated']
            published=[publications[m['operation_id']] for m in markers if m['operation_id'] in publications]
            if markers and len(published)==len(markers):
                answer.update(publication='published',published_oid=published[-1],publication_verification='local_push_receipt')
            hashes_match = bool(markers) and all(all(snapshot.hashes.get(name) == digest
                        for name, digest in marker['payload']['note_hashes'].items()) for marker in markers)
            journal = root / '.teseo/local/operations.sqlite'
            known_states = []
            if journal.exists():
                with _connection(journal.as_uri() + '?mode=ro', uri=True) as db:
                    for marker in markers:
                        row = db.execute('SELECT record FROM operations WHERE operation_id=?', (marker['operation_id'],)).fetchone()
                        if row: known_states.append(parse_json(row[0]).get('state'))
            if known_states and all(s == 'succeeded' for s in known_states):
                answer['applied'] = True
                answer['notes_changed_since_checkpoint'] = not hashes_match
                answer['verification'] = 'local_checkpoint'
            elif known_states:
                answer['applied'] = False
                answer['state'] = 'checkpoint_pending'
            elif hashes_match:
                answer['applied'] = True
                answer['verification'] = 'current_note_hashes'
            else:
                answer['applied'] = None
                answer['verification'] = 'historical_unverified'
        state['content_revision'] = snapshot.digest
        return state

    def _local(self, root):
        local = _local_directory(root)
        _ensure_ignored(local)
        return local

    def _author(self, root):
        return author_id(root)

    def _body(self, body, fields):
        if not isinstance(body, dict) or set(body) != fields or body.get('share_confirmed') is not True:
            raise ContractError('shared_confirmation_required', 'Selezione e conferma esplicita della condivisione richieste')
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not 8 <= len(key) <= 128:
            raise ContractError('invalid_idempotency_key', 'Chiave idempotente di 8–128 caratteri richiesta')

    def _event(self, vault, author, operation, kind, entity, question, payload, parents):
        return dict(format_version=1, vault_id=vault, event_id=str(uuid4()), kind=kind,
                    entity_id=entity, question_id=question, operation_id=operation, author_id=author,
                    created_at=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
                    parents=parents, payload=payload)

    def _requests(self, root):
        path = self._local(root) / 'shared-requests.sqlite'
        for candidate in (path, Path(str(path) + '-journal'), Path(str(path) + '-wal'), Path(str(path) + '-shm')):
            _no_link(candidate)
        return _connection(path)

    def _mutate(self, vault, body, kind, factory):
        root = self._root(vault)
        with VaultLock(root):
            self._readable(root)
            snapshot = capture_snapshot(root)
            current = snapshot_events(snapshot, vault)
            digest = content_hash({'kind': kind, 'body': body})
            with self._requests(root) as db:
                db.execute('CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY, digest TEXT NOT NULL, events BLOB NOT NULL)')
                row = db.execute('SELECT digest,events FROM requests WHERE key=?', (body['idempotency_key'],)).fetchone()
                if row:
                    if row[0] != digest:
                        raise ContractError('idempotency_conflict', 'Chiave già usata con dati diversi')
                    events = parse_json(row[1])['events']
                else:
                    events = factory(root, current, self._author(root), str(uuid4()))
                    project(current + events, vault, allow_pending=False)
                    db.execute('INSERT INTO requests VALUES(?,?,?)',
                               (body['idempotency_key'], digest, canonical_json({'events': events})))
            # The request is durable before the first immutable event is linked.
            project(current + events, vault, allow_pending=False)
            snapshot.assert_unchanged(root)
            self._append(root, events)
            return {'event_ids': [e['event_id'] for e in events],
                    'operation_id': events[-1]['operation_id'] if events else None, 'state': 'archived'}

    def _append(self, root, events):
        if not events: return
        directory = root / '.teseo/shared/events'
        for path in (root / '.teseo/shared', directory):
            _no_link(path); path.mkdir(exist_ok=True)
        for event in events:
            destination = directory / (event['event_id'] + '.json')
            _no_link(destination)
            data = canonical_json(event)
            if destination.exists():
                if destination.read_bytes() != data:
                    raise ContractError('event_collision', 'File evento già presente con byte diversi')
                continue
            staged = self._local(root) / ('.shared-stage-' + str(uuid4()))
            try:
                with staged.open('xb') as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                try:
                    os.link(staged, destination)
                except FileExistsError:
                    _no_link(destination)
                    if destination.read_bytes() != data:
                        raise ContractError('event_collision', 'Evento creato contemporaneamente con dati diversi')
            finally:
                staged.unlink(missing_ok=True)

    def record(self, vault_id, body):
        self._body(body, {'question_id','question_text','pages','text','idempotency_key','share_confirmed'})
        _list(body['pages'], _page)
        _text(body['text'])
        if body['question_id'] is None: _text(body['question_text'])
        else: _uuid(body['question_id'])
        def factory(root, current, author, operation):
            state = project(current, vault_id)
            questions = {q['question_id']: q for q in state['questions']}
            question = body['question_id']
            events = []
            if question is None:
                question = str(uuid4())
                anchors = [{'page': page, 'signal': 'nota-utente'} for page in body['pages']]
                registration = self._event(vault_id, author, operation, 'question.registered', question, question,
                                           {'text': body['question_text'], 'anchors': anchors}, [])
                events.append(registration); parents = [registration['event_id']]
            else:
                if question not in questions: raise ContractError('question_missing', 'Domanda condivisa non trovata')
                parents = questions[question]['heads']
            events.append(self._event(vault_id, author, operation, 'answer.recorded', str(uuid4()), question,
                                      {'text': body['text'], 'pages': body['pages'], 'source':'nota-utente'}, parents))
            return events
        return self._mutate(vault_id, body, 'answer', factory)

    def decision(self, vault_id, body):
        self._body(body, {'question_id','heads','decision','reason','idempotency_key','share_confirmed'})
        _uuid(body['question_id']); _list(body['heads'], _uuid)
        _text(body['reason'], 4096)
        def factory(root, current, author, operation):
            state = project(current, vault_id)
            question = next((q for q in state['questions'] if q['question_id'] == body['question_id']), None)
            if question is None: raise ContractError('question_missing', 'Domanda condivisa non trovata')
            required = set(question['heads'])
            for conflict in state['conflicts']:
                if conflict['entity_id'] == body['question_id']: required.update(conflict['heads'])
            if not isinstance(body['heads'], list) or set(body['heads']) != required:
                raise ContractError('shared_heads_stale', 'Rileggere tutti gli head correnti prima della decisione')
            kind='question.deferred' if body['decision']=='defer' else 'question.decided'
            payload={'reason':body['reason']} if kind=='question.deferred' else {'decision':body['decision'],'reason':body['reason']}
            return [self._event(vault_id, author, operation, kind, body['question_id'], body['question_id'], payload, sorted(required))]
        return self._mutate(vault_id, body, 'decision', factory)

    def preview(self, vault_id, body=None):
        if body not in (None, {}): raise ContractError('invalid_parameters', 'Preview senza parametri')
        root = self._root(vault_id)
        with VaultLock(root):
            self._readable(root)
            return LegacyMigration(root, vault_id, self._author(root)).preview()

    def export(self, vault_id, body):
        self._body(body, {'preview_id','selection_ids','idempotency_key','share_confirmed'})
        return self._mutate(vault_id, body, 'legacy-export',
            lambda root, current, author, operation: LegacyMigration(root, vault_id, author).export(body['selection_ids'], body['preview_id']))

    def import_state(self, vault_id, body=None):
        if body not in (None, {}): raise ContractError('invalid_parameters', 'Import senza parametri')
        from .shared_state import rebuild_projection
        root = self._root(vault_id)
        with VaultLock(root):
            self._readable(root)
            snapshot = capture_snapshot(root)
            events = snapshot_events(snapshot, vault_id)
            path = self._local(root) / 'shared-state.sqlite'
            for candidate in (path, Path(str(path)+'-journal'), Path(str(path)+'-wal'), Path(str(path)+'-shm')):
                _no_link(candidate)
            result = rebuild_projection(path, events, vault_id)
            snapshot.assert_unchanged(root)
            return result

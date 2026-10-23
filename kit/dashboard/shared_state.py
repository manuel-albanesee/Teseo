"""Eventi condivisi v1: validazione pura, DAG causale e cache SQLite rigenerabile.

Il clock e l'autore sono informativi. Nessun evento esegue codice o modifica note.
La cache non sostituisce i file immutabili del vault.
"""
from datetime import datetime
from pathlib import Path
import re
import sqlite3
from uuid import UUID

from .contracts import ContractError, canonical_json, content_hash, parse_json, portable_path

MAX_EVENTS = 2048
MAX_EVENT_BYTES = 65536
COMMON = {'format_version', 'vault_id', 'event_id', 'kind', 'entity_id', 'question_id',
          'operation_id', 'author_id', 'created_at', 'parents', 'payload'}
FIELDS = {
    'question.registered': {'text', 'anchors'},
    'question.deferred': {'reason'},
    'question.decided': {'decision', 'reason'},
    'synthesis.discarded': {'question', 'reason', 'pages'},
    'answer.recorded': {'text', 'pages', 'source'},
    'answer.superseded': {'replacement_id'},
    'answer.consolidated': {'answer_ids', 'note_hashes', 'checkpoint_id'},
    'page.renamed': {'from', 'to'},
}


def _fail(message, code='invalid_event'):
    raise ContractError(code, message)


def _uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
            _fail('UUID canonico richiesto')
    except (ValueError, AttributeError):
        _fail('UUID canonico richiesto')
    return value


def _text(value, limit=16384):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        _fail('Testo evento non valido o troppo grande')


def _page(value):
    _text(value, 240)
    portable_path(value)
    if '/' in value or value in {'.', '..'} or value.lower().endswith('.md'):
        _fail('ID pagina non valido')


def _list(value, validator, maximum=128, nonempty=False):
    if not isinstance(value, list) or len(value) > maximum or (nonempty and not value):
        _fail('Lista evento non valida')
    for item in value:
        validator(item)
    if len({canonical_json({'v': item}) for item in value}) != len(value):
        _fail('Lista evento duplicata')


def validate_event(event, vault_id, filename=None):
    """Rifiuta versioni, campi eseguibili/sconosciuti e identità non canoniche."""
    if not isinstance(event, dict) or set(event) != COMMON:
        _fail('Campi comuni evento non validi')
    if type(event['format_version']) is not int or event['format_version'] != 1:
        _fail('Versione evento non supportata', 'event_version')
    _uuid(vault_id)
    for field in ('vault_id', 'event_id', 'entity_id', 'question_id', 'operation_id', 'author_id'):
        _uuid(event[field])
    if event['vault_id'] != vault_id:
        _fail('Evento di un altro vault', 'event_vault')
    if filename is not None and filename != event['event_id'] + '.json':
        _fail('Nome file diverso da event_id', 'event_filename')
    stamp = event['created_at']
    if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', stamp):
        _fail('Timestamp UTC richiesto')
    try:
        datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        _fail('Timestamp UTC non valido')
    _list(event['parents'], _uuid)
    kind, payload = event['kind'], event['payload']
    if not isinstance(kind, str) or kind not in FIELDS or not isinstance(payload, dict) or set(payload) != FIELDS[kind]:
        _fail('Tipo o payload evento non valido')
    if kind.startswith('question.') and event['entity_id'] != event['question_id']:
        _fail('Identità domanda incoerente')
    if kind == 'question.registered':
        _text(payload['text']); _list(payload['anchors'], lambda a: _anchor(a))
    if kind in {'question.deferred', 'question.decided', 'synthesis.discarded'}:
        _text(payload['reason'], 4096)
    if kind == 'question.decided' and (not isinstance(payload['decision'], str) or payload['decision'] not in {'open', 'reopen', 'closed', 'accepted', 'rejected'}):
        _fail('Decisione non supportata')
    if kind == 'synthesis.discarded':
        _text(payload['question']); _list(payload['pages'], _page)
    if kind == 'answer.recorded':
        _text(payload['text']); _list(payload['pages'], _page)
        if payload['source'] != 'nota-utente':
            _fail('Fonte risposta non supportata')
    if kind == 'answer.superseded':
        _uuid(payload['replacement_id'])
        if payload['replacement_id'] == event['entity_id']:
            _fail('Una risposta non può sostituire se stessa')
    if kind == 'answer.consolidated':
        _list(payload['answer_ids'], _uuid, nonempty=True); _uuid(payload['checkpoint_id'])
        hashes = payload['note_hashes']
        if not isinstance(hashes, dict) or not hashes or len(hashes) > 128:
            _fail('Hash note obbligatori')
        for name, digest in hashes.items():
            portable_path(name)
            if not name.startswith('wiki/') or not name.endswith('.md') or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                _fail('Hash o percorso nota non valido')
        if event['entity_id'] not in payload['answer_ids']:
            _fail('Entità consolidamento non inclusa')
    if kind == 'page.renamed':
        _page(payload['from']); _page(payload['to'])
        if payload['from'] == payload['to']:
            _fail('Rinomina identica')
    if len(canonical_json(event)) > MAX_EVENT_BYTES:
        _fail('Evento troppo grande')
    return parse_json(canonical_json(event))


def _anchor(anchor):
    if not isinstance(anchor, dict) or set(anchor) not in ({'page', 'signal'}, {'page', 'signal', 'legacy_key'}):
        _fail('Ancora non valida')
    _page(anchor['page']); _text(anchor['signal'], 240)
    if 'legacy_key' in anchor:
        _text(anchor['legacy_key'], 1024)


def snapshot_events(snapshot, vault_id):
    """Legge soltanto eventi nei byte già catturati, senza accesso al filesystem."""
    events = []
    for entry in snapshot.files:
        if not entry.path.startswith('.teseo/shared/'):
            continue
        parts = entry.path.split('/')
        if len(parts) != 4 or parts[:3] != ['.teseo', 'shared', 'events']:
            _fail('Percorso evento non valido', 'event_filename')
        if len(entry.data) > MAX_EVENT_BYTES:
            _fail('Evento troppo grande')
        event = validate_event(parse_json(entry.data), vault_id, parts[3])
        if canonical_json(event) != entry.data:
            _fail('Byte evento non canonici', 'event_canonical')
        events.append(event)
        if len(events) > MAX_EVENTS:
            _fail('Troppi eventi')
    return sorted(events, key=lambda e: e['event_id'])


def project(events, vault_id, allow_pending=True):
    """Proiezione deterministica del medesimo insieme, con conflitti visibili."""
    if not isinstance(events, list) or len(events) > MAX_EVENTS * 2:
        _fail('Insieme eventi troppo grande')
    _uuid(vault_id)
    by_id = {}
    for raw in events:
        event = validate_event(raw, vault_id)
        key = event['event_id']
        if key in by_id and by_id[key] != event:
            _fail('ID evento riutilizzato con contenuto diverso', 'event_collision')
        by_id[key] = event
    if len(by_id) > MAX_EVENTS:
        _fail('Troppi eventi')
    # Kahn considera tutti gli archi noti: anche un ciclo con parent assenti blocca.
    dependencies = {key: set(e['parents']) & by_id.keys() for key, e in by_id.items()}
    children = {key: set() for key in by_id}
    for key, parents in dependencies.items():
        for parent in parents:
            children[parent].add(key)
    ready = sorted(key for key in by_id if not dependencies[key]); order = []
    while ready:
        key = ready.pop(0); order.append(key)
        for child in sorted(children[key]):
            dependencies[child].discard(key)
            if not dependencies[child]:
                ready.append(child); ready.sort()
    if len(order) != len(by_id):
        _fail('Ciclo causale negli eventi', 'event_cycle')
    ancestors, pending = {}, set()
    for key in order:
        e = by_id[key]; parents = set(e['parents'])
        ancestors[key] = parents | set().union(*(ancestors[p] for p in parents if p in ancestors))
        if any(p not in by_id or p in pending for p in parents):
            pending.add(key)
    if pending and not allow_pending:
        _fail('Parent mancanti nel candidato completo', 'event_pending')
    active = [by_id[k] for k in order if k not in pending]
    registrations, answers = {}, {}
    for e in active:
        if e['kind'] == 'question.registered':
            q = e['question_id']
            if q in registrations:
                _fail('Registrazione domanda duplicata', 'entity_collision')
            registrations[q] = e
        if e['kind'] == 'answer.recorded':
            a = e['entity_id']
            if a in answers:
                _fail('Registrazione risposta duplicata', 'entity_collision')
            answers[a] = e
    if registrations.keys() & answers.keys():
        _fail('UUID globale riutilizzato tra domanda e risposta', 'entity_collision')
    def causal(e, reference):
        if reference is None or reference['event_id'] not in ancestors[e['event_id']]:
            _fail('Riferimento senza antenato causale', 'event_reference')
    for e in active:
        kind = e['kind']
        if kind not in {'question.registered', 'page.renamed'}:
            causal(e, registrations.get(e['question_id']))
        if kind in {'answer.superseded', 'answer.consolidated'}:
            ids = e['payload'].get('answer_ids', [e['entity_id']])
            if kind == 'answer.superseded':
                ids = ids + [e['payload']['replacement_id']]
            for answer_id in ids:
                answer = answers.get(answer_id)
                causal(e, answer)
                if answer['question_id'] != e['question_id']:
                    _fail('Riferimento a risposta di altra domanda', 'event_reference')
    def heads(items):
        return sorted(e['event_id'] for e in items if not any(e['event_id'] in ancestors[o['event_id']] for o in items))
    conflicts = []
    def conflict(kind, entity_id, ids):
        conflicts.append({'kind':kind, 'entity_id':entity_id, 'heads':sorted(ids)})
    renames = {}
    rename_groups = {}
    for e in active:
        if e['kind'] == 'page.renamed':
            rename_groups.setdefault(e['payload']['from'], []).append(e)
    for old, items in sorted(rename_groups.items()):
        latest = heads(items); targets = {by_id[i]['payload']['to'] for i in latest}
        if len(targets) > 1:
            conflict('page.rename', old, latest)
        else:
            renames[old] = targets.pop()
    def mapped(page):
        seen = set()
        while page in renames:
            if page in seen:
                _fail('Ciclo mapping pagine', 'rename_cycle')
            seen.add(page); page = renames[page]
        return page
    for old in list(renames):
        renames[old] = mapped(old)
    result_answers = []
    for identity, original in sorted(answers.items()):
        actions = [e for e in active if (e['kind'] == 'answer.superseded' and e['entity_id'] == identity) or (e['kind'] == 'answer.consolidated' and identity in e['payload']['answer_ids'])]
        latest = heads(actions); state = 'archived'
        if latest:
            signatures = {canonical_json({'kind':by_id[i]['kind'], 'payload':by_id[i]['payload']}) for i in latest}
            if len(signatures) > 1:
                state = 'needs_decision'; conflict('answer.state', identity, latest)
            else:
                state = 'consolidated' if by_id[latest[0]]['kind'] == 'answer.consolidated' else 'superseded'
        result_answers.append({'entity_id':identity, 'question_id':original['question_id'], 'text':original['payload']['text'], 'pages':sorted({mapped(p) for p in original['payload']['pages']}), 'source':original['payload']['source'], 'state':state, 'heads':latest or [original['event_id']], 'event_id':original['event_id']})
    result_questions = []
    for identity, original in sorted(registrations.items()):
        actions = [e for e in active if e['question_id'] == identity and e['kind'] in {'question.deferred','question.decided'}]
        latest = heads(actions); state = 'open'
        if len(latest) > 1:
            state = 'needs_decision'; conflict('question.decision', identity, latest)
        elif latest:
            e=by_id[latest[0]]
            state = 'deferred' if e['kind']=='question.deferred' else ('open' if e['payload']['decision'] in {'open','reopen'} else 'closed')
        current_answers = [a for a in result_answers if a['question_id']==identity and a['state']!='superseded']
        if len({a['text'] for a in current_answers}) > 1:
            ids = sorted(a['event_id'] for a in current_answers)
            resolved = any(e['kind']=='question.decided' and set(ids) <= ancestors[e['event_id']] for e in actions if e['event_id'] in latest)
            if not resolved:
                conflict('question.answers', identity, ids)
                state='needs_decision'
        # Longest causal chain, so sibling deferrals cannot increment twice.
        depths = {}
        for e in actions:
            if e['kind']=='question.deferred':
                depths[e['event_id']] = 1 + max((n for k,n in depths.items() if k in ancestors[e['event_id']]), default=0)
        result_questions.append({'question_id':identity,'entity_id':identity,'text':original['payload']['text'],'anchors':[{**a,'page':mapped(a['page'])} for a in original['payload']['anchors']], 'state':state,'heads':heads([e for e in active if e['question_id']==identity and e['kind']!='page.renamed']), 'defer_count':max(depths.values(),default=0)})
    return {'format_version':1,'vault_id':vault_id,'answers':result_answers,'questions':result_questions,'conflicts':sorted(conflicts,key=lambda c:(c['kind'],c['entity_id'])),'pending':sorted(pending),'renames':renames,'heads':heads(active),'event_count':len(by_id),'digest':content_hash({'events':[by_id[k] for k in sorted(by_id)]})}


def import_events(db_path, events, vault_id):
    """Merge transazionale locale: duplicati no-op, collisioni rollback completo.

    Il chiamante sceglie un percorso locale fidato; nessuna scrittura nel vault.
    Anche gli eventi pending restano nel ledger per import successivi.
    """
    path = Path(db_path)
    if path.is_symlink() or getattr(path, 'is_junction', lambda:False)():
        _fail('Cache collegata non ammessa', 'linked_path')
    db = sqlite3.connect(path)
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS applied_events (event_id TEXT PRIMARY KEY, event_hash TEXT NOT NULL, event_json BLOB NOT NULL, vault_id TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS shared_projection (singleton INTEGER PRIMARY KEY CHECK(singleton=1), vault_id TEXT NOT NULL, projection_json BLOB NOT NULL)')
        stored = []
        for identity, digest, raw, owner in db.execute('SELECT event_id,event_hash,event_json,vault_id FROM applied_events'):
            if owner != vault_id:
                _fail('Cache di un altro vault', 'event_vault')
            item = parse_json(raw)
            if item['event_id'] != identity or content_hash(item) != digest:
                _fail('Ledger locale incoerente', 'event_collision')
            stored.append(item)
        projection = project(stored + events, vault_id)
        for raw in events:
            e = validate_event(raw, vault_id)
            db.execute('INSERT OR IGNORE INTO applied_events VALUES (?,?,?,?)', (e['event_id'],content_hash(e),canonical_json(e),vault_id))
        db.execute('INSERT OR REPLACE INTO shared_projection VALUES (1,?,?)',(vault_id,canonical_json(projection)))
        db.commit()
        return projection
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def validate_snapshot(snapshot, vault_id=None, allow_pending=False):
    """Valida l'insieme completo; il manifest è l'autorità per vault_id."""
    from .contracts import parse_manifest
    manifests = [entry for entry in snapshot.files if entry.path == '.teseo/project.json']
    if manifests:
        owner = parse_manifest(manifests[0].data)['vault_id']
        if vault_id is not None and vault_id != owner:
            _fail('Manifest di un altro vault', 'event_vault')
        vault_id = owner
    if vault_id is None:
        _fail('Identità vault obbligatoria', 'event_vault')
    return project(snapshot_events(snapshot, vault_id), vault_id, allow_pending=allow_pending)


def rebuild_projection(db_path, events, vault_id):
    """Ricostruisce soltanto la cache dall'insieme esatto post-checkpoint.

    Consente rollback dei file applicati eliminando righe derivate obsolete.
    Gli ID che rimangono non possono cambiare contenuto. Non elimina eventi
    condivisi né accede ai database personali.
    """
    projection = project(events, vault_id)
    path = Path(db_path)
    if path.is_symlink() or getattr(path, 'is_junction', lambda:False)():
        _fail('Cache collegata non ammessa', 'linked_path')
    db = sqlite3.connect(path)
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS applied_events (event_id TEXT PRIMARY KEY, event_hash TEXT NOT NULL, event_json BLOB NOT NULL, vault_id TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS shared_projection (singleton INTEGER PRIMARY KEY CHECK(singleton=1), vault_id TEXT NOT NULL, projection_json BLOB NOT NULL)')
        wanted = {e['event_id']:e for e in events}
        for identity, digest, raw, owner in db.execute('SELECT event_id,event_hash,event_json,vault_id FROM applied_events'):
            item = parse_json(raw)
            if owner != vault_id:
                _fail('Cache di un altro vault', 'event_vault')
            if item['event_id'] != identity or content_hash(item) != digest or (identity in wanted and content_hash(wanted[identity]) != digest):
                _fail('ID evento modificato o ledger incoerente', 'event_collision')
        db.execute('DELETE FROM applied_events')
        db.executemany('INSERT INTO applied_events VALUES (?,?,?,?)',[(e['event_id'],content_hash(e),canonical_json(e),vault_id) for e in wanted.values()])
        db.execute('INSERT OR REPLACE INTO shared_projection VALUES (1,?,?)',(vault_id,canonical_json(projection)))
        db.commit()
    finally:
        db.close()
    return projection

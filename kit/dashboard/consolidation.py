"""UUID selezionati, note giustificate e merge dei soli eventi sopraggiunti."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .contracts import ContractError, canonical_json, rebased_rel, resolve_path
from .storage import Snapshot, SnapshotFile, capture_snapshot
from .shared_state import snapshot_events, validate_snapshot
from .read_api import _parser

PREFIX='.teseo/shared/events/'


def selection(base,answer_ids,vault):
    if (not isinstance(answer_ids,list) or len(answer_ids)>128 or any(not isinstance(value,str) for value in answer_ids)
            or len(answer_ids)!=len(set(answer_ids))):
        raise ContractError('invalid_response_ids','Selezione UUID risposte non valida')
    for value in answer_ids:
        try:
            if str(UUID(value))!=value: raise ValueError
        except (ValueError,TypeError):
            raise ContractError('invalid_response_ids','Richiesti UUID risposta canonici') from None
    original=validate_snapshot(base,vault)
    answers={a['entity_id']:a for a in original['answers']}
    conflicted={q['question_id'] for q in original['questions'] if q['state']=='needs_decision'}
    for identity in answer_ids:
        answer=answers.get(identity)
        if not answer or answer['state'] not in ('archived','needs_decision'):
            raise ContractError('invalid_response_ids','Risposta non pendente nello snapshot iniziale')
        if answer['question_id'] in conflicted:
            raise ContractError('answer_conflict','Risolvere esplicitamente il conflitto prima del consolidamento')
        if answer['state']=='needs_decision':
            events=snapshot_events(base,vault); by_id={e['event_id']:e for e in events}
            accepted=[]
            for event in events:
                if event['kind']!='question.decided' or event['question_id']!=answer['question_id'] or event['payload']['decision']!='accepted': continue
                ancestors=set(); todo=list(event['parents'])
                while todo:
                    parent=todo.pop()
                    if parent in ancestors:continue
                    ancestors.add(parent);todo.extend(by_id[parent]['parents'])
                if set(answer['heads'])<=ancestors:accepted.append(event['event_id'])
            if not accepted:
                raise ContractError('answer_conflict','Accettare una revisione causale che includa tutti i checkpoint in conflitto')
            answers[identity]=dict(answer,resolution_parents=accepted)
    return answers


def prepare(journal, record, candidate, answer_ids):
    root=journal.lock.root
    base=capture_snapshot(resolve_path(root,record['snapshot_path']))
    if base.digest!=record['base_content_digest']:
        raise ContractError('snapshot_corrupt','Snapshot iniziale alterato')
    vault=record['vault_id']
    answers=selection(base,answer_ids,vault)
    before_events={p:h for p,h in base.hashes.items() if p.startswith(PREFIX)}
    proposed_events={p:h for p,h in candidate.hashes.items() if p.startswith(PREFIX)}
    if before_events!=proposed_events:
        raise ContractError('event_write_forbidden','Il client non può scrivere o rimuovere eventi condivisi')
    # Rebase only immutable additions: live Markdown/raw/identity may never drift.
    live=capture_snapshot(root)
    values={entry.path:entry.data for entry in candidate.files}
    if live.digest!=base.digest:
        if (any(live.hashes.get(p)!=h for p,h in base.hashes.items())
                or any(not p.startswith(PREFIX) for p in set(live.hashes)-set(base.hashes))):
            raise ContractError('blocked_external_change','Modifiche estranee alle nuove risposte: nessun apply')
        validate_snapshot(live,vault)
        initial_ids={e['event_id'] for e in snapshot_events(base,vault)}
        additions=[e for e in snapshot_events(live,vault) if e['event_id'] not in initial_ids]
        if any(e['kind'] not in ('question.registered','answer.recorded') for e in additions):
            raise ContractError('blocked_external_change','Decisioni o consolidamenti sopraggiunti: revisionare un nuovo ciclo')
        for entry in live.files:
            if entry.path.startswith(PREFIX): values[entry.path]=entry.data
        record['client_snapshot_path']=record['snapshot_path']
        record['client_base_content_digest']=base.digest
        relative=rebased_rel(record['operation_id'],uuid4())
        journal._persist_snapshot(relative,live)
        record.update(snapshot_path=relative,base_content_digest=live.digest,before=live.hashes)
        base=live
    checkpoint_id=str(uuid4())
    authorized=[]
    parser=_parser()
    from .shared_service import author_id
    author=author_id(root) if answer_ids else None
    for identity in answer_ids:
        answer=answers[identity]
        supported={}
        for page in answer['pages']:
            path='wiki/'+page+'.md'
            if path not in values or base.hashes.get(path)==candidate.hashes.get(path): continue
            text=values[path].decode('utf-8')
            fm,body=parser.leggi_testo(text,page)
            if 'nota-utente' in parser.valori(fm.get('fonti')) and answer['text'] in body:
                import hashlib
                supported[path]=hashlib.sha256(values[path]).hexdigest()
        if not supported:
            raise ContractError('answer_not_supported','Risposta da riportare testualmente in una nota modificata con fonte nota-utente')
        event={'format_version':1,'vault_id':vault,'event_id':str(uuid4()),'kind':'answer.consolidated',
            'entity_id':identity,'question_id':answer['question_id'],'operation_id':record['operation_id'],
            'author_id':author,'created_at':datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
            'parents':sorted(set(answer['heads']+answer.get('resolution_parents',[]))),'payload':{'answer_ids':[identity],'note_hashes':supported,'checkpoint_id':checkpoint_id}}
        path=PREFIX+event['event_id']+'.json'
        values[path]=canonical_json(event);authorized.append(path)
    candidate=Snapshot(tuple(SnapshotFile(path,data) for path,data in sorted(values.items())))
    validate_snapshot(candidate,vault)
    record.update(logical_checkpoint_id=checkpoint_id,processed_response_ids=answer_ids,authorized_event_paths=authorized)
    journal._save(record)
    return base,candidate,checkpoint_id


def validate_added_events(base,candidate,authorized):
    before={p:h for p,h in base.hashes.items() if p.startswith(PREFIX)}
    after={p:h for p,h in candidate.hashes.items() if p.startswith(PREFIX)}
    if any(after.get(p)!=h for p,h in before.items()) or set(after)-set(before)!=set(authorized):
        raise ContractError('event_write_forbidden','Solo gli eventi di consolidamento preparati dal coordinator sono ammessi')
    projection=validate_snapshot(candidate)
    return projection

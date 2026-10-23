"""Cicli skill persistenti: output isolato, ricevute e nessun successo implicito."""
import hashlib
from pathlib import Path
import re
import secrets
import threading
import time
import subprocess
import sys

from .contracts import ContractError, canonical_json, content_hash, resolve_path, portable_path
from .storage import Journal, VaultLock, capture_snapshot, _no_link
from .jobs import _public

KINDS = {'ingest_lint', 'lint', 'fill_gaps'}
FINAL = {'succeeded', 'failed', 'cancelled', 'blocked_external_change', 'rolled_back'}
WAITING = {'awaiting_client', 'awaiting_user', 'prepared', 'recovery_required', 'applying'}


def _fields(body, names):
    if not isinstance(body, dict) or set(body) != set(names):
        raise ContractError('invalid_operation', 'Campi operazione non validi')


class SkillCoordinator:
    def __init__(self, registry, adapters=None):
        self.registry = registry
        self.adapters = adapters or {}
        self._mutex = threading.RLock()
        self._stop = False

    def active(self, vault_id):
        # No threads or live Markdown writes while a client works on its copy.
        return None

    def _records(self, journal):
        return [journal.get(row[0]) for row in journal.db.execute('SELECT operation_id FROM operations ORDER BY rowid')
                if journal.get(row[0])['kind'] in KINDS]

    def _save(self, journal, record):
        journal._save(record)

    def submit(self, vault_id, body):
        _fields(body, ('kind', 'inputs', 'base_content_digest', 'adapter', 'idempotency_key', 'scope'))
        if (not isinstance(body['kind'],str) or body['kind'] not in KINDS
                or not isinstance(body['adapter'],str) or body['adapter'] not in self.adapters
                or not isinstance(body['idempotency_key'], str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}', body['idempotency_key'])
                or not isinstance(body['base_content_digest'], str) or not re.fullmatch('[0-9a-f]{64}', body['base_content_digest'])):
            raise ContractError('invalid_operation', 'Tipo, adapter, digest o chiave non validi')
        for field in ('inputs', 'scope'):
            if not isinstance(body[field], list) or len(body[field]) > 100 or any(not isinstance(p, str) for p in body[field]):
                raise ContractError('invalid_operation', 'Percorsi operazione non validi')
            if len(body[field]) != len(set(body[field])):
                raise ContractError('invalid_operation', 'Percorsi duplicati')
            for path in body[field]:
                portable_path(path)
        if (not body['scope'] or any(p not in ('wiki/', 'Wiki reference.md', 'index.md', 'log.md')
                and not (p.startswith('wiki/') and p.count('/') == 1 and p.endswith('.md')) for p in body['scope'])
                or any(not p.startswith('raw/') or p.endswith('/') for p in body['inputs'])
                or (body['kind'] == 'ingest_lint') != bool(body['inputs'])):
            raise ContractError('invalid_operation', 'Selezionare fonti raw per ingest e un perimetro Markdown esplicito')
        with self._mutex:
            if self._stop:
                raise ContractError('service_stopping', 'Servizio in arresto')
            root = self.registry.root(vault_id)
            with VaultLock(root) as lock, Journal(lock) as journal:
                previous = journal.find_request(body['kind'], body, body['idempotency_key'])
                if previous:
                    return _public(previous)
                snapshot = capture_snapshot(root)
                if snapshot.digest != body['base_content_digest']:
                    raise ContractError('blocked_external_change', 'Base cambiata: aggiornare la vista')
                if any(p not in snapshot.hashes for p in body['inputs']):
                    raise ContractError('invalid_operation', 'Fonte selezionata non presente')
                if sum(r['state'] not in FINAL for r in self._records(journal)) >= 8:
                    raise ContractError('job_limit', 'Otto cicli già pendenti nel vault')
                record = journal.create(body['kind'], body, body['idempotency_key'], snapshot,initial={
                    'state':'queued', 'request':body, 'phases':{'ingest': 'pending' if body['kind']=='ingest_lint' else 'skipped', 'lint':'pending'},
                    'receipts':{}, 'publication_eligible':False, 'expires_at':int(time.time())+86400})
                self._advance(journal)
                return _public(journal.get(record['operation_id']))

    def _advance(self, journal):
        records = self._records(journal)
        if any(r['state'] not in FINAL | {'queued'} for r in records):
            return
        # Ontology recovery/apply excludes dispatch; queue stays durable.
        try:
            journal.assert_notes_idle()
        except ContractError:
            return
        for record in records:
            if record['state'] != 'queued':
                continue
            if capture_snapshot(journal.lock.root).digest != record['base_content_digest']:
                record.update(state='blocked_external_change', error={'code':'blocked_external_change','message':'Base cambiata durante la coda; creare nuovo ciclo'})
                self._save(journal, record)
                continue
            try:
                record['state'] = 'preparing'
                self._save(journal, record)
                base = capture_snapshot(resolve_path(journal.lock.root, record['snapshot_path']))
                if base.digest != record['base_content_digest']:
                    raise ContractError('snapshot_corrupt', 'Snapshot base alterato')
                relative = '.teseo/local/skill-jobs/' + record['operation_id'] + '/workspace'
                journal._persist_snapshot(relative, base)
                record['workspace_path'] = relative
                record['phase'] = 'ingest' if record['kind'] == 'ingest_lint' else 'lint'
                self._handoff(journal, record)
                break
            except Exception as error:
                record.update(state='failed', error={'code':getattr(error,'code','prepare_failed'),'message':'Preparazione area isolata non riuscita; output conservato'})
                self._save(journal, record)

    def _handoff(self, journal, record):
        token = secrets.token_urlsafe(32)
        record['token_hash'] = hashlib.sha256(token.encode()).hexdigest()
        workspace = resolve_path(journal.lock.root, record['workspace_path'])
        parent = workspace.parent
        request_path = parent / 'request.json'
        _no_link(request_path)
        request = {'operation_id':record['operation_id'], 'base_content_digest':record['base_content_digest'],
                   'phase':record['phase'], 'token':token, 'workspace':str(workspace), 'scope':record['request']['scope'],
                   'inputs':record['request']['inputs'], 'receipt_path':str(parent / 'receipt.json')}
        request_path.write_bytes(canonical_json(request))
        adapter = self.adapters[record['request']['adapter']]
        record['handoff'] = adapter.prepare(workspace, request_path, record['request'], record['phase'])
        record.update(state='awaiting_client', error=None)
        record['phases'][record['phase']] = 'awaiting_client'
        self._save(journal, record)

    def complete(self, vault_id, identifier, body):
        _fields(body, ('receipt',))
        receipt = body['receipt']
        _fields(receipt, ('operation_id','base_content_digest','phase','token','outcome','files','processed_response_ids','checks','reason'))
        if (receipt['operation_id'] != identifier or receipt['phase'] not in ('ingest','lint')
                or receipt['outcome'] not in ('succeeded','failed','awaiting_user')
                or not isinstance(receipt['token'],str) or len(receipt['token']) > 128
                or not isinstance(receipt['reason'],str) or len(receipt['reason']) > 2000
                or not isinstance(receipt['files'],dict) or len(receipt['files']) > 1000
                or not isinstance(receipt['checks'],dict) or not isinstance(receipt['processed_response_ids'],list)):
            raise ContractError('invalid_receipt', 'Ricevuta non valida')
        token_hash = hashlib.sha256(receipt['token'].encode()).hexdigest()
        digest = content_hash(receipt)
        with self._mutex:
            if self._stop:
                raise ContractError('service_stopping', 'Servizio in arresto')
            with VaultLock(self.registry.root(vault_id)) as lock, Journal(lock) as journal:
                record = self._get(journal, identifier)
                previous = record['receipts'].get(receipt['phase'])
                if previous and secrets.compare_digest(previous['token_hash'], token_hash):
                    if previous['digest'] != digest:
                        raise ContractError('receipt_conflict', 'Ricevuta già consumata con contenuto diverso')
                    return _public(record)
                if (record['state'] != 'awaiting_client' or receipt['phase'] != record['phase']
                        or receipt['base_content_digest'] != record['base_content_digest']
                        or not secrets.compare_digest(record['token_hash'], token_hash)):
                    raise ContractError('invalid_receipt', 'Token, fase o base non corrispondenti')
                if time.time() > record['expires_at']:
                    record.update(state='failed',error={'code':'operation_timeout','message':'Ciclo scaduto; output isolato conservato'})
                    self._save(journal,record)
                    self._advance(journal)
                    return _public(record)
                workspace = resolve_path(lock.root, record['workspace_path'])
                candidate = capture_snapshot(workspace)
                if receipt['files'] != candidate.hashes:
                    raise ContractError('receipt_manifest_mismatch', 'Manifest ricevuta diverso dai byte isolati')
                if receipt['processed_response_ids']:
                    raise ContractError('shared_mapping_unavailable', 'Consolidamento risposte richiede il passo 5')
                record['receipts'][receipt['phase']] = {'digest':digest,'token_hash':token_hash,
                    'outcome':receipt['outcome'],'files':candidate.hashes,'checks':receipt['checks'],'reason':receipt['reason']}
                record['phases'][record['phase']] = receipt['outcome']
                if receipt['outcome'] != 'succeeded':
                    record.update(state='awaiting_user' if receipt['outcome']=='awaiting_user' else 'failed',
                                  error={'code':receipt['outcome'],'message':receipt['reason'] or 'Fase non completata'})
                    self._save(journal,record)
                elif record['phase']=='ingest':
                    record['phase']='lint'
                    self._handoff(journal,record)
                else:
                    self._validate(journal, record, candidate)
                self._advance(journal)
                return _public(journal.get(identifier))

    def _validate(self, journal, record, candidate):
        try:
            from .operation_validation import validate_candidate
        except ImportError:
            record.update(state='failed',error={'code':'validation_unavailable','message':'Pipeline deterministica non ancora disponibile; nessun apply'})
            self._save(journal,record)
            return
        from .graph_service import rebuild
        record['state']='validating'
        self._save(journal,record)
        try:
            base = capture_snapshot(resolve_path(journal.lock.root, record['snapshot_path']))
            if base.digest != record['base_content_digest']:
                raise ContractError('snapshot_corrupt','Snapshot base alterato')
            result = validate_candidate(base,candidate,kind=record['kind'],inputs=record['request']['inputs'],scope=record['request']['scope'])
            rebuild(resolve_path(journal.lock.root, record['workspace_path']))
            workspace=resolve_path(journal.lock.root,record['workspace_path'])
            runtime=Path(__file__).resolve().parents[1]
            helper=runtime/'teseo_validate.py'
            if not helper.is_file(): helper=runtime/'graph/teseo_validate.py'
            checked=subprocess.run([sys.executable,str(helper),str(workspace)],cwd=helper.parent,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,
                shell=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if checked.returncode!=0:
                raise ContractError('synthesis_invalid','Verifica deterministica delle sintesi fallita; nessun apply')
            candidate.assert_unchanged(workspace)
            result['checks']['synthesis']=True
            immutable={k:v for k,v in result.items() if k!='manifest_digest'}
            result['manifest_digest']=content_hash(immutable)
            record.update(validation=result)
            self._save(journal,record)
            prepared = journal.prepare(record['operation_id'],candidate)
            prepared['checkpoint'].update(validation=result, publication_eligible=False)
            self._save(journal,prepared)
        except Exception as error:
            record = journal.get(record['operation_id'])
            record.update(state='blocked_external_change' if getattr(error,'code','')=='blocked_external_change' else 'failed',
                          error={'code':getattr(error,'code','candidate_invalid'),'message':str(error)[:500] if isinstance(error,ContractError) else 'Validazione candidata fallita'})
            self._save(journal,record)

    @staticmethod
    def _get(journal, identifier):
        record = journal.get(identifier)
        if record['kind'] not in KINDS:
            raise ContractError('operation_missing','Ciclo skill non trovato')
        return record

    def action(self, vault_id, identifier, body, action):
        _fields(body, ('decision',) if action=='resume' else ())
        with self._mutex:
            with VaultLock(self.registry.root(vault_id)) as lock, Journal(lock) as journal:
                record = self._get(journal,identifier)
                if action=='cancel':
                    if record['state'] in FINAL:
                        return _public(record)
                    if record['state'] in ('applying','recovery_required'):
                        raise ContractError('recovery_required','Conservare output e risolvere recovery prima di cancellare')
                    record.update(state='cancelled',publication_eligible=False)
                    self.adapters[record['request']['adapter']].cancel(record)
                    self._save(journal,record)
                elif action=='resume':
                    if record['state']!='awaiting_user' or body['decision'] not in ('continue','refuse'):
                        raise ContractError('invalid_operation','Conferma una sospensione utente esistente')
                    if body['decision']=='refuse':
                        record.update(state='cancelled',publication_eligible=False)
                        self._save(journal,record)
                    else:
                        # Explicit continuation; fresh one-use token, old receipt retained for replay.
                        self._handoff(journal,record)
                self._advance(journal)
                return _public(journal.get(identifier))

    def dispatch(self, vault_id, body):
        _fields(body,())
        with self._mutex:
            with VaultLock(self.registry.root(vault_id)) as lock,Journal(lock) as journal:
                self._advance(journal)
        return {'state':'checked','content_revision':None,'graph_generation':None}

    def request_stop(self):
        self._stop=True

    def close(self):
        self.request_stop()

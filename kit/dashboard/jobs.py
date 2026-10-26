"""Rebuild derivati espliciti: journal persistente, lock comune, nessun apply note."""
import re
import sqlite3
import threading
from uuid import UUID

from .contracts import ContractError, parse_json, content_hash, check_path_budget
from .diagnostics import log_unexpected as _log_unexpected
from .storage import VaultLock, Journal, capture_snapshot, _no_link

TERMINAL = {"succeeded", "failed", "cancelled", "blocked_external_change", "recovery_required"}


def _public(record):
    return {key: record.get(key) for key in ("operation_id", "vault_id", "kind", "state", "error",
            "base_content_digest", "checkpoint", "phases", "phase", "handoff", "validation", "publication_eligible", "expires_at")} | {
                "content_revision": (record.get("checkpoint") or {}).get("content_revision"),
                "graph_generation": (record.get("checkpoint") or {}).get("graph_generation")}


class RebuildCoordinator:
    def __init__(self, registry):
        self.registry = registry
        self._mutex = threading.RLock()
        self._workers = {}  # one live job per vault, at most four vaults
        self._requests = {}
        self._stop = threading.Event()
        self.note_activity = lambda vault_id: None

    def activity(self, vault_id):
        with self._mutex:
            job = self._workers.get(vault_id)
            note = self.note_activity(vault_id)
            return {"busy": job is not None or note is not None, "busy_known": True, "busy_scope": "service",
                    "active_operation_id": job[0] if job else note}

    def submit(self, vault_id, body):
        self.registry.status(vault_id)
        if (set(body) != {"idempotency_key", "expected_content_revision"}
                or not isinstance(body["idempotency_key"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", body["idempotency_key"])):
            raise ContractError("invalid_operation", "Richiesti chiave idempotente e revisione attesa")
        expected = body["expected_content_revision"]
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected)):
            raise ContractError("invalid_operation", "Revisione attesa non valida")
        payload = {"expected_content_revision": expected}
        key = (vault_id, body["idempotency_key"])
        digest = content_hash(payload)
        with self._mutex:
            if self._stop.is_set():
                raise ContractError("service_stopping", "Il servizio si sta arrestando")
            if key in self._requests:
                identifier, previous = self._requests[key]
                if digest != previous:
                    raise ContractError("idempotency_conflict", "Chiave già usata con payload diverso")
                return self.get(vault_id, identifier)
            if vault_id in self._workers:
                raise ContractError("vault_busy", "Un rebuild del vault è già attivo")
            if len(self._workers) >= 4:
                raise ContractError("job_limit", "Quattro rebuild già attivi; riprovare al termine")
            root = self.registry.root(vault_id)
            check_path_budget(root)
            with VaultLock(root) as lock, Journal(lock) as journal:
                journal.assert_notes_idle()
                journal.recover_rebuilds()
                snapshot = capture_snapshot(root)
                record = journal.create("rebuild", payload, body["idempotency_key"], snapshot)
                identifier = record["operation_id"]
                self._requests[key] = (identifier, digest)
                if len(self._requests) > 256:
                    for cached_key, (cached_id, _) in self._requests.items():
                        active = self._workers.get(cached_key[0])
                        if not active or active[0] != cached_id:
                            del self._requests[cached_key]
                            break
                if record["state"] in TERMINAL:
                    return _public(record)
                if expected is not None and expected != snapshot.digest:
                    record = journal.transition(identifier, "blocked_external_change", error={
                        "code": "revision_changed", "message": "Contenuti cambiati dopo la richiesta; aggiornare la vista"})
                    return _public(record)
            worker = threading.Thread(target=self._run, args=(vault_id, identifier),
                                      name="teseo-rebuild", daemon=False)
            self._workers[vault_id] = (identifier, worker)
            try:
                worker.start()
            except BaseException:
                del self._workers[vault_id]
                raise
            return _public(record)

    def _run(self, vault_id, identifier):
        try:
            root = self.registry.root(vault_id)
            with VaultLock(root, timeout=5) as lock, Journal(lock) as journal:
                try:
                    if self._stop.is_set():
                        raise ContractError("operation_cancelled", "Servizio in arresto")
                    record = journal.get(identifier)
                    if record["state"] != "created":
                        return  # altro processo ha già risolto il record sotto lock
                    if capture_snapshot(root).digest != record["base_content_digest"]:
                        raise ContractError("blocked_external_change", "Contenuti cambiati prima del build")
                    journal.transition(identifier, "waiting_lock")
                    journal.transition(identifier, "running")
                    # Import solo nel worker, dal runtime fidato, mai dal vault registrato.
                    from .graph_service import rebuild
                    reference = rebuild(root, lock=lock, cancelled=self._stop,
                        validating=lambda: journal.transition(identifier, "validating"))
                    journal.complete_rebuild(identifier, reference)
                except Exception as error:
                    if not isinstance(error, ContractError) and not hasattr(error, "problemi"): _log_unexpected(error)
                    code = error.code if isinstance(error, ContractError) else "rebuild_failed"
                    message = str(error) if isinstance(error, ContractError) else "Rebuild fallito; generazione precedente conservata"
                    details = getattr(error, "problemi", [])
                    if details:
                        code, message = "graph_validation_failed", "Validazione del grafo fallita"
                    failure = {"code": code, "message": message,
                               "details": [str(item)[:500] for item in details[:20]]}
                    state = ("cancelled" if code == "operation_cancelled" else
                             "blocked_external_change" if code in ("blocked_external_change", "revision_changed") else "failed")
                    journal.transition(identifier, state, error=failure)
        except Exception as error:
            # Un lock/storage esterno può impedire il checkpoint; GET lo segnala
            # recovery_required, senza scrivere durante una lettura o fare replay.
            _log_unexpected(error)
        finally:
            with self._mutex:
                self._workers.pop(vault_id, None)

    def get(self, vault_id, identifier):
        try:
            if str(UUID(identifier)) != identifier:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ContractError("operation_missing", "Operazione non trovata") from None
        root = self.registry.operation_root(vault_id)
        for relative in (".teseo", ".teseo/local", ".teseo/local/operations.sqlite"):
            _no_link(root / relative)
        path = root / ".teseo/local/operations.sqlite"
        if not path.is_file():
            raise ContractError("operation_missing", "Operazione non trovata")
        try:
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
            try:
                row = db.execute("SELECT record FROM operations WHERE operation_id=?", (identifier,)).fetchone()
                if not row:
                    raise ContractError("operation_missing", "Operazione non trovata")
                record = parse_json(row[0])
            finally:
                db.close()
        except sqlite3.Error:
            raise ContractError("operation_unavailable", "Journal temporaneamente non leggibile") from None
        skill = record['kind'] in ('ingest_lint','lint','fill_gaps')
        if record["kind"] not in ("rebuild", "ontology_apply", 'ingest_lint','lint','fill_gaps') or record["vault_id"] != vault_id:
            raise ContractError("operation_missing", "Operazione non trovata")
        if skill:
            if record['state']=='recovery_required' and self.note_activity(vault_id)==identifier:
                record.update(state='running',error=None)
            if record['state'] in ('preparing','validating','applying') and self.note_activity(vault_id)!=identifier:
                record.update(state='recovery_required',error={'code':'interrupted','message':'Verificare output e snapshot; nessun replay automatico'})
            return _public(record)
        with self._mutex:
            active = self._workers.get(vault_id)
            note = self.note_activity(vault_id)
            if record['kind'] == 'ontology_apply' and record['state'] == 'recovery_required' and note == identifier:
                record.update(state='running', error=None)
            if record["state"] not in TERMINAL | {'rolled_back'} and (not active or active[0] != identifier) and note != identifier:
                record.update(state="recovery_required", error={"code": "interrupted",
                    "message": "Job non gestito da questa sessione; verificare eventuali altri servizi e la generazione"})
        return _public(record)

    def request_stop(self):
        with self._mutex:
            self._stop.set()

    def list(self, vault_id, parameters=None):
        if parameters:
            raise ContractError('invalid_query', 'Elenco operazioni senza parametri')
        root = self.registry.operation_root(vault_id)
        for relative in ('.teseo', '.teseo/local', '.teseo/local/operations.sqlite'):
            _no_link(root / relative)
        path = root / '.teseo/local/operations.sqlite'
        if not path.exists():
            return {'operations': [], 'truncated': False, 'content_revision': None, 'graph_generation': None}
        try:
            db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
            try:
                identifiers = [row[0] for row in db.execute('SELECT operation_id FROM operations ORDER BY rowid DESC LIMIT 51')]
            finally:
                db.close()
        except sqlite3.Error:
            raise ContractError('operation_unavailable', 'Journal non leggibile') from None
        try:
            digest = capture_snapshot(root, allow_missing_schema=True).digest
        except (ContractError, OSError):
            digest = None
        return {'operations': [self.get(vault_id, identifier) for identifier in identifiers[:50]],
                'truncated': len(identifiers) > 50, 'content_revision': None, 'graph_generation': None,
                'live_content_revision': digest}

    def close(self):
        self.request_stop()
        with self._mutex:
            workers = [job[1] for job in self._workers.values()]
        for worker in workers:
            worker.join()

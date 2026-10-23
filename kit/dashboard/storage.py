"""Storage locale del coordinator futuro, senza apply delle note.

I lock coordinano solo i chiamanti cooperanti. Snapshot e precondizioni hash
non escludono editor esterni e non autorizzano apply automatici.
"""
from contextlib import AbstractContextManager
from dataclasses import dataclass
import errno
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from .contracts import (
    ContractError, DEFAULT_SHARED_PATHS, PathKind, canonical_json, classify_path,
    content_hash, inspect_vault, parse_json, resolve_path, validate_paths,
    parse_manifest,
)


def _compatible_root(root, allow_missing_schema=False):
    root = Path(root).resolve(strict=True)
    compatibility = inspect_vault(root)
    if compatibility.mode != "compatible":
        if allow_missing_schema and not (root / 'Wiki reference.md').exists() and (root / 'wiki').is_dir():
            for relative in ('.teseo', '.teseo/project.json', 'wiki', 'Wiki reference.md'):
                _no_link(root / relative)
                resolve_path(root, relative)
            with (root / '.teseo/project.json').open('rb') as stream:
                data = stream.read(65537)
            if len(data) <= 65536:
                return root, parse_manifest(data)['vault_id']
        raise ContractError("vault_readonly", "Richiesto manifest compatibile; nessuna adozione implicita")
    return root, compatibility.manifest["vault_id"]


def _no_link(path):
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ContractError("linked_path", "Symlink e junction non ammessi nello storage", path.name)


def _local_directory(root):
    for relative in (".teseo", ".teseo/local"):
        _no_link(root / relative)
        resolve_path(root, relative).mkdir(exist_ok=True)
    local = root / ".teseo/local"
    return local


def _ensure_ignored(local):
    ignore = local / ".gitignore"
    _no_link(ignore)
    if not ignore.exists():
        with ignore.open("xb") as stream:
            stream.write(b"*\n")
    elif [line.strip() for line in ignore.read_text(encoding="utf-8").splitlines()
          if line.strip() and not line.lstrip().startswith("#")] != ["*"]:
        raise ContractError("local_not_ignored", "Lo storage locale richiede .gitignore con regola *")


class VaultLock(AbstractContextManager):
    """Lock kernel su un file persistente: non rimuovere lock in base al PID.

    Timeout produce vault_busy; il chiamante può mantenere il job in coda e
    ritentare. La chiusura/crash del processo libera il lock del kernel.
    """

    def __init__(self, root, timeout=0, *, recovery=False):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout deve essere finito e non negativo")
        self.recovery = recovery
        self.root, self.vault_id = _compatible_root(root, recovery)
        self.timeout, self._stream = timeout, None

    @property
    def held(self):
        return self._stream is not None

    def __enter__(self):
        if self.held:
            raise ContractError("lock_reentry", "Lock già acquisito")
        if _compatible_root(self.root, self.recovery)[1] != self.vault_id:
            raise ContractError("vault_changed", "Identità vault cambiata prima del lock")
        local = _local_directory(self.root)
        path = local / "vault.lock"
        _no_link(path)
        stream = path.open("a+b")
        try:
            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise ContractError("vault_busy", "Vault occupato da un altro scrittore") from error
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            _ensure_ignored(local)
            self._stream = stream
            return self
        except BaseException:
            stream.close()
            raise

    def __exit__(self, *exc):
        if self._stream is not None:
            # close rilascia anche il lock kernel; il file non viene cancellato.
            self._stream.close()
            self._stream = None


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    data: bytes

    @property
    def digest(self):
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class Snapshot:
    files: tuple[SnapshotFile, ...]

    def __post_init__(self):
        object.__setattr__(self, "files", tuple(self.files))
        paths = [entry.path for entry in self.files]
        validate_paths(paths)
        if len(paths) != len(set(paths)):
            raise ContractError("duplicate_path", "Snapshot con percorsi duplicati")
        for entry in self.files:
            if not isinstance(entry.data, bytes) or classify_path(entry.path) not in (
                    PathKind.MANIFEST, PathKind.MARKDOWN, PathKind.RAW, PathKind.EVENT):
                raise ContractError("invalid_snapshot", "Snapshot contiene file non dati", entry.path)

    @property
    def hashes(self):
        return {entry.path: entry.digest for entry in self.files}

    @property
    def digest(self):
        return content_hash(self.hashes)

    @property
    def schema_digest(self):
        return self.hashes.get("Wiki reference.md")

    def assert_unchanged(self, root):
        current = capture_snapshot(root)
        if current.digest != self.digest:
            raise ContractError("blocked_external_change", "Contenuti cambiati dopo lo snapshot")


def _scan(root, max_bytes):
    entries, seen, total = [], [], 0

    def visit(path, relative):
        nonlocal total
        if not path.exists() and not path.is_symlink():
            return
        _no_link(path)
        resolve_path(root, relative)
        seen.append(relative)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                visit(child, f"{relative}/{child.name}")
        elif path.is_file():
            if classify_path(relative) not in (PathKind.MANIFEST, PathKind.MARKDOWN, PathKind.RAW, PathKind.EVENT):
                raise ContractError("unexpected_data_path", "File non dati nel perimetro dello snapshot", relative)
            remaining = max_bytes - total
            with path.open("rb") as stream:
                data = stream.read(remaining + 1)
            total += len(data)
            if total > max_bytes:
                raise ContractError("snapshot_too_large", "Superato il limite byte dello snapshot")
            entries.append(SnapshotFile(relative, data))
        else:
            raise ContractError("unsupported_file", "Tipo file non supportato", relative)

    # Censire tutto il perimetro dati, non solo file già esistenti o selezionati
    # per export: nuove note e raw esclusi dalla condivisione restano protetti.
    for relative in (*DEFAULT_SHARED_PATHS, ".teseo/project.json"):
        relative = relative.rstrip("/")
        visit(root / relative, relative)
    validate_paths(seen)
    return Snapshot(tuple(sorted(entries, key=lambda entry: entry.path)))


def capture_snapshot(root, max_bytes=64 * 1024 * 1024, *, allow_missing_schema=False):
    """Due scansioni di confronto, limite esplicito; nessuna garanzia anti-race.

    Byte della prima scansione conservati in memoria e successivamente copiabili
    per il build. Una mutazione rilevata durante la lettura invalida il risultato.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes deve essere un intero positivo")
    root, _ = _compatible_root(root, allow_missing_schema)
    try:
        snapshot = _scan(root, max_bytes)
        if snapshot.digest != _scan(root, max_bytes).digest:
            raise ContractError("blocked_external_change", "Modifica durante la cattura dello snapshot")
        _compatible_root(root, allow_missing_schema)
        return snapshot
    except OSError as error:
        raise ContractError("snapshot_unreadable", "File cambiato o non accessibile durante lo snapshot") from error


def validate_raw_unchanged(base, candidate):
    """Nuove fonti ammesse; eliminazione, modifica e rename di raw vietati."""
    after = candidate.hashes
    for path, digest in base.hashes.items():
        if path.startswith("raw/") and after.get(path) != digest:
            raise ContractError("immutable_raw_changed", "Fonte raw preesistente alterata o rimossa", path)


_NEXT = {
    "created": {"waiting_lock"}, "waiting_lock": {"running"},
    "running": {"validating"}, "validating": {"prepared"},
    "prepared": {"applying"}, "applying": {"succeeded"},
}
_EXITS = {"failed", "cancelled", "blocked_external_change", "recovery_required"}


class Journal(AbstractContextManager):
    """Record SQLite transazionali e copie prima dell'operazione.

    Richiede lock per ogni accesso. Non applica note, non completa recovery e non
    autorizza applying delle note. Solo complete_rebuild può completare un job
    derivato; succeeded delle operazioni note resta riservato all'apply protetto.
    """

    def __init__(self, lock):
        self.lock = lock
        self._require_lock()
        self.local = _local_directory(lock.root)
        path = self.local / "operations.sqlite"
        _no_link(path)
        self.db = sqlite3.connect(path)
        try:
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("CREATE TABLE IF NOT EXISTS operations ("
                            "operation_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, "
                            "request_digest TEXT NOT NULL, record BLOB NOT NULL)")
            self.db.commit()
        except BaseException:
            self.db.close()
            raise

    def _require_lock(self):
        if not self.lock.held:
            raise ContractError("lock_required", "Acquisire il lock vault prima del journal")

    def __exit__(self, *exc):
        self.db.close()

    def get(self, operation_id):
        self._require_lock()
        row = self.db.execute("SELECT record FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise ContractError("operation_missing", "Operazione non trovata")
        return parse_json(row[0])

    def create(self, kind, payload, idempotency_key, snapshot, base_git_revision=None):
        self._require_lock()
        if not kind or not isinstance(kind, str) or not isinstance(idempotency_key, str) or not idempotency_key:
            raise ContractError("invalid_operation", "Richiesti kind e chiave idempotente")
        request = content_hash({"kind": kind, "payload": payload})
        row = self.db.execute("SELECT operation_id, request_digest FROM operations WHERE idempotency_key=?",
                              (idempotency_key,)).fetchone()
        if row:
            if row[1] != request:
                raise ContractError("idempotency_conflict", "Chiave già usata con payload diverso")
            return self.get(row[0])
        # Non attribuire un vecchio snapshot a una nuova operazione.
        snapshot.assert_unchanged(self.lock.root)
        operation_id = str(uuid4())
        relative = f".teseo/local/snapshots/{operation_id}/base"
        self._persist_snapshot(relative, snapshot)
        record = {"operation_id": operation_id, "vault_id": self.lock.vault_id, "kind": kind,
                  "base_git_revision": base_git_revision, "base_content_digest": snapshot.digest,
                  "schema_digest": snapshot.schema_digest, "reads": sorted(snapshot.hashes),
                  "before": snapshot.hashes, "after": {}, "state": "created", "error": None,
                  "checkpoint": None, "snapshot_path": relative}
        with self.db:
            self.db.execute("INSERT INTO operations VALUES (?,?,?,?)",
                            (operation_id, idempotency_key, request, canonical_json(record)))
        return record

    def find_request(self, kind, payload, key):
        self._require_lock()
        row = self.db.execute('SELECT operation_id,request_digest FROM operations WHERE idempotency_key=?', (key,)).fetchone()
        if not row:
            return None
        if row[1] != content_hash({'kind': kind, 'payload': payload}):
            raise ContractError('idempotency_conflict', 'Chiave già usata con payload diverso')
        return self.get(row[0])

    def assert_notes_idle(self, allowed=None):
        self._require_lock()
        for (identifier,) in self.db.execute('SELECT operation_id FROM operations').fetchall():
            record = self.get(identifier)
            if (identifier != allowed and record['kind'] == 'ontology_apply'
                    and record['state'] not in ('succeeded', 'rolled_back', 'failed', 'blocked_external_change', 'cancelled')):
                raise ContractError('recovery_required', 'Operazione note da completare o ripristinare prima di altre scritture')

    def save_ontology(self, record):
        """Solo il coordinator specifico può avanzare il protocollo note."""
        self._require_lock()
        if record['kind'] != 'ontology_apply' or self.get(record['operation_id'])['kind'] != 'ontology_apply':
            raise ContractError('invalid_transition', 'Richiesta operazione ontologia')
        self._save(record)

    def _persist_snapshot(self, relative, snapshot):
        destination = resolve_path(self.lock.root, relative)
        parent = self.lock.root
        for component in Path(relative).parts:
            parent = parent / component
            _no_link(parent)
            parent.mkdir(exist_ok=True)
        (destination / "wiki").mkdir(exist_ok=True)
        for entry in snapshot.files:
            target = destination / entry.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(entry.data)
                stream.flush()
                os.fsync(stream.fileno())

    def _save(self, record):
        with self.db:
            self.db.execute("UPDATE operations SET record=? WHERE operation_id=?",
                            (canonical_json(record), record["operation_id"]))

    def prepare(self, operation_id, candidate):
        """Persisti candidato e checkpoint solo se base live e raw sono invariati."""
        self._require_lock()
        record = self.get(operation_id)
        if record["state"] != "validating":
            raise ContractError("invalid_transition", "Preparazione richiede stato validating")
        manifest = next((entry.data for entry in candidate.files if entry.path == ".teseo/project.json"), b"{}")
        if parse_manifest(manifest)["vault_id"] != self.lock.vault_id:
            raise ContractError("vault_mismatch", "Candidato di un altro vault")
        if "Wiki reference.md" not in candidate.hashes:
            raise ContractError("invalid_snapshot", "Schema mancante nel candidato")
        base = capture_snapshot(resolve_path(self.lock.root, record["snapshot_path"]))
        if base.digest != record["base_content_digest"]:
            raise ContractError("snapshot_corrupt", "Copia base non corrisponde al journal")
        try:
            base.assert_unchanged(self.lock.root)
        except ContractError as error:
            self.transition(operation_id, "blocked_external_change", error=error.as_dict())
            raise
        validate_raw_unchanged(base, candidate)
        checkpoint_id = str(uuid4())
        relative = f".teseo/local/snapshots/{operation_id}/candidates/{checkpoint_id}"
        self._persist_snapshot(relative, candidate)
        try:
            base.assert_unchanged(self.lock.root)
        except ContractError as error:
            self.transition(operation_id, "blocked_external_change", error=error.as_dict())
            raise
        record.update(state="prepared", after=candidate.hashes,
                      checkpoint={"checkpoint_id": checkpoint_id, "candidate_path": relative,
                                  "candidate_digest": candidate.digest})
        self._save(record)
        return record

    def transition(self, operation_id, state, error=None):
        self._require_lock()
        record = self.get(operation_id)
        if state in ("applying", "succeeded"):
            raise ContractError("apply_unavailable", "Apply protetto non ancora implementato")
        if state == "prepared":
            raise ContractError("prepare_required", "Usare prepare per verificare base e raw")
        if state == record["state"]:
            return record
        allowed = _NEXT.get(record["state"], set())
        if state not in allowed and not (record["state"] in _NEXT and state in _EXITS):
            raise ContractError("invalid_transition", "Transizione operazione non consentita")
        record.update(state=state, error=error)
        self._save(record)
        return record

    def complete_rebuild(self, operation_id, reference):
        """Checkpoint derivato: non abilita apply/succeeded per operazioni note."""
        self._require_lock()
        record = self.get(operation_id)
        if (record["kind"] != "rebuild" or record["state"] not in ("running", "validating")
                or record["base_content_digest"] != reference.content_revision or not reference.generation):
            raise ContractError("invalid_transition", "Checkpoint rebuild non corrispondente")
        record.update(state="succeeded", error=None,
                      checkpoint={"content_revision": reference.content_revision,
                                  "graph_generation": reference.generation})
        self._save(record)
        return record

    def recover_rebuilds(self):
        """Chiamare senza worker attivi e sotto lock; nessun replay automatico."""
        self._require_lock()
        for (operation_id,) in self.db.execute("SELECT operation_id FROM operations").fetchall():
            record = self.get(operation_id)
            if record["kind"] == "rebuild" and record["state"] in _NEXT:
                self.transition(operation_id, "recovery_required", error={"code": "interrupted",
                    "message": "Rebuild interrotto; verificare la generazione e avviare un nuovo job"})

    def require_recovery(self):
        """Segnala operazioni interrotte, senza cancellare lock, snapshot o note."""
        self._require_lock()
        rows = self.db.execute("SELECT operation_id FROM operations").fetchall()
        pending = []
        for (operation_id,) in rows:
            record = self.get(operation_id)
            if record["state"] in _NEXT:
                record = self.transition(operation_id, "recovery_required",
                                         error={"code": "interrupted", "message": "Verificare snapshot e precondizioni"})
                pending.append(record)
            elif record["state"] == "recovery_required":
                pending.append(record)
        return pending

    def orphan_snapshots(self):
        """Copie senza checkpoint dopo interruzioni: segnalarle, mai cancellarle."""
        self._require_lock()
        directory = self.local / "snapshots"
        _no_link(directory)
        if not directory.exists():
            return []
        records = {row[0]: self.get(row[0]) for row in
                   self.db.execute("SELECT operation_id FROM operations").fetchall()}
        orphans = []
        for operation in sorted(directory.iterdir()):
            _no_link(operation)
            if operation.name not in records:
                orphans.append(operation.relative_to(self.lock.root).as_posix())
                continue
            record = records[operation.name]
            candidates = operation / "candidates"
            _no_link(candidates)
            if candidates.exists():
                checkpoint = record["checkpoint"] or {}
                for candidate in sorted(candidates.iterdir()):
                    _no_link(candidate)
                    relative = candidate.relative_to(self.lock.root).as_posix()
                    if relative != checkpoint.get("candidate_path"):
                        orphans.append(relative)
        return orphans

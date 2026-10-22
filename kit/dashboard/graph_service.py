"""Generazioni derivate: il solo manifest corrente viene sostituito atomicamente."""
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from uuid import uuid4

from .contracts import ContractError, canonical_json, content_hash, resolve_path, file_hash
from .storage import VaultLock, capture_snapshot, _no_link

try:  # sorgenti del kit / pacchetto installato in .graph/dashboard
    from ..graph import build_graph
    from ..graph.graph_db import graph_reference
except ImportError:
    import build_graph
    from graph_db import graph_reference

BUILDER_VERSION = 2


def _atomic_marker(path, record):
    fd, name = tempfile.mkstemp(prefix=".graph-current-", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical_json(record))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _check_database(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ContractError("invalid_graph", "Integrità SQLite fallita")
    finally:
        db.close()


def rebuild(root):
    """Build da copia dei byte, lock comune e controllo contenuti prima del marker.

    Non modifica note e non applica operazioni del journal. Un crash prima del
    marker lascia la vecchia generazione; quella non referenziata è riutilizzabile.
    """
    with VaultLock(root, timeout=5) as lock:
        root = lock.root
        snapshot = capture_snapshot(root)
        if any(entry.path.startswith(".teseo/shared/events/") for entry in snapshot.files):
            raise ContractError("event_validation_unavailable", "Validazione eventi non ancora disponibile")
        generation = content_hash({"content_revision": snapshot.digest, "builder_version": BUILDER_VERSION})
        legacy = root / ".graph/graph.sqlite"
        current = graph_reference(legacy)
        if current.generation == generation:
            _check_database(current.path)
            if file_hash(current.path) != current.sqlite_sha256:
                raise ContractError("graph_corrupt", "Hash generazione corrente non valido")
            return current
        local = root / ".teseo/local"
        graphs = resolve_path(root, ".teseo/local/graphs")
        _no_link(root / ".teseo/local/graphs")
        graphs.mkdir(exist_ok=True)
        destination = graphs / f"{generation}.sqlite"
        _no_link(destination)
        # Ricostruire anche gli orfani: non fidarsi dei soli metadati locali.
        with tempfile.TemporaryDirectory(prefix="build-", dir=local) as temporary:
            copy = Path(temporary)
            (copy / "wiki").mkdir()
            for entry in snapshot.files:
                target = copy / entry.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(entry.data)
            parsed = build_graph.parse_snapshot(copy)
            candidate = build_graph.build_candidate(parsed, destination)
            try:
                db = sqlite3.connect(candidate)
                try:
                    db.execute("CREATE TABLE graph_metadata (key TEXT PRIMARY KEY, value TEXT)")
                    db.executemany("INSERT INTO graph_metadata VALUES (?,?)",
                                   [("content_revision", snapshot.digest), ("generation", generation),
                                    ("builder_version", str(BUILDER_VERSION))])
                    db.execute("CREATE TABLE graph_documents (path TEXT PRIMARY KEY, content TEXT NOT NULL)")
                    documents = [(entry.path, entry.data.decode("utf-8")) for entry in snapshot.files
                                 if entry.path in ("Wiki reference.md", "index.md", "log.md")
                                 or (entry.path.startswith("wiki/") and entry.path.count("/") == 1
                                     and entry.path.endswith(".md"))]
                    db.executemany("INSERT INTO graph_documents VALUES (?,?)", documents)
                    db.commit()
                finally:
                    db.close()
                _check_database(candidate)
                with candidate.open("r+b") as stream:
                    os.fsync(stream.fileno())
                if destination.exists():
                    if file_hash(candidate) != file_hash(destination):
                        raise ContractError("graph_corrupt", "Generazione orfana diversa dalla ricostruzione")
                else:
                    os.replace(candidate, destination)
            finally:
                candidate.unlink(missing_ok=True)
        _check_database(destination)
        db = sqlite3.connect(destination.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            metadata = dict(db.execute("SELECT key, value FROM graph_metadata"))
            if metadata != {"content_revision": snapshot.digest, "generation": generation,
                            "builder_version": str(BUILDER_VERSION)}:
                raise ContractError("graph_corrupt", "Metadati generazione non corrispondenti")
        finally:
            db.close()
        snapshot.assert_unchanged(root)
        marker = local / "graph-current.json"
        _no_link(marker)
        _atomic_marker(marker, {"format_version": 1, "content_revision": snapshot.digest,
                                "generation": generation, "sqlite_sha256": file_hash(destination)})
        return graph_reference(legacy)


def backup_personal_databases(root, timeout=30):
    """SQLite online backup: include dati WAL committati, mai semplice copia file.

    Una directory senza backup.json è incompleta; resta disponibile per diagnosi.
    Nessun restore automatico e nessuna cancellazione dei DB sorgenti.
    """
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
        raise ValueError("timeout backup atteso fra 0 e 300 secondi")
    with VaultLock(root, timeout=5) as lock:
        directory = resolve_path(lock.root, ".teseo/local/backups")
        _no_link(lock.root / ".teseo/local/backups")
        directory.mkdir(exist_ok=True)
        backup = directory / str(uuid4())
        backup.mkdir()
        results = {}
        for name in ("memoria.sqlite", "domande.sqlite"):
            source_path = resolve_path(lock.root, ".graph/" + name)
            _no_link(lock.root / ".graph")
            _no_link(lock.root / ".graph" / name)
            if not source_path.exists():
                continue
            deadline = time.monotonic() + timeout
            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise ContractError("backup_timeout", "Backup SQLite oltre il timeout")
            source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
            target = None
            try:
                target = sqlite3.connect(backup / name)
                source.backup(target, pages=128, progress=progress, sleep=0.01)
            finally:
                if target is not None:
                    target.close()
                source.close()
            _check_database(backup / name)
            with (backup / name).open("r+b") as stream:
                os.fsync(stream.fileno())
            results[name] = {"sha256": file_hash(backup / name)}
        _atomic_marker(backup / "backup.json", {"format_version": 1, "vault_id": lock.vault_id,
                                               "databases": results})
        return backup

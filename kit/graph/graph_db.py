"""Apertura readonly e revisione fissata per connessione, anche nel kit installato."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3


class GraphDatabaseError(sqlite3.DatabaseError):
    pass


@dataclass(frozen=True)
class GraphReference:
    path: Path
    content_revision: str | None = None
    generation: str | None = None
    sqlite_sha256: str | None = None


def graph_reference(path):
    path = Path(path)
    if path.name != "graph.sqlite" or path.parent.name != ".graph":
        return GraphReference(path)
    root = path.parent.parent.resolve()
    marker = root / ".teseo/local/graph-current.json"
    if not marker.exists():
        return GraphReference(path)
    try:
        if not marker.resolve().is_relative_to(root):
            raise ValueError("manifest fuori root")
        if marker.stat().st_size > 4096:
            raise ValueError("manifest oltre limite")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("chiave duplicata")
                result[key] = value
            return result
        record = json.loads(marker.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if type(record["format_version"]) is not int or record["format_version"] != 1:
            raise ValueError("versione non supportata")
        for key in ("generation", "content_revision", "sqlite_sha256"):
            if not isinstance(record[key], str) or not re.fullmatch("[0-9a-f]{64}", record[key]):
                raise ValueError("digest non valido")
        target = root / ".teseo/local/graphs" / (record["generation"] + ".sqlite")
        if not target.resolve().is_relative_to(root) or not target.is_file():
            raise ValueError("generazione assente o fuori root")
        return GraphReference(target, record["content_revision"], record["generation"], record["sqlite_sha256"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise GraphDatabaseError("Manifest generazione non valido; ultima vista non sostituita") from error


def resolve_graph(path):
    return graph_reference(path).path


class GraphConnection(sqlite3.Connection):
    """Attributi content_revision e graph_generation fissati all'apertura."""


def connect_graph(path):
    reference = graph_reference(path)
    uri = reference.path.resolve().as_uri() + "?mode=ro"
    if reference.generation:
        uri += "&immutable=1"
    db = sqlite3.connect(uri, uri=True, factory=GraphConnection)
    try:
        if reference.generation:
            metadata = dict(db.execute("SELECT key, value FROM graph_metadata"))
            if (metadata.get("content_revision") != reference.content_revision
                    or metadata.get("generation") != reference.generation):
                raise GraphDatabaseError("Generazione diversa dal manifest")
        db.content_revision = reference.content_revision
        db.graph_generation = reference.generation
        db.graph_path = reference.path
        return db
    except BaseException:
        db.close()
        raise

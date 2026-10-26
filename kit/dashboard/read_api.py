"""Consultazione di una generazione immutabile; nessuna GET costruisce o scrive dati."""
import base64
from contextlib import contextmanager
import hmac
import html
import json
import re
import secrets
import sqlite3
import time

from .contracts import ContractError, canonical_json, parse_json, portable_path, file_hash
from .storage import capture_snapshot, _no_link

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def _parser():
    # Modulo del runtime del servizio, mai caricato dal percorso del vault collegato.
    try:
        from ..graph import build_graph
    except ImportError:
        import build_graph
    return build_graph


def _revision(reference):
    return {"content_revision": reference.content_revision, "graph_generation": reference.generation}


def _issue(code, severity, message, revision, path=None):
    return {"code": code, "severity": severity, "message": message, "path": path, "revision": revision}


class ReadAPI:
    def __init__(self, registry, operations=None):
        self.registry = registry
        self.operations = operations
        self._cursor_key = secrets.token_bytes(32)

    @staticmethod
    def _parameters(parameters, allowed):
        if set(parameters) - set(allowed):
            raise ContractError("invalid_query", "Parametri di consultazione non supportati")
        generation = parameters.get("generation")
        if generation is not None and not re.fullmatch("[0-9a-f]{64}", generation):
            raise ContractError("invalid_query", "Generazione non valida")

    @contextmanager
    def _open(self, root, generation=None):
        db = None
        try:
            for relative in (".teseo", ".teseo/local", ".teseo/local/graphs"):
                _no_link(root / relative)
            if not (root / ".teseo/local/graph-current.json").exists():
                raise ContractError("graph_unavailable", "Grafo versionato non disponibile; nessun rebuild automatico")
            try:
                from ..graph.graph_db import graph_reference, connect_graph
            except ImportError:
                from graph_db import graph_reference, connect_graph
            reference = graph_reference(root / ".graph/graph.sqlite")
            if not reference.generation:
                raise ContractError("graph_unavailable", "Grafo versionato non disponibile; nessun rebuild automatico")
            if generation is not None and generation != reference.generation:
                raise ContractError("revision_changed", "La generazione è cambiata; riavviare la lettura")
            _no_link(reference.path)
            if reference.path.stat().st_size > 512 * 1024 * 1024:
                raise ContractError("graph_too_large", "Grafo oltre il limite di consultazione iniziale")
            if file_hash(reference.path) != reference.sqlite_sha256:
                raise ContractError("graph_corrupt", "Hash del grafo non valido")
            db = connect_graph(reference.path, reference=reference)
            metadata = dict(db.execute("SELECT key, value FROM graph_metadata"))
            if metadata.get("builder_version") not in {"2", "3"}:
                raise ContractError("graph_upgrade_required", "Ricostruire esplicitamente il grafo con il kit aggiornato")
            deadline = time.monotonic() + 5
            db.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
            yield db, reference
        except (OSError, sqlite3.Error) as error:
            raise ContractError("graph_unreadable", "Generazione non leggibile o query oltre il tempo limite") from error
        finally:
            if db is not None:
                db.close()

    def status(self, vault_id, parameters=None):
        parameters = parameters or {}
        self._parameters(parameters, {"generation"})
        root = self.registry.root(vault_id)
        result = self.registry.status(vault_id)
        result.update(live_content_revision=None, stale=None, busy=None, busy_known=False)
        if self.operations is not None:
            result.update(self.operations.activity(vault_id))
            result["capabilities"]["rebuild"] = result["compatibility"] == "compatible"
        try:
            live = capture_snapshot(root)
            result["live_content_revision"] = live.digest
        except (ContractError, OSError):
            result["issues"].append(_issue("live_revision_unavailable", "warning",
                                           "Revisione corrente non verificabile", None))
        try:
            with self._open(root, parameters.get("generation")) as (db, reference):
                result.update(_revision(reference))
                result['validation_version'] = int(dict(db.execute('SELECT key,value FROM graph_metadata'))['builder_version'])
                if result['validation_version'] == 2:
                    result['issues'].append(_issue('graph_validation_upgrade', 'warning',
                        'Grafo precedente alla validazione del catalogo tipi: rebuild esplicito consigliato', reference.content_revision))
                result["capabilities"]["graph"] = True
                result["stale"] = (result["live_content_revision"] != reference.content_revision
                                   if result["live_content_revision"] else None)
                if result["stale"]:
                    result["issues"].append(_issue("graph_stale", "warning",
                        "Il vault è cambiato; le API mostrano l'ultima generazione pubblicata", reference.content_revision))
        except ContractError as error:
            if error.code == "revision_changed":
                raise
            result["issues"].append(_issue(error.code, "warning", str(error), None))
        return result

    def _encode_cursor(self, value):
        data = canonical_json(value)
        signature = hmac.digest(self._cursor_key, data, "sha256")
        return base64.urlsafe_b64encode(data + signature).decode("ascii").rstrip("=")

    def _decode_cursor(self, token):
        try:
            if not token or len(token) > 4096 or not token.isascii():
                raise ValueError
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            data, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self._cursor_key, data, "sha256")):
                raise ValueError
            return parse_json(data)
        except (ValueError, ContractError):
            raise ContractError("invalid_cursor", "Cursore non valido per questa sessione") from None

    def graph(self, vault_id, parameters):
        self._parameters(parameters, {"generation", "limit", "type", "relation", "cursor"})
        limit = parameters.get("limit", "100")
        if not limit.isascii() or not limit.isdecimal() or len(limit) > 3 or not 1 <= int(limit) <= 200:
            raise ContractError("invalid_query", "limit atteso fra 1 e 200")
        limit = int(limit)
        filters = {key: parameters.get(key) for key in ("type", "relation")}
        if any(value is not None and (not value or len(value) > 128) for value in filters.values()):
            raise ContractError("invalid_query", "Filtro vuoto o oltre 128 caratteri")
        cursor = self._decode_cursor(parameters["cursor"]) if "cursor" in parameters else None
        if cursor and (cursor.get("vault_id") != vault_id or cursor.get("filters") != filters or cursor.get("limit") != limit):
            raise ContractError("invalid_cursor", "Cursore usato con vault o filtri diversi")
        generation = parameters.get("generation") or (cursor.get("generation") if cursor else None)
        if cursor and parameters.get("generation") and parameters["generation"] != cursor["generation"]:
            raise ContractError("invalid_cursor", "Cursore e generazione non corrispondenti")
        root = self.registry.root(vault_id)
        with self._open(root, generation) as (db, reference):
            node_where, node_args = [], []
            if filters["type"]:
                node_where.append("tipo = ?")
                node_args.append(filters["type"])
            if cursor and cursor["nodes_after"] is not None:
                node_where.append("id > ?")
                node_args.append(cursor["nodes_after"])
            where = " WHERE " + " AND ".join(node_where) if node_where else ""
            db.row_factory = sqlite3.Row
            nodes = [dict(row) for row in db.execute(
                "SELECT id,tipo,descrizione,path,tags,aggiornato FROM entities" + where + " ORDER BY id LIMIT ?",
                (*node_args, limit + 1))]
            edge_where, edge_args = [], []
            if filters["relation"]:
                edge_where.append("type = ?")
                edge_args.append(filters["relation"])
            if filters["type"]:
                edge_where.append("source_id IN (SELECT id FROM entities WHERE tipo=?) AND "
                                  "target_id IN (SELECT id FROM entities WHERE tipo=?)")
                edge_args.extend([filters["type"], filters["type"]])
            if cursor and cursor["edges_after"] is not None:
                edge_where.append("(source_id,target_id,type) > (?,?,?)")
                edge_args.extend(cursor["edges_after"])
            where = " WHERE " + " AND ".join(edge_where) if edge_where else ""
            edges = [dict(row) for row in db.execute(
                "SELECT source_id,target_id,type FROM relations" + where + " ORDER BY source_id,target_id,type LIMIT ?",
                (*edge_args, limit + 1))]
            more = len(nodes) > limit or len(edges) > limit
            nodes, edges = nodes[:limit], edges[:limit]
            after_node = nodes[-1]["id"] if nodes else (cursor["nodes_after"] if cursor else None)
            after_edge = ([edges[-1][key] for key in ("source_id", "target_id", "type")] if edges
                          else (cursor["edges_after"] if cursor else None))
            next_cursor = self._encode_cursor({"vault_id": vault_id, "generation": reference.generation,
                "filters": filters, "limit": limit, "nodes_after": after_node, "edges_after": after_edge}) if more else None
            return {**_revision(reference), "nodes": nodes, "edges": edges, "next_cursor": next_cursor,
                    "direction": "source_to_target"}

    @staticmethod
    def _document(db, path):
        row = db.execute("SELECT length(CAST(content AS BLOB)) FROM graph_documents WHERE path=?", (path,)).fetchone()
        if row is None:
            raise ContractError("document_unavailable", "Documento assente dalla generazione")
        if row[0] > MAX_DOCUMENT_BYTES:
            raise ContractError("document_too_large", "Documento oltre 2 MiB; usare gli strumenti locali")
        return db.execute("SELECT content FROM graph_documents WHERE path=?", (path,)).fetchone()[0]

    def node(self, vault_id, node_id, parameters):
        self._parameters(parameters, {"generation"})
        if not node_id or "/" in node_id or "\\" in node_id or node_id in (".", "..") or len(node_id) > 255:
            raise ContractError("invalid_node", "ID nodo non valido")
        portable_path("wiki/" + node_id + ".md")
        with self._open(self.registry.root(vault_id), parameters.get("generation")) as (db, reference):
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM entities WHERE id=?", (node_id,)).fetchone()
            if row is None:
                raise ContractError("node_missing", "Nodo non presente nella generazione")
            node = dict(row)
            properties, text = {}, None
            if node["path"]:
                source = self._document(db, node["path"])
                try:
                    properties, text = _parser().leggi_testo(source, node_id)
                    properties = json.loads(json.dumps(properties, default=str, allow_nan=False))
                except (ValueError, TypeError, RecursionError) as error:
                    raise ContractError("invalid_node_data", "Frontmatter non rappresentabile in JSON") from error
            relations = [dict(row) for row in db.execute("SELECT source_id,target_id,type FROM relations "
                "WHERE source_id=? OR target_id=? ORDER BY source_id,target_id,type LIMIT 201", (node_id, node_id))]
            aliases = [row[0] for row in db.execute("SELECT alias FROM aliases WHERE entity_id=? ORDER BY alias LIMIT 201", (node_id,))]
            sources = [row[0] for row in db.execute("SELECT target_id FROM relations WHERE source_id=? "
                "AND type='documentato_in' ORDER BY target_id LIMIT 201", (node_id,))]
            return {**_revision(reference), "node": node, "properties": properties,
                    "text": html.escape(text, quote=False) if text is not None else None,
                    "text_format": "escaped_markdown", "relations": relations[:200],
                    "aliases": aliases[:200], "sources": sources[:200],
                    "relations_truncated": len(relations) > 200, "aliases_truncated": len(aliases) > 200,
                    "sources_truncated": len(sources) > 200}

    @staticmethod
    def _ontology(db, reference):
        source = ReadAPI._document(db, "Wiki reference.md")
        document = _parser().parse_ontology(source)
        relations = [{"name": item.name, "from_types": list(item.from_types), "to_types": list(item.to_types),
                      "direction": item.direction, "meaning": item.meaning, "example": item.example}
                     for item in sorted(document.relations, key=lambda item: item.name)]
        if document.types is not None:
            types = [item.name for item in document.types]
        else:
            types = {row[0] for row in db.execute("SELECT DISTINCT tipo FROM entities WHERE tipo IS NOT NULL")}
            for item in relations:
                types.update(item["from_types"] + item["to_types"])
            types = sorted(types - {"qualsiasi", "stesso tipo"})
        opaque = [html.escape(document.source[span.start:span.end].decode('utf-8'), quote=False)
                  for span in document.opaque_sections]
        return {**_revision(reference), "types": types, "types_source": "declared" if document.types is not None else "observed_and_constraints",
                "relations": relations, "opaque_sections": opaque,
                "schema_digest": document.digest,
                "source_spans": {key: {"start": span.start, "end": span.end} for key, span in document.source_spans.items()},
                "editable": document.editable, "catalog_adoption_required": not document.catalog_present,
                "schema_issues": [{"code": issue.code, "message": issue.message, "line": issue.line,
                                   "severity": issue.severity} for issue in document.issues[:200]],
                "schema_issues_truncated": len(document.issues) > 200,
                "text": html.escape(source, quote=False), "text_format": "escaped_markdown"}

    def ontology(self, vault_id, parameters):
        self._parameters(parameters, {"generation"})
        with self._open(self.registry.root(vault_id), parameters.get("generation")) as (db, reference):
            return self._ontology(db, reference)

    def diagnostics(self, vault_id, parameters):
        self._parameters(parameters, {"generation"})
        status = self.status(vault_id, parameters)
        issues = list(status["issues"])
        if status["capabilities"]["graph"]:
            with self._open(self.registry.root(vault_id), status["graph_generation"]) as (db, reference):
                total, count = db.execute("SELECT coalesce(sum(length(CAST(content AS BLOB))),0),count(*) FROM graph_documents").fetchone()
                if total > 8 * 1024 * 1024 or count > 2000:
                    issues.append(_issue("diagnostics_limited", "warning", "Analisi semantica oltre i limiti iniziali",
                                         reference.content_revision))
                else:
                    documents = dict(db.execute("SELECT path,content FROM graph_documents"))
                    try:
                        parser = _parser()
                        parsed = parser.parse_documents(documents)
                        for issue in parsed['ontology'].issues:
                            issues.append(_issue('ontology_' + issue.code, issue.severity, issue.message,
                                                 reference.content_revision, 'Wiki reference.md'))
                        for message in parser.validate_snapshot(parsed):
                            page = "wiki/" + message.split(":", 1)[0] + ".md"
                            issues.append(_issue("semantic_issue", "error", message, reference.content_revision,
                                                 page if page in documents else "Wiki reference.md"))
                        if parsed["vocabolario"] is None:
                            issues.append(_issue("ontology_unstructured", "warning", "Tabella relazioni non riconosciuta",
                                                 reference.content_revision, "Wiki reference.md"))
                    except (ValueError, RecursionError) as error:
                        basename = str(error).split(":", 1)[0]
                        path = next((path for path in documents if path.rsplit("/", 1)[-1] == basename), None)
                        issues.append(_issue("parse_error", "error", "Documento della generazione non analizzabile",
                                             reference.content_revision, path))
        return {"content_revision": status["content_revision"], "graph_generation": status["graph_generation"],
                "live_content_revision": status["live_content_revision"], "stale": status["stale"],
                "issues": issues[:200], "truncated": len(issues) > 200}

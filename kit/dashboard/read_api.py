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

from .contracts import ContractError, canonical_json, content_hash, parse_json, portable_path, file_hash
from .storage import capture_snapshot, _no_link

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_CAUSAL_DEPTH = 10
MAX_CAUSAL_EDGES = 500
MAX_NEIGHBORS = 200


def _parser():
    # Modulo del runtime del servizio, mai caricato dal percorso del vault collegato.
    try:
        from ..graph import build_graph
    except ImportError:
        import build_graph
    return build_graph


def _lavorazioni():
    # Modulo del runtime del servizio, come build_graph: mai caricato dal percorso del vault collegato.
    try:
        from ..graph import lavorazioni
    except ImportError:
        import lavorazioni
    return lavorazioni


def _revision(reference):
    return {"content_revision": reference.content_revision, "graph_generation": reference.generation}


def _has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


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
            if metadata.get("builder_version") not in {"2", "3", "4", "5"}:
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
                if result["stale"] is False and result["validation_version"] >= 4 and not self._history_current(root, reference, result):
                    result["stale"] = True  # stessi contenuti ma HEAD diverso: gli autori del grafo sono indietro
                if result["stale"]:
                    result["issues"].append(_issue("graph_stale", "warning",
                        "Il vault o la sua storia Git sono cambiati; le API mostrano l'ultima generazione pubblicata", reference.content_revision))
        except ContractError as error:
            if error.code == "revision_changed":
                raise
            result["issues"].append(_issue(error.code, "warning", str(error), None))
        return result

    @staticmethod
    def _history_current(root, reference, status):
        """False se l'HEAD Git attuale non è quello su cui la generazione è stata costruita (identità: contenuti + HEAD)."""
        try:
            from .authors import history_head
            from .graph_service import BUILDER_VERSION
            head = history_head(root)
            expected = content_hash({"content_revision": reference.content_revision, "builder_version": BUILDER_VERSION,
                                     **({"history": head} if head else {})})
        except (ContractError, OSError):
            return True
        return status["validation_version"] != BUILDER_VERSION or expected == reference.generation

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
        self._parameters(parameters, {"generation", "limit", "type", "relation", "author", "cursor"})
        limit = parameters.get("limit", "100")
        if not limit.isascii() or not limit.isdecimal() or len(limit) > 3 or not 1 <= int(limit) <= 200:
            raise ContractError("invalid_query", "limit atteso fra 1 e 200")
        limit = int(limit)
        filters = {key: parameters.get(key) for key in ("type", "relation", "author")}
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
            by_author = "(SELECT entity_id FROM autori WHERE creato_da=? OR modificato_da=?)"
            if filters["author"]:
                if not _has_table(db, "autori"):
                    raise ContractError("graph_upgrade_required", "Autori non disponibili: ricostruire il grafo con il kit aggiornato")
                node_where.append("id IN " + by_author)
                node_args.extend([filters["author"]] * 2)
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
            if filters["author"]:
                edge_where.append("source_id IN " + by_author + " AND target_id IN " + by_author)
                edge_args.extend([filters["author"]] * 4)
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
            attributes = []
            if _has_table(db, "relation_attributes"):
                attributes = [dict(row) for row in db.execute("SELECT source_id,target_id,type,confidenza,evidenza FROM relation_attributes "
                    "WHERE source_id=? OR target_id=? ORDER BY source_id,target_id,type LIMIT 200", (node_id, node_id))]
            aliases = [row[0] for row in db.execute("SELECT alias FROM aliases WHERE entity_id=? ORDER BY alias LIMIT 201", (node_id,))]
            sources = [row[0] for row in db.execute("SELECT target_id FROM relations WHERE source_id=? "
                "AND type='documentato_in' ORDER BY target_id LIMIT 201", (node_id,))]
            authors = None
            if _has_table(db, "autori"):
                row = db.execute("SELECT creato_da,creato_il,modificato_da,modificato_il,agente,modifiche FROM autori "
                                 "WHERE entity_id=?", (node_id,)).fetchone()
                authors = dict(zip(("created_by", "created_at", "modified_by", "modified_at", "agent", "changes"), row)) if row else None
            return {**_revision(reference), "node": node, "properties": properties, "authors": authors,
                    "text": html.escape(text, quote=False) if text is not None else None,
                    "text_format": "escaped_markdown", "relations": relations[:200], "relation_attributes": attributes,
                    "aliases": aliases[:200], "sources": sources[:200],
                    "relations_truncated": len(relations) > 200, "aliases_truncated": len(aliases) > 200,
                    "sources_truncated": len(sources) > 200}

    def neighbors(self, vault_id, parameters):
        """Vicinato a un passo di un nodo (archi in entrata e in uscita) per espandere il disegno senza paginare tutto il grafo."""
        self._parameters(parameters, {"generation", "node", "limit"})
        node, limit = parameters.get("node"), parameters.get("limit", "100")
        if not node or "/" in node or "\\" in node or len(node) > 255:
            raise ContractError("invalid_query", "Richiesto il parametro node")
        if not limit.isascii() or not limit.isdecimal() or not 1 <= int(limit) <= MAX_NEIGHBORS:
            raise ContractError("invalid_query", f"limit atteso fra 1 e {MAX_NEIGHBORS}")
        limit = int(limit)
        with self._open(self.registry.root(vault_id), parameters.get("generation")) as (db, reference):
            if db.execute("SELECT 1 FROM entities WHERE id=?", (node,)).fetchone() is None:
                raise ContractError("node_missing", "Nodo non presente nella generazione")
            edges = [dict(zip(("source_id", "target_id", "type"), row)) for row in db.execute(
                "SELECT source_id,target_id,type FROM relations WHERE source_id=? OR target_id=? "
                "ORDER BY source_id,target_id,type LIMIT ?", (node, node, limit + 1))]
            truncated = len(edges) > limit
            edges = edges[:limit]
            ids = sorted({node, *(edge[key] for edge in edges for key in ("source_id", "target_id"))})
            nodes = [dict(zip(("id", "tipo", "descrizione"), row)) for row in db.execute(
                f"SELECT id,tipo,descrizione FROM entities WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids)]
            return {**_revision(reference), "root": node, "nodes": nodes, "edges": edges, "truncated": truncated}

    def causal(self, vault_id, parameters):
        """Catena causale orientata: cause (a ritroso) o effetti (in avanti) di un nodo lungo la sola relazione `causa`."""
        self._parameters(parameters, {"generation", "node", "direction", "depth"})
        node, direction, depth = parameters.get("node"), parameters.get("direction", "effects"), parameters.get("depth", "3")
        if not node or "/" in node or "\\" in node or len(node) > 255:
            raise ContractError("invalid_query", "Richiesto il parametro node")
        if direction not in ("effects", "causes"):
            raise ContractError("invalid_query", "direction atteso: effects o causes")
        if not depth.isascii() or not depth.isdecimal() or not 1 <= int(depth) <= MAX_CAUSAL_DEPTH:
            raise ContractError("invalid_query", f"depth atteso fra 1 e {MAX_CAUSAL_DEPTH}")
        forward = direction == "effects"
        with self._open(self.registry.root(vault_id), parameters.get("generation")) as (db, reference):
            if db.execute("SELECT 1 FROM entities WHERE id=?", (node,)).fetchone() is None:
                raise ContractError("node_missing", "Nodo non presente nella generazione")
            # Una sola query per nodo di frontiera: gli attributi d'arco arrivano con un LEFT JOIN (NULL se la tabella manca).
            join, columns = (("LEFT JOIN relation_attributes a ON a.source_id=r.source_id AND a.target_id=r.target_id AND a.type=r.type",
                              "a.confidenza,a.evidenza") if _has_table(db, "relation_attributes") else ("", "NULL,NULL"))
            column = "r.source_id" if forward else "r.target_id"
            frontier, seen, edges, truncated = [node], {node}, [], False
            for level in range(int(depth)):
                found = []
                for current in frontier:
                    rows = db.execute(f"SELECT r.source_id,r.target_id,{columns} FROM relations r {join} "
                                      f"WHERE r.type='causa' AND {column}=? ORDER BY r.source_id,r.target_id", (current,)).fetchall()
                    for source, target, confidence, evidence in rows:
                        if len(edges) >= MAX_CAUSAL_EDGES:
                            truncated = True
                            break
                        edges.append({"source_id": source, "target_id": target, "type": "causa", "level": level + 1,
                                      "confidenza": confidence, "evidenza": evidence})
                        follow = target if forward else source
                        if follow not in seen:
                            seen.add(follow)
                            found.append(follow)
                    if truncated:
                        break
                if truncated:
                    break
                frontier = found
            marks = ",".join("?" * len(seen))
            nodes = [dict(zip(("id", "tipo", "descrizione"), row)) for row in db.execute(
                f"SELECT id,tipo,descrizione FROM entities WHERE id IN ({marks}) ORDER BY id", tuple(seen))]
            return {**_revision(reference), "root": node, "direction": direction, "depth": int(depth),
                    "nodes": nodes, "edges": edges, "truncated": truncated, "cycle": any(
                        edge["target_id" if forward else "source_id"] == node for edge in edges)}

    def authors(self, vault_id, parameters):
        self._parameters(parameters, {"generation"})
        with self._open(self.registry.root(vault_id), parameters.get("generation")) as (db, reference):
            if not _has_table(db, "autori"):
                return {**_revision(reference), "authors": [], "available": False}
            names = {}
            for column, key in (("creato_da", "created"), ("modificato_da", "modified")):
                for name, count in db.execute(f"SELECT {column},count(*) FROM autori WHERE {column} IS NOT NULL GROUP BY {column}"):
                    names.setdefault(name, {"name": name, "created": 0, "modified": 0})[key] = count
            return {**_revision(reference), "authors": sorted(names.values(), key=lambda item: item["name"])[:200],
                    "available": True}

    def lavorazioni(self, vault_id, parameters):
        """Stato delle lavorazioni (pipeline ICM) del vault: sola lettura, senza grafo né generazione."""
        self._parameters(parameters, set())
        try:
            return _lavorazioni().pannello(self.registry.root(vault_id))
        except OSError as error:
            raise ContractError("lavorazioni_illeggibili", "La cartella lavorazioni/ non è leggibile") from error

    @staticmethod
    def _ontology(db, reference):
        source = ReadAPI._document(db, "Wiki reference.md")
        document = _parser().parse_ontology(source)
        if _has_table(db, "onto_tipi"):  # builder 5 (doc/16): l'ontologia che il builder ha usato, già nel grafo
            constraints = {}
            for relation, side, kind in db.execute("SELECT relazione, lato, tipo FROM onto_vincoli ORDER BY posizione"):
                constraints.setdefault((relation, side), []).append(kind)
            relations = [{"name": name, "from_types": constraints.get((name, "da"), []),
                          "to_types": constraints.get((name, "a"), []), "direction": direction,
                          "meaning": meaning, "example": example} for name, meaning, example, direction in db.execute(
                "SELECT nome, significato, esempio, verso FROM onto_relazioni ORDER BY nome")]
            types = [name for (name,) in db.execute("SELECT nome FROM onto_tipi ORDER BY posizione")]
            declared = dict(db.execute("SELECT chiave, valore FROM onto_metadata"))["tipi"] == "dichiarati"
        else:  # generazioni precedenti: stessa risposta ricavata dal Markdown memorizzato
            relations = [{"name": item.name, "from_types": list(item.from_types), "to_types": list(item.to_types),
                          "direction": item.direction, "meaning": item.meaning, "example": item.example}
                         for item in sorted(document.relations, key=lambda item: item.name)]
            declared = document.types is not None
            if declared:
                types = [item.name for item in document.types]
            else:
                types = {row[0] for row in db.execute("SELECT DISTINCT tipo FROM entities WHERE tipo IS NOT NULL")}
                for item in relations:
                    types.update(item["from_types"] + item["to_types"])
                types = sorted(types - {"qualsiasi", "stesso tipo"})
        opaque = [html.escape(document.source[span.start:span.end].decode('utf-8'), quote=False)
                  for span in document.opaque_sections]
        return {**_revision(reference), "types": types, "types_source": "declared" if declared else "observed_and_constraints",
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

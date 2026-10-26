"""API readonly su generazioni reali: coerenza revisioni, pagine e sicurezza."""
import _shortpath  # noqa: F401
import json
from urllib.parse import quote, urlencode

import test_dashboard_readonly as fixture
import unittest

from kit.dashboard.graph_service import rebuild, file_hash


class Queries(unittest.TestCase):
    stop = fixture.ReadonlyHTTP.stop
    request = fixture.ReadonlyHTTP.request
    manifest = fixture.ReadonlyHTTP.manifest
    hashes = fixture.ReadonlyHTTP.hashes
    attach = fixture.ReadonlyHTTP.attach

    def setUp(self):
        fixture.ReadonlyHTTP.setUp(self)
        self.manifest()
        (self.root / "wiki/Anna.md").unlink()
        self.schema = (
            "## Relazioni tipizzate\n| Nome | Da | A | Significato | Esempio |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| `usa` | persona | persona | X usa Y | Anna → Bruno |\n"
            "## Convenzioni libere\n<script>opaque</script>\n"
            "## Fonti\n| `nota-utente` | Precisazione utente |\n")
        (self.root / "Wiki reference.md").write_text(self.schema, encoding="utf-8")
        self.page = self.root / "wiki/Anna Rossi.md"
        self.page.write_text('---\ntipo: persona\naliases: [Anni]\nfonti: [nota-utente]\n'
                             'usa: "[[Bruno]]"\n---\n<script>old</script> [[Bruno]]', encoding="utf-8")
        (self.root / "wiki/Bruno.md").write_text("---\ntipo: persona\n---\nBruno", encoding="utf-8")
        (self.root / "wiki/Équipe.md").write_text("---\ntipo: sistema\n---\nÉquipe", encoding="utf-8")
        self.reference = rebuild(self.root)
        self.vault_id = self.attach()["vault_id"]
        self.base = f"/api/v1/vaults/{self.vault_id}/"

    def get(self, endpoint, parameters=None, headers=None):
        query = "?" + urlencode(parameters) if parameters else ""
        status, response_headers, data = self.request("GET", self.base + endpoint + query, headers=headers)
        return status, response_headers, json.loads(data) if data else None

    def test_consistent_revision_across_status_graph_node_ontology_and_diagnostics(self):
        before = self.hashes()
        for endpoint in ("status", "graph", "nodes/" + quote("Anna Rossi", safe=""), "ontology", "diagnostics"):
            with self.subTest(endpoint=endpoint):
                status, _, body = self.get(endpoint, {"generation": self.reference.generation})
                self.assertEqual(status, 200, body)
                self.assertEqual(body["content_revision"], self.reference.content_revision)
                self.assertEqual(body["graph_generation"], self.reference.generation)
        self.assertEqual(self.hashes(), before)
        self.assertFalse((self.root / "EXECUTED").exists())

    def test_graph_pagination_is_deterministic_and_has_no_duplicates(self):
        parameters = {"limit": "1"}
        nodes, edges = [], []
        for page in range(20):
            status, _, body = self.get("graph", parameters)
            self.assertEqual(status, 200, body)
            nodes += [node["id"] for node in body["nodes"]]
            edges += [(edge["source_id"], edge["target_id"], edge["type"]) for edge in body["edges"]]
            self.assertLessEqual(len(body["nodes"]), 1)
            self.assertLessEqual(len(body["edges"]), 1)
            if not body["next_cursor"]:
                break
            parameters["cursor"] = body["next_cursor"]
        else:
            self.fail("Paginazione senza termine")
        self.assertEqual(nodes, ["Anna Rossi", "Bruno", "nota-utente", "Équipe"])
        self.assertEqual(len(edges), len(set(edges)))
        self.assertEqual(len(edges), 3)

    def test_filters_and_sql_inputs_are_parameterized(self):
        status, _, body = self.get("graph", {"type": "persona", "relation": "usa"})
        self.assertEqual(status, 200, body)
        self.assertEqual([node["id"] for node in body["nodes"]], ["Anna Rossi", "Bruno"])
        self.assertEqual(body["edges"], [{"source_id": "Anna Rossi", "target_id": "Bruno", "type": "usa"}])
        status, _, body = self.get("graph", {"type": "persona' OR 1=1 --"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["nodes"], [])
        self.assertEqual(body["edges"], [])

    def test_old_cursor_and_pins_conflict_after_publish(self):
        _, _, page = self.get("graph", {"limit": "1"})
        self.page.write_text(self.page.read_text(encoding="utf-8") + "\nNuova nota", encoding="utf-8")
        second = rebuild(self.root)
        status, _, body = self.get("graph", {"limit": "1", "cursor": page["next_cursor"]})
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error"]["code"], "revision_changed")
        for endpoint in ("status", "graph", "nodes/Bruno", "ontology", "diagnostics"):
            status, _, body = self.get(endpoint, {"generation": self.reference.generation})
            self.assertEqual(status, 409, (endpoint, body))
        status, _, body = self.get("nodes/Bruno", {"generation": second.generation})
        self.assertEqual(status, 200, body)

    def test_live_edits_do_not_mix_schema_or_text_with_published_generation(self):
        self.page.write_text("---\ntipo: persona\n---\nNUOVO TESTO NON PUBBLICATO", encoding="utf-8")
        (self.root / "Wiki reference.md").write_text("Nuovo schema non pubblicato", encoding="utf-8")
        status, _, body = self.get("status")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["stale"])
        self.assertNotEqual(body["live_content_revision"], body["content_revision"])
        _, _, node = self.get("nodes/" + quote("Anna Rossi", safe=""))
        self.assertIn("&lt;script&gt;old&lt;/script&gt;", node["text"])
        self.assertNotIn("NUOVO", node["text"])
        _, _, ontology = self.get("ontology")
        self.assertEqual(ontology["relations"][0]["name"], "usa")
        _, _, diagnostics = self.get("diagnostics")
        self.assertTrue(any(issue["code"] == "graph_stale" for issue in diagnostics["issues"]))
        self.assertTrue(all(issue["revision"] == self.reference.content_revision for issue in diagnostics["issues"]))

    def test_cursor_tamper_and_filter_change_rejected(self):
        _, _, body = self.get("graph", {"limit": "1"})
        cursor = body["next_cursor"]
        tampered = ("A" if cursor[0] != "A" else "B") + cursor[1:]
        for parameters in ({"limit": "1", "cursor": tampered},
                           {"limit": "1", "cursor": cursor, "type": "persona"},
                           {"limit": "2", "cursor": cursor}):
            status, _, body = self.get("graph", parameters)
            self.assertEqual(status, 400, body)
            self.assertEqual(body["error"]["code"], "invalid_cursor")

    def test_etag_and_conditional_get_are_generation_specific(self):
        for endpoint in ("status", "graph", "nodes/Bruno", "ontology", "diagnostics"):
            with self.subTest(endpoint=endpoint):
                status, headers, body = self.get(endpoint)
                self.assertEqual(status, 200, body)
                status, response_headers, body = self.get(endpoint, headers={"If-None-Match": headers["ETag"]})
                self.assertEqual(status, 304)
                self.assertIsNone(body)
                self.assertEqual(response_headers["ETag"], headers["ETag"])

    def test_unicode_nodes_escaped_text_properties_and_source_nodes(self):
        for node_id in ("Anna Rossi", "Équipe", "nota-utente"):
            status, _, body = self.get("nodes/" + quote(node_id, safe=""))
            self.assertEqual(status, 200, body)
            self.assertEqual(body["node"]["id"], node_id)
            if node_id == "Anna Rossi":
                self.assertNotIn("<script>", body["text"])
                self.assertEqual(body["properties"]["tipo"], "persona")
                self.assertEqual(body["aliases"], ["Anni"])
                self.assertEqual(body["sources"], ["nota-utente"])
            elif node_id == "nota-utente":
                self.assertIsNone(body["text"])

    def test_ontology_direction_meaning_and_opaque_sections_preserved(self):
        status, _, body = self.get("ontology")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["relations"][0]["direction"], "source_to_target")
        self.assertEqual(body["relations"][0]["meaning"], "X usa Y")
        self.assertIn("persona", body["types"])
        self.assertEqual(body["types_source"], "observed_and_constraints")
        self.assertIn("&lt;script&gt;opaque&lt;/script&gt;", "".join(body["opaque_sections"]))

    def test_query_bounds_traversal_and_unknown_nodes(self):
        for parameters in ({"limit": "0"}, {"limit": "201"}, {"limit": "-1"},
                           {"limit": "1.0"}, {"sql": "DROP TABLE entities"}, {"generation": "../private"}):
            status, _, body = self.get("graph", parameters)
            self.assertEqual(status, 400, body)
        self.assertEqual(self.get("nodes/not-found")[0], 404)
        self.assertEqual(self.get("nodes/..%2Fprivate")[0], 403)
        self.assertEqual(self.get("nodes/%ZZ")[0], 400)
        self.assertEqual(self.get("graph?limit=1&limit=2")[0], 400)

    def test_corrupt_hash_has_no_silent_fallback_or_rebuild(self):
        with self.reference.path.open("ab") as stream:
            stream.write(b"tampered")
        before = self.hashes()
        status, _, body = self.get("graph")
        self.assertEqual(status, 503, body)
        self.assertEqual(body["error"]["code"], "graph_corrupt")
        _, _, diagnostics = self.get("diagnostics")
        self.assertTrue(any(issue["code"] == "graph_corrupt" for issue in diagnostics["issues"]))
        self.assertEqual(self.hashes(), before)

    def test_legacy_or_old_generation_reports_unavailable_without_migration(self):
        import sqlite3
        db = sqlite3.connect(self.reference.path)
        db.execute("UPDATE graph_metadata SET value='1' WHERE key='builder_version'")
        db.commit()
        db.close()
        marker = self.root / ".teseo/local/graph-current.json"
        record = json.loads(marker.read_bytes())
        record["sqlite_sha256"] = file_hash(self.reference.path)
        marker.write_text(json.dumps(record), encoding="utf-8")
        before = self.hashes()
        status, _, body = self.get("graph")
        self.assertEqual(status, 503, body)
        self.assertEqual(body["error"]["code"], "graph_upgrade_required")
        self.assertEqual(self.hashes(), before)

    def test_legacy_graph_is_not_read_or_migrated_by_get(self):
        root = self.root / "legacy"
        (root / "wiki").mkdir(parents=True)
        (root / ".graph").mkdir()
        (root / "Wiki reference.md").write_text("Schema legacy", encoding="utf-8")
        (root / ".graph/graph.sqlite").write_bytes(b"not SQLite: must not open")
        status, _, body = self.request("POST", "/api/v1/vaults/attach", {"path": str(root)})
        self.assertEqual(status, 200, body)
        identifier = json.loads(body)["vault_id"]
        before = self.hashes()
        status, _, body = self.request("GET", f"/api/v1/vaults/{identifier}/graph")
        self.assertEqual(status, 503, body)
        self.assertEqual(json.loads(body)["error"]["code"], "graph_unavailable")
        status, _, body = self.request("GET", f"/api/v1/vaults/{identifier}/diagnostics")
        self.assertEqual(status, 200, body)
        self.assertIsNone(json.loads(body)["graph_generation"])
        self.assertEqual(self.hashes(), before)

    def test_diagnostics_separate_parse_and_semantic_issues_on_stored_documents(self):
        import sqlite3
        for source, expected in (("[[Pagina assente]]", "semantic_issue"),
                                 ("---\ntipo: [\n---\n", "parse_error")):
            db = sqlite3.connect(self.reference.path)
            db.execute("UPDATE graph_documents SET content=? WHERE path='wiki/Anna Rossi.md'", (source,))
            db.commit()
            db.close()
            marker = self.root / ".teseo/local/graph-current.json"
            record = json.loads(marker.read_bytes())
            record["sqlite_sha256"] = file_hash(self.reference.path)
            marker.write_text(json.dumps(record), encoding="utf-8")
            before = self.hashes()
            status, _, body = self.get("diagnostics")
            self.assertEqual(status, 200, body)
            issue = next(item for item in body["issues"] if item["code"] == expected)
            self.assertEqual(issue["severity"], "error")
            self.assertEqual(issue["path"], "wiki/Anna Rossi.md")
            self.assertEqual(issue["revision"], self.reference.content_revision)
            self.assertEqual(self.hashes(), before)


if __name__ == "__main__":
    unittest.main()

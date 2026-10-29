"""Gate Windows: lettore aperto, pubblicazione interrotta e backup SQLite WAL."""
import _shortpath  # noqa: F401
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kit/graph"))
from kit.dashboard import graph_service as service
from kit.dashboard.contracts import ContractError
from kit.graph.graph_db import connect_graph, graph_reference, GraphDatabaseError


class Generations(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="teseo generations ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()  # macOS: /var è un link a /private/var e il codice lavora su percorsi risolti
        (self.root / "wiki").mkdir()
        (self.root / ".teseo").mkdir()
        (self.root / ".graph").mkdir()
        for source in (ROOT / "kit/graph").glob("*.py"):
            shutil.copyfile(source, self.root / ".graph" / source.name)
        shutil.copytree(ROOT / "kit/dashboard", self.root / ".graph/dashboard",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / ".teseo/project.json").write_bytes(
            (ROOT / "tests/fixtures/dashboard/project-v1.json").read_bytes())
        (self.root / "Wiki reference.md").write_text("Schema legacy compatibile", encoding="utf-8")
        self.page = self.root / "wiki/Anna.md"
        self.page.write_text("---\ntipo: persona\n---\nPrima versione", encoding="utf-8")
        self.legacy = self.root / ".graph/graph.sqlite"
        self.marker = self.root / ".teseo/local/graph-current.json"

    def assert_code(self, code, function, *args):
        with self.assertRaises(ContractError) as raised:
            function(*args)
        self.assertEqual(raised.exception.code, code)

    def script(self, name, *args, stdin=None):
        return subprocess.run([sys.executable, str(self.root / ".graph" / name), *args],
                              cwd=self.root, input=stdin, capture_output=True, timeout=30,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    def test_open_windows_reader_keeps_old_generation_during_new_publication(self):
        first = service.rebuild(self.root)
        old = connect_graph(self.legacy)
        try:
            self.page.write_text("---\ntipo: persona\n---\nSeconda versione", encoding="utf-8")
            second = service.rebuild(self.root)
            new = connect_graph(self.legacy)
            try:
                self.assertNotEqual(first.generation, second.generation)
                self.assertIn("Prima", old.execute("SELECT corpo FROM testo").fetchone()[0])
                self.assertIn("Seconda", new.execute("SELECT corpo FROM testo").fetchone()[0])
                self.assertEqual(old.graph_generation, first.generation)
                self.assertEqual(new.content_revision, second.content_revision)
                with self.assertRaises(sqlite3.OperationalError):
                    new.execute("DELETE FROM entities")
            finally:
                new.close()
            self.assertTrue(first.path.exists())
            self.assertFalse(self.legacy.exists())
        finally:
            old.close()

    def test_noop_keeps_marker_and_generation_bytes(self):
        first = service.rebuild(self.root)
        marker = self.marker.read_bytes()
        stamp = self.marker.stat().st_mtime_ns
        with mock.patch.object(service.build_graph, "build_candidate", side_effect=AssertionError("no build")):
            self.assertEqual(service.rebuild(self.root), first)
        self.assertEqual(self.marker.read_bytes(), marker)
        self.assertEqual(self.marker.stat().st_mtime_ns, stamp)
        db = sqlite3.connect(first.path)
        try:
            db.execute("UPDATE graph_metadata SET value='999' WHERE key='builder_version'")
            db.commit()
        finally:
            db.close()
        record = json.loads(self.marker.read_bytes())
        record["sqlite_sha256"] = service.file_hash(first.path)
        self.marker.write_text(json.dumps(record), encoding="utf-8")
        self.assert_code("graph_corrupt", service.rebuild, self.root)
        if os.name == "nt":
            graphs = self.root / ".teseo/local/graphs"
            saved = graphs.with_name("graphs-original")
            self.assertTrue(graphs.resolve().is_relative_to(self.root))
            self.assertTrue(saved.parent.resolve().is_relative_to(self.root))
            graphs.rename(saved)
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(graphs), str(saved)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                self.assert_code("linked_path", service.rebuild, self.root)
            finally:
                graphs.rmdir()
                saved.rename(graphs)

    def test_failed_validation_keeps_current_generation(self):
        first = service.rebuild(self.root)
        marker = self.marker.read_bytes()
        self.page.write_text("[[Assente]]", encoding="utf-8")
        with self.assertRaises(service.build_graph.GraphValidationError):
            service.rebuild(self.root)
        self.assertEqual(self.marker.read_bytes(), marker)
        self.assertEqual(graph_reference(self.legacy), first)

    def test_marker_replace_failure_preserves_old_and_retry_checks_orphan(self):
        first = service.rebuild(self.root)
        self.page.write_text("Seconda versione", encoding="utf-8")
        replace = os.replace
        def injected(source, target):
            if Path(target) == self.marker:
                raise PermissionError("injected")
            return replace(source, target)
        with mock.patch.object(service.os, "replace", side_effect=injected):
            with self.assertRaises(PermissionError):
                service.rebuild(self.root)
        self.assertEqual(graph_reference(self.legacy), first)
        self.assertEqual(len(list(first.path.parent.glob("*.sqlite"))), 2)
        second = service.rebuild(self.root)
        self.assertNotEqual(second.generation, first.generation)
        self.assertEqual(len(list(first.path.parent.glob("*.sqlite"))), 2)

    def test_external_change_during_build_preserves_current(self):
        first = service.rebuild(self.root)
        self.page.write_text("Candidato", encoding="utf-8")
        build = service.build_graph.build_candidate
        def injected(snapshot, out):
            candidate = build(snapshot, out)
            self.page.write_text("Modifica esterna", encoding="utf-8")
            return candidate
        with mock.patch.object(service.build_graph, "build_candidate", side_effect=injected):
            self.assert_code("blocked_external_change", service.rebuild, self.root)
        self.assertEqual(graph_reference(self.legacy), first)
        self.assertEqual(self.page.read_text(encoding="utf-8"), "Modifica esterna")

    def test_process_crash_before_marker_keeps_old_and_retry_recovers(self):
        first = service.rebuild(self.root)
        self.page.write_text("Dopo il crash", encoding="utf-8")
        script = (
            "import os,sys; from pathlib import Path; "
            "sys.path.insert(0,str(Path(sys.argv[1])/'.graph')); "
            "from dashboard import graph_service as service; "
            "service._atomic_marker=lambda *args: os._exit(27); "
            "service.rebuild(Path(sys.argv[1]))"
        )
        result = subprocess.run([sys.executable, "-c", script, str(self.root)], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 27, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(graph_reference(self.legacy), first)
        self.assertEqual(len(list(first.path.parent.glob("*.sqlite"))), 2)
        second = service.rebuild(self.root)
        self.assertNotEqual(second.generation, first.generation)
        self.assertTrue(first.path.exists())

    def test_unsupported_events_do_not_publish_partial_view(self):
        first = service.rebuild(self.root)
        events = self.root / ".teseo/shared/events"
        events.mkdir(parents=True)
        (events / "a.json").write_text("{}", encoding="utf-8")
        self.assert_code("invalid_event", service.rebuild, self.root)
        self.assertEqual(graph_reference(self.legacy), first)

    def test_pointer_traversal_unknown_version_and_missing_generation_rejected(self):
        service.rebuild(self.root)
        original = json.loads(self.marker.read_bytes())
        for key, value in (("generation", "../../private"), ("format_version", True),
                           ("generation", "0" * 64)):
            with self.subTest(key=key, value=value):
                self.marker.write_text(json.dumps({**original, key: value}), encoding="utf-8")
                with self.assertRaises(GraphDatabaseError):
                    connect_graph(self.legacy)

    def test_missing_manifest_never_falls_back_to_legacy_writes(self):
        first = service.rebuild(self.root)
        (self.root / ".teseo/project.json").unlink()
        result = self.script("build_graph.py", "--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(graph_reference(self.legacy), first)

    def test_installed_cli_and_hook_read_generation_without_legacy_file(self):
        result = self.script("build_graph.py", "--check")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertFalse(self.legacy.exists())
        for name, args in (("recall.py", ["Anna"]), ("sintesi.py", ["--verifica"]),
                           ("domande.py", ["--json"]), ("banco.py", ["--semi"])):
            with self.subTest(name=name):
                result = self.script(name, *args)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        result = self.script("recall_hook.py", stdin=b'{"prompt":"Anna","session_id":"test"}')
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIsInstance(json.loads(result.stdout), dict)
        self.assertFalse(self.legacy.exists())
        reference = graph_reference(self.legacy)
        self.assertIn(reference.content_revision, result.stdout.decode("utf-8"))
        result = self.script("recall.py", "Anna", "--json")
        self.assertEqual(json.loads(result.stdout)["graph_generation"], reference.generation)
        result = self.script("backup_personal.py")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

    def test_sqlite_backup_includes_committed_wal_and_preserves_source(self):
        source_path = self.root / ".graph/memoria.sqlite"
        source = sqlite3.connect(source_path)
        try:
            source.execute("PRAGMA journal_mode=WAL")
            source.execute("CREATE TABLE personal (text TEXT)")
            source.execute("INSERT INTO personal VALUES ('committed')")
            source.commit()
            self.assertTrue(source_path.with_name("memoria.sqlite-wal").exists())
            source.execute("INSERT INTO personal VALUES ('uncommitted')")
            backup = service.backup_personal_databases(self.root)
            db = sqlite3.connect(backup / "memoria.sqlite")
            try:
                self.assertEqual(db.execute("SELECT text FROM personal").fetchall(), [("committed",)])
            finally:
                db.close()
            record = json.loads((backup / "backup.json").read_bytes())
            self.assertEqual(record["databases"]["memoria.sqlite"]["sha256"],
                             service.file_hash(backup / "memoria.sqlite"))
            self.assertFalse((self.root / ".graph/domande.sqlite").exists())
            self.assertEqual(source.execute("SELECT count(*) FROM personal").fetchone(), (2,))
        finally:
            source.close()

    def test_incomplete_backup_has_no_completion_marker(self):
        path = self.root / ".graph/domande.sqlite"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE answers (text TEXT)")
        db.commit()
        db.close()
        with mock.patch.object(service, "_check_database", side_effect=sqlite3.DatabaseError("injected")):
            with self.assertRaises(sqlite3.DatabaseError):
                service.backup_personal_databases(self.root)
        backups = list((self.root / ".teseo/local/backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertFalse((backups[0] / "backup.json").exists())
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()

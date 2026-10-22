"""Regressioni del gate di pubblicazione legacy: nessun vault personale."""
import contextlib
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kit" / "graph"))
import build_graph as graph


class Publication(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="teseo graph ")
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        (self.vault / "wiki").mkdir()
        (self.vault / ".graph").mkdir()
        (self.vault / "Wiki reference.md").write_text(
            "## Relazioni tipizzate\n\n| Relazione | Da | A |\n| --- | --- | --- |\n"
            "| `usa` | persona | persona |\n", encoding="utf-8")
        self.page = self.vault / "wiki/Anna.md"
        self.page.write_text("---\ntipo: persona\n---\nNota iniziale\n", encoding="utf-8")
        self.out = self.vault / ".graph/graph.sqlite"
        with contextlib.redirect_stdout(io.StringIO()):
            graph.costruisci(self.vault, self.out)
        self.before = self.out.read_bytes()

    def assert_preserved(self):
        self.assertEqual(self.out.read_bytes(), self.before)
        self.assertEqual(list(self.out.parent.glob("*.tmp")), [])

    def test_invalid_cli_preserves_previous_graph_with_and_without_check(self):
        self.page.write_text("---\ntipo: persona\n---\n[[Assente]]\n", encoding="utf-8")
        for flags in (["--check"], []):
            with self.subTest(flags=flags):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "kit/graph/build_graph.py"), "--vault", str(self.vault),
                     "--out", str(self.out), *flags], capture_output=True, timeout=30,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                self.assertEqual(result.returncode, 1, result.stderr.decode("utf-8", "replace"))
                self.assertIn("Anna: link non risolto", result.stdout.decode("utf-8"))
                self.assert_preserved()

    def test_semantic_issues_prevent_any_candidate(self):
        for content in (
            '---\ntipo: persona\nignota: "[[Bruno]]"\n---\n',
            '---\ntipo: sistema\nusa: "[[Bruno]]"\n---\n',
            '---\ntipo: persona\naliases: [Bruno]\n---\n',
        ):
            with self.subTest(content=content):
                (self.vault / "wiki/Bruno.md").write_text("---\ntipo: persona\n---\n", encoding="utf-8")
                self.page.write_text(content, encoding="utf-8")
                with self.assertRaises(graph.GraphValidationError):
                    graph.costruisci(self.vault, self.out)
                self.assert_preserved()

    def test_invalid_yaml_and_non_mapping_preserve_previous(self):
        for content in ("---\ntipo: [\n---\n", "---\n- voce\n---\n", "---\nfalse\n---\n", "---\ntipo: persona\n"):
            with self.subTest(content=content):
                self.page.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Anna.md"):
                    graph.costruisci(self.vault, self.out)
                self.assert_preserved()

    def test_missing_wiki_does_not_publish_empty_graph(self):
        self.page.unlink()
        (self.vault / "wiki").rmdir()
        with self.assertRaisesRegex(ValueError, "wiki/"):
            graph.costruisci(self.vault, self.out)
        self.assert_preserved()

    def test_failed_first_build_does_not_create_graph(self):
        self.out.unlink()
        self.page.write_text("[[Assente]]", encoding="utf-8")
        with self.assertRaises(graph.GraphValidationError):
            graph.costruisci(self.vault, self.out)
        self.assertFalse(self.out.exists())

    def test_preparation_is_separate_and_candidates_are_unique(self):
        snapshot = graph.parse_snapshot(self.vault)
        self.assertEqual(graph.validate_snapshot(snapshot), ())
        first = graph.build_candidate(snapshot, self.out)
        self.addCleanup(first.unlink, missing_ok=True)
        second = graph.build_candidate(snapshot, self.out)
        self.addCleanup(second.unlink, missing_ok=True)
        self.assertNotEqual(first, second)
        self.assertEqual(self.out.read_bytes(), self.before)
        for candidate in (first, second):
            db = sqlite3.connect(candidate)
            try:
                self.assertEqual(db.execute("SELECT id FROM entities").fetchall(), [("Anna",)])
            finally:
                db.close()

    def test_database_failure_cleans_candidate(self):
        with mock.patch.object(graph.sqlite3, "connect", side_effect=sqlite3.OperationalError("injected")):
            with self.assertRaises(sqlite3.OperationalError):
                graph.costruisci(self.vault, self.out)
        self.assert_preserved()

    def test_replace_failure_cleans_candidate_and_preserves_current(self):
        with mock.patch.object(graph.os, "replace", side_effect=PermissionError("injected")):
            with self.assertRaises(PermissionError):
                graph.costruisci(self.vault, self.out)
        self.assert_preserved()

    def test_corrupt_candidate_is_not_published(self):
        candidate = self.out.parent / "corrupt.tmp"
        candidate.write_bytes(b"not sqlite")
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                graph.publish_generation(candidate, self.out)
            self.assertEqual(self.out.read_bytes(), self.before)
        finally:
            candidate.unlink()

    def test_readonly_integrity_check_does_not_create_missing_candidate(self):
        candidate = self.out.parent / "missing.tmp"
        with self.assertRaises(sqlite3.OperationalError):
            graph.publish_generation(candidate, self.out)
        self.assertFalse(candidate.exists())
        self.assert_preserved()

    def test_hook_refuses_invalid_rebuild_and_keeps_previous(self):
        from recall_hook import aggiorna
        self.page.write_text("[[Assente]]", encoding="utf-8")
        # Il legacy hook usa ancora mtime: forzare un sorgente più recente.
        stamp = self.out.stat().st_mtime + 10
        os.utime(self.page, (stamp, stamp))
        with self.assertRaises(graph.GraphValidationError):
            aggiorna(self.vault, self.out)
        self.assert_preserved()

    def test_valid_rebuild_publishes_new_content(self):
        self.page.write_text("---\ntipo: persona\n---\nNota aggiornata\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(graph.costruisci(self.vault, self.out), [])
        db = sqlite3.connect(self.out)
        try:
            self.assertIn("aggiornata", db.execute("SELECT corpo FROM testo").fetchone()[0])
        finally:
            db.close()
        self.assertNotEqual(self.out.read_bytes(), self.before)
        self.assertEqual(list(self.out.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

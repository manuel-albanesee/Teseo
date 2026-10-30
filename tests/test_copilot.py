"""Contratti Copilot CLI e migrazione Claude: solo fixture locali, nessun modello."""
import _shortpath  # noqa: F401
import contextlib
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from test_codex import installa


class CopilotIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teseo copilot ")
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name).resolve() / "Vault con spazi"  # macOS: /var → /private/var
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installa.installa(self.vault, esempio=True), 0)

    def hook(self, event, **fields):
        payload = {"sessionId": "test", "timestamp": 1792400000000, "cwd": str(self.vault),
                   "prompt": "chi è il referente del Rilascio in produzione?", **fields}
        return self.run_hook("copilot_hook.py", payload, event)

    def run_hook(self, script, payload, *args):
        result = subprocess.run([sys.executable, "-B", str(self.vault / ".graph" / script), *args],
                                input=json.dumps(payload).encode("utf-8"), cwd=self.vault,
                                capture_output=True, timeout=60,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout or b"{}")

    def test_configuration_native_commands_and_merge(self):
        claude = json.loads((self.vault / ".claude/settings.json").read_text(encoding="utf-8"))
        command = claude["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn(Path(sys.executable).as_posix(), command)
        self.assertIn("/.graph/claude_hook.py", command)
        path = self.vault / ".github/hooks/teseo.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["hooks"]), 8)
        script_per_evento = {"sessionStart": ["copilot_hook.py"], "userPromptSubmitted": ["copilot_hook.py"],
                             "userPromptTransformed": ["copilot_hook.py"],
                             "postToolUse": ["copilot_hook.py", "copilot_timing_hook.py"],
                             "agentStop": ["copilot_hook.py"], "sessionEnd": ["copilot_hook.py"],
                             "preToolUse": ["copilot_timing_hook.py"],
                             "postToolUseFailure": ["copilot_timing_hook.py"]}
        self.assertEqual(set(data["hooks"]), set(script_per_evento))
        for event, handlers in data["hooks"].items():
            self.assertEqual(len(handlers), len(script_per_evento[event]))
            for handler, script in zip(handlers, script_per_evento[event]):
                self.assertEqual(handler["exec"], sys.executable)
                self.assertEqual(handler["args"], [str(self.vault / ".graph" / script), event])
                self.assertEqual(handler["cwd"], str(self.vault))
                self.assertNotIn("command", handler)
        foreign = {"type": "command", "command": "echo mio-hook", "timeoutSec": 2}
        data["hooks"]["sessionStart"].insert(0, foreign)
        data["metadata"] = "conservare"
        path.write_text(json.dumps(data), encoding="utf-8")
        report = installa.Rapporto()
        self.assertTrue(installa.unisci_hook_copilot(self.vault, report))
        first = path.read_bytes()
        self.assertTrue(installa.unisci_hook_copilot(self.vault, report))
        self.assertEqual(path.read_bytes(), first)
        self.assertIn(foreign, json.loads(first)["hooks"]["sessionStart"])
        self.assertEqual(json.loads(first)["metadata"], "conservare")

    def test_malformed_configuration_fails_without_overwriting(self):
        path = self.vault / ".github/hooks/teseo.json"
        for text in ("{err", "[]", '{"version":2}', '{"version":1,"hooks":{"agentStop":[null]}}'):
            with self.subTest(text=text), contextlib.redirect_stdout(io.StringIO()):
                path.write_text(text, encoding="utf-8")
                self.assertNotEqual(installa.installa(self.vault, client="copilot", solo_integrazione=True), 0)
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_recall_transformation_preserves_runtime_content(self):
        self.assertIn("additionalContext", self.hook("sessionStart"))
        self.assertEqual(self.hook("userPromptSubmitted"), {})
        original = "<attachment>contenuto già trasformato</attachment>\nDomanda originale"
        output = self.hook("userPromptTransformed", transformedPrompt=original)
        enriched = output["modifiedTransformedPrompt"]
        self.assertTrue(enriched.startswith(original + "\n\n<teseo-context"))
        self.assertIn("Anna Rossi", enriched)
        self.assertEqual(self.hook("userPromptTransformed", transformedPrompt=enriched), {})
        with closing(sqlite3.connect(self.vault / ".graph/memoria.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turni").fetchone()[0], 1)

    def test_transform_without_submitted_and_repeated_prompt_new_turn(self):
        first = self.hook("userPromptTransformed", transformedPrompt="testo")
        self.hook("agentStop")
        second = self.hook("userPromptTransformed", transformedPrompt="testo")
        self.assertIn("Anna Rossi", second["modifiedTransformedPrompt"])
        self.assertNotEqual(first, second)
        with closing(sqlite3.connect(self.vault / ".graph/memoria.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(DISTINCT sessione) FROM turni").fetchone()[0], 2)

    def test_memory_successful_views_only_and_isolated_sessions(self):
        prompt = "dove recupero il responsabile delle pratiche urgenti?"
        self.hook("userPromptSubmitted", prompt=prompt)
        self.hook("userPromptSubmitted", prompt=prompt + " domani", sessionId="altra")
        read = {"toolName": "view", "toolArgs": json.dumps({"path": "wiki/Rilascio in produzione.md"}),
                "toolResult": {"resultType": "success", "textResultForLlm": "pagina"}}
        for override in ({"toolName": "grep"}, {"toolResult": {"resultType": "failure"}},
                         {"agentId": "figlio"}, {"toolArgs": {"path": "raw/Documento.md"}}):
            self.hook("postToolUse", **{**read, **override})
        with closing(sqlite3.connect(self.vault / ".graph/memoria.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM letture_turno").fetchone()[0], 0)
        self.hook("postToolUse", **read)
        self.hook("agentStop", sessionId="altra")
        self.hook("agentStop")
        self.hook("agentStop")
        self.hook("sessionEnd")
        self.hook("sessionEnd")
        with closing(sqlite3.connect(self.vault / ".graph/memoria.sqlite")) as db:
            self.assertEqual(db.execute("SELECT pagina FROM pagine_lette").fetchall(), [("Rilascio in produzione",)])
            self.assertEqual(db.execute("SELECT volte FROM domande").fetchall(), [(1,)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sospese").fetchone()[0], 0)
        state = self.vault / ".graph/copilot-sessioni" / (hashlib.sha256(b"test").hexdigest() + ".json")
        self.assertFalse(state.exists())

    def test_broken_recall_degrades_to_page_search(self):
        (self.vault / ".graph/recall_hook.py").write_text("raise RuntimeError('test')", encoding="utf-8")
        self.assertEqual(self.hook("userPromptSubmitted"), {})
        out = self.hook("userPromptTransformed", transformedPrompt="originale")
        self.assertTrue(out["modifiedTransformedPrompt"].startswith("originale\n\n"))
        self.assertIn("index.md", out["modifiedTransformedPrompt"])
        self.assertEqual(self.run_hook("copilot_hook.py", [], "postToolUse"), {})

    def run_timing(self, event, **fields):
        payload = {"sessionId": "test", "timestamp": 1792400000000, "cwd": str(self.vault),
                   "toolName": "sql", "toolArgs": {"query": "SELECT nome FROM persone"}, **fields}
        result = subprocess.run([sys.executable, "-B", str(self.vault / ".graph" / "copilot_timing_hook.py"), event],
                                input=json.dumps(payload).encode("utf-8"), cwd=self.vault,
                                capture_output=True, timeout=60,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return [json.loads(riga) for riga in result.stdout.decode("utf-8").splitlines() if riga.strip()]

    def test_timing_measures_logs_and_shows_progress(self):
        self.assertEqual(self.run_timing("preToolUse"), [{}])
        time.sleep(0.05)
        righe = self.run_timing("postToolUse", toolResult={
            "resultType": "success", "textResultForLlm": "id | nome\n1 | Anna Rossi"})
        self.assertEqual(righe[0]["type"], "progress")
        self.assertIn("⏱ sql", righe[0]["message"])
        self.assertIn("ms", righe[0]["message"])
        self.assertNotIn("ERRORE", righe[0]["message"])
        self.assertEqual(righe[1], {})
        log = self.vault / ".graph" / "timing.jsonl"
        voce = json.loads(log.read_text(encoding="utf-8").strip())
        self.assertEqual(voce["tool"], "sql")
        self.assertIsInstance(voce["ms"], int)
        self.assertGreaterEqual(voce["ms"], 0)
        self.assertTrue(voce["ok"])
        self.assertIn("Anna Rossi", voce["risultato"])
        self.assertIn("SELECT", voce["args"])
        self.assertFalse(list((self.vault / ".graph" / "timing-stato").glob("*.json")))

    def test_timing_failure_and_unknown_start(self):
        righe = self.run_timing("postToolUseFailure", error="query non valida")
        self.assertIn("ERRORE", righe[0]["message"])
        self.assertIn("ms n/d", righe[0]["message"])
        self.assertEqual(righe[1], {})
        righe = self.run_timing("postToolUse", toolResult={"resultType": "success", "textResultForLlm": "ok"})
        self.assertIn("ms n/d", righe[0]["message"])
        voci = [json.loads(riga) for riga in
                (self.vault / ".graph" / "timing.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(v["ok"], v["ms"]) for v in voci], [(False, None), (True, None)])
        self.assertEqual(voci[0]["errore"], "query non valida")

    def test_timing_never_blocks_tool_calls(self):
        for stdin in (b"", b"non json", b"[]"):
            with self.subTest(stdin=stdin):
                result = subprocess.run(
                    [sys.executable, "-B", str(self.vault / ".graph" / "copilot_timing_hook.py"), "preToolUse"],
                    input=stdin, cwd=self.vault, capture_output=True, timeout=60,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout.decode("utf-8").splitlines()[-1]), {})

    def test_claude_wrapper_skips_imported_copilot_and_forwards_claude(self):
        stub = "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n"
        (self.vault / ".graph/modello_hook.py").write_text(stub, encoding="utf-8")
        claude = {"hook_event_name": "UserPromptSubmit", "session_id": "claude", "prompt": "test",
                  "permission_mode": "default", "transcript_path": "session.jsonl"}
        self.assertEqual(self.run_hook("claude_hook.py", claude), claude)
        imported = {k: v for k, v in claude.items() if k != "permission_mode"}
        imported["timestamp"] = "2026-10-20T12:00:00Z"
        self.assertEqual(self.run_hook("claude_hook.py", imported), {})
        self.assertEqual(self.run_hook("claude_hook.py", {"sessionId": "copilot"}), {})

    def test_migrate_claude_hooks_preserve_foreign_and_domain(self):
        path = self.vault / ".claude/settings.json"
        local = self.vault / ".claude/settings.local.json"
        foreign = {"type": "command", "command": "echo utente"}
        legacy = {"type": "command", "command": "python .graph/modello_hook.py"}
        data = {"permissions": {"allow": ["Read"]}, "hooks": {
            "UserPromptSubmit": [{"hooks": [foreign, legacy]}]}}
        path.write_text(json.dumps(data), encoding="utf-8")
        local.write_text(json.dumps(data), encoding="utf-8")
        domain = self.vault / ".graph/modello_hook.py"
        before = domain.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installa.installa(self.vault, client="copilot", aggiorna=True, solo_integrazione=True), 0)
        self.assertEqual(before, domain.read_bytes())
        merged = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(foreign, merged["hooks"]["UserPromptSubmit"][0]["hooks"])
        self.assertNotIn("modello_hook.py", path.read_text(encoding="utf-8"))
        self.assertEqual(merged["permissions"], data["permissions"])
        clean_local = json.loads(local.read_text(encoding="utf-8"))
        self.assertEqual(clean_local["hooks"]["UserPromptSubmit"], [{"hooks": [foreign]}])
        first = path.read_bytes()
        self.assertTrue(installa.unisci_hook(self.vault, installa.Rapporto()))
        self.assertEqual(first, path.read_bytes())
        self.assertTrue(list(path.parent.glob("settings.json.bak-*")))
        self.assertTrue(list(path.parent.glob("settings.local.json.bak-*")))

    def test_copilot_user_skills_only_on_explicit_option(self):
        home = Path(self.temp.name) / "home"
        with mock.patch.object(Path, "home", return_value=home):
            installa.installa_skill("utente", self.vault, False, installa.Rapporto(), "copilot")
        self.assertEqual(len(list((home / ".copilot/skills").glob("*/SKILL.md"))), 5)

    def test_invalid_imported_claude_settings_fail_installation(self):
        for name in ("settings.json", "settings.local.json"):
            with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                path = self.vault / ".claude" / name
                before = path.read_bytes() if path.exists() else None
                path.write_text('{"hooks":[]}', encoding="utf-8")
                self.assertNotEqual(installa.installa(self.vault, client="copilot", solo_integrazione=True), 0)
                self.assertEqual(path.read_text(encoding="utf-8"), '{"hooks":[]}')
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)

    def test_existing_copilot_instructions_preserved_during_update(self):
        path = self.vault / ".github/copilot-instructions.md"
        path.write_text("istruzioni personali", encoding="utf-8")
        domain = [self.vault / ".graph/graph.sqlite", self.vault / ".graph/recall.py", self.vault / "Wiki reference.md"]
        before = {p: p.read_bytes() for p in domain}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installa.installa(self.vault, client="copilot", aggiorna=True, solo_integrazione=True), 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "istruzioni personali")
        self.assertEqual(before, {p: p.read_bytes() for p in domain})


if __name__ == "__main__":
    unittest.main()

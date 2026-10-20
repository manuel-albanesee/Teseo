"""Regressioni locali: nessun modello, servizio di rete o vault reale."""
import contextlib
from contextlib import closing
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installa", ROOT / "installa.py")
installa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installa)
NO_EVENT = object()


class Capture(io.StringIO):
    def reconfigure(self, **kwargs):
        pass


class CodexIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teseo test ")
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "Vault con spazi"
        with contextlib.redirect_stdout(io.StringIO()):
            code = installa.installa(self.vault, skill="vault", esempio=True, client="entrambi")
        self.assertEqual(code, 0)

    def script(self, name, *args, event=NO_EVENT, env=None):
        run = subprocess.run([sys.executable, str(self.vault / ".graph" / name), *args],
                             cwd=self.vault, capture_output=True,
                             input=json.dumps(event).encode("utf-8") if event is not NO_EVENT else None,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
        return run.stdout.decode("utf-8")

    def hook(self, event="UserPromptSubmit", **fields):
        return json.loads(self.script("codex_hook.py", event={
            "hook_event_name": event, "session_id": "test", "turn_id": "turno-1",
            "prompt": "chi è il referente del Rilascio in produzione?", "model": "gpt-6.1-sol", **fields,
        }))

    def test_installation_clients(self):
        for client in ("claude", "codex", "copilot", "entrambi", "tutti"):
            with self.subTest(client=client), contextlib.redirect_stdout(io.StringIO()):
                vault = Path(self.temp.name) / client
                self.assertEqual(installa.installa(vault, skill="vault", client=client), 0)
                selected = installa.clienti(client)
                self.assertEqual((vault / ".claude/settings.json").exists(), "claude" in selected)
                self.assertEqual((vault / ".codex/hooks.json").exists(), "codex" in selected)
                self.assertEqual((vault / "AGENTS.md").exists(), "codex" in selected)
                self.assertEqual((vault / ".github/hooks/teseo.json").exists(), "copilot" in selected)
                for name in ("obsidian-wiki-query", "obsidian-wiki-fill-gaps", "obsidian-wiki-lint", "obsidian-wiki-ingest"):
                    if "codex" in selected:
                        self.assertTrue((vault / ".agents/skills" / name / "SKILL.md").is_file())

    def test_merge_idempotent_and_preserves_other_hooks(self):
        path = self.vault / ".codex/hooks.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mio-hook"}]}
        data["hooks"]["PostToolUse"].insert(0, foreign)
        data["customMetadata"] = "preservare"
        path.write_text(json.dumps(data), encoding="utf-8")
        report = installa.Rapporto()
        installa.unisci_hook_codex(self.vault, report)
        first = path.read_bytes()
        installa.unisci_hook_codex(self.vault, report)
        self.assertEqual(path.read_bytes(), first)
        self.assertIn(foreign, json.loads(first)["hooks"]["PostToolUse"])
        self.assertEqual(json.loads(first)["customMetadata"], "preservare")
        self.assertNotIn("trust", json.loads(first))

    def test_malformed_hook_config_preserved(self):
        path = self.vault / ".codex/hooks.json"
        path.write_text("{non valido", encoding="utf-8")
        self.assertFalse(installa.unisci_hook_codex(self.vault, installa.Rapporto()))
        self.assertEqual(path.read_text(encoding="utf-8"), "{non valido")

    def test_invalid_hook_config_fails_installation(self):
        path = self.vault / ".codex/hooks.json"
        path.write_text("{non valido", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = installa.installa(self.vault, skill="vault", client="codex", solo_integrazione=True)
        self.assertNotEqual(code, 0, "non si può dichiarare riuscita un'installazione senza hook validi")
        self.assertEqual(path.read_text(encoding="utf-8"), "{non valido")

    def test_invalid_nested_hook_shape_is_preserved(self):
        path = self.vault / ".codex/hooks.json"
        for stop in ("errore", [None], [{"hooks": ["non un handler"]}]):
            with self.subTest(stop=stop):
                text = json.dumps({"hooks": {"Stop": stop}})
                path.write_text(text, encoding="utf-8")
                self.assertFalse(installa.unisci_hook_codex(self.vault, installa.Rapporto()))
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_non_object_event_still_returns_valid_json(self):
        for event in ([], None, "evento non valido"):
            with self.subTest(event=event):
                output = json.loads(self.script("codex_hook.py", event=event))
                self.assertIn("non riuscito", output["systemMessage"])

    def test_integration_does_not_touch_existing_domain_or_data(self):
        protected = [self.vault / ".graph/recall.py", self.vault / ".graph/graph.sqlite",
                     self.vault / "Wiki reference.md", self.vault / ".claude/settings.json"]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        config = self.vault / ".graph/codex.json"
        config.write_text('{"models":{"research":"mio-sol"}}', encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            installa.installa(self.vault, skill="vault", aggiorna=True, client="codex", solo_integrazione=True)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected})
        self.assertEqual(json.loads(config.read_text())["models"]["research"], "mio-sol")

    def test_skill_backup_outside_discovery(self):
        path = self.vault / ".agents/skills/obsidian-wiki-query/SKILL.md"
        path.write_text("skill personalizzata", encoding="utf-8")
        installa.installa_skill("vault", self.vault, True, installa.Rapporto(), "codex")
        self.assertIn("name: obsidian-wiki-query", path.read_text(encoding="utf-8"))
        self.assertEqual(len(list((self.vault / ".agents/skills").rglob("SKILL.md"))), 4)
        backups = list((self.vault / ".graph_backup").glob("*/skills/codex/obsidian-wiki-query/SKILL.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "skill personalizzata")

    def test_recall_and_roles(self):
        start = self.hook("SessionStart")
        self.assertIn("gpt-6-astra", start["hookSpecificOutput"]["additionalContext"])
        output = self.hook()
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("gpt-6-luna", context)
        self.assertIn("Anna Rossi", context)
        self.assertIn("leggi.py", context)
        self.assertNotIn("decision", output)
        self.assertNotIn("continue", output)

    def test_router_conservative_and_forced(self):
        cases = [("chi è il referente del Rilascio in produzione?", "gpt-6-luna"),
                 ("spiega come funziona RTC", "gpt-6.1-sol"),
                 ("@astra chi è il referente di RTC?", "gpt-6-astra"),
                 ("@sol chi è il referente di RTC?", "gpt-6.1-sol"),
                 ("modifica RTC", "gpt-6.1-sol"),
                 ("come funziona Codex?", "gpt-6.1-sol"),
                 ("chi gestisce un oggetto inesistente?", "gpt-6.1-sol")]
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                result = json.loads(self.script("chiedi_codex.py", "--piano", prompt))
                self.assertEqual(result["model"], expected)
        self.assertFalse((self.vault / ".graph/memoria.sqlite").exists())

    def test_memory_only_successful_reads_and_turn_isolation(self):
        prompt = "dove recupero il responsabile delle pratiche urgenti?"
        out = self.hook(prompt=prompt)
        import re
        token = re.search(r"--turno ([a-f0-9]{64})", out["hookSpecificOutput"]["additionalContext"])[1]
        self.script("leggi.py", "--turno", token, "wiki/Rilascio in produzione.md")
        # Bash che nomina un file non e' prova di lettura.
        self.hook("PostToolUse", tool_name="Bash", tool_input={"command": 'rg "Incident" wiki/'}, tool_response="Incident settimanale.md")
        # Un secondo turno della stessa sessione resta distinto.
        self.hook(turn_id="turno-2", prompt="dove recupero il responsabile delle pratiche urgenti domani?")
        self.hook("Stop", turn_id="turno-2")
        self.hook("Stop")
        self.hook("Stop")  # ripetere Stop non duplica apprendimento
        with closing(sqlite3.connect(self.vault / ".graph/memoria.sqlite")) as db:
            pages = db.execute("SELECT pagina FROM pagine_lette").fetchall()
            self.assertEqual(pages, [("Rilascio in produzione",)])
            self.assertEqual(db.execute("SELECT volte FROM domande").fetchall(), [(1,)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sospese").fetchone()[0], 0)

    def test_structured_read_and_subagent_do_not_mix(self):
        self.hook(prompt="dove recupero il responsabile delle pratiche urgenti?")
        self.hook("PostToolUse", tool_name="mcp__fs__read_file", tool_input={"path": "wiki/RTC.md"},
                  tool_response={"isError": True})
        self.hook("PostToolUse", tool_name="Read", tool_input={"file_path": "wiki/Incident settimanale.md"},
                  tool_response="testo", agent_id="subagent")
        self.hook("PostToolUse", tool_name="mcp__fs__read_file", tool_input={"path": "wiki/Rilascio in produzione.md"},
                  tool_response={"content": [{"type": "text", "text": "testo"}]})
        self.assertEqual(self.hook("Stop"), {})
        with closing(sqlite3.connect(self.vault / ".graph/memoria.sqlite")) as db:
            self.assertEqual(db.execute("SELECT pagina FROM pagine_lette").fetchall(), [("Rilascio in produzione",)])

    def test_fault_returns_valid_advisory_json(self):
        (self.vault / ".graph/recall_hook.py").write_text("raise RuntimeError('guasto simulato')", encoding="utf-8")
        output = self.hook()
        self.assertIn("non riuscito", output["systemMessage"])
        self.assertIn("index", output["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("decision", output)

    def test_child_guard(self):
        result = json.loads(self.script("codex_hook.py", event={"hook_event_name": "SessionStart"},
                                       env={"TESEO_CODEX_CHILD": "1"}))
        self.assertEqual(result, {})

    def test_reader_rejects_raw_and_outside(self):
        run = subprocess.run([sys.executable, str(self.vault / ".graph/leggi.py"), "../raw/fonte.md"],
                             cwd=self.vault, capture_output=True)
        self.assertNotEqual(run.returncode, 0)


class DefaultInstallation(unittest.TestCase):
    def check_vault_configuration(self, vault, home):
        for name in (".claude/settings.json", ".codex/hooks.json", "CLAUDE.md", "AGENTS.md", ".graph/codex.json",
                     ".github/hooks/teseo.json", ".github/copilot-instructions.md"):
            self.assertTrue((vault / name).is_file(), f"Configurazione locale mancante: {name}")
        for client_dir in (".claude", ".agents", ".github"):
            for skill in ("ingest", "query", "lint", "fill-gaps"):
                self.assertTrue((vault / client_dir / "skills" / f"obsidian-wiki-{skill}" / "SKILL.md").is_file())
            self.assertFalse((home / client_dir).exists(), "L'installazione predefinita deve restare nel vault")
        self.assertFalse((home / ".copilot").exists())

    def test_default_python_installation_is_local_for_all_clients(self):
        with tempfile.TemporaryDirectory(prefix="teseo default ") as temp:
            root = Path(temp)
            home = root / "utente"
            home.mkdir()
            vault = root / "vault"
            with mock.patch.object(Path, "home", return_value=home), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(installa.installa(vault), 0)
            self.check_vault_configuration(vault, home)

    def test_default_cli_installation_is_local_for_all_clients(self):
        with tempfile.TemporaryDirectory(prefix="teseo cli default ") as temp:
            root = Path(temp)
            home = root / "utente"
            home.mkdir()
            vault = root / "vault"
            result = subprocess.run([sys.executable, "-B", str(ROOT / "installa.py"), str(vault)],
                                    cwd=ROOT, capture_output=True, timeout=60,
                                    env={**os.environ, "USERPROFILE": str(home), "HOME": str(home),
                                         "PYTHONIOENCODING": "utf-8"})
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            self.check_vault_configuration(vault, home)


class QueryRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "kit/graph"))
        import chiedi_codex
        cls.runner = chiedi_codex

    def test_exec_contract_and_child_guard(self):
        def fake_run(argv, **kwargs):
            self.assertIn("--model", argv)
            self.assertEqual(argv[argv.index("--model") + 1], "gpt-6-luna")
            self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
            self.assertIn("features.hooks=false", argv)
            self.assertIn("--ephemeral", argv)
            self.assertNotIn("--dangerously-bypass-hook-trust", argv)
            self.assertEqual(kwargs["env"]["TESEO_CODEX_CHILD"], "1")
            self.assertIsInstance(kwargs["input"], bytes)
            Path(argv[argv.index("--output-last-message") + 1]).write_text("risposta con citazioni", encoding="utf-8")
            return SimpleNamespace(returncode=0, stderr=b"")
        with mock.patch.object(self.runner.subprocess, "run", side_effect=fake_run):
            answer = self.runner.esegui("codex", "gpt-6-luna", "domanda", "contesto")
        self.assertEqual(answer, "risposta con citazioni")

    def run_main(self, answers):
        with mock.patch.object(sys, "argv", ["chiedi_codex.py", "domanda"]), \
             mock.patch.object(self.runner, "contesto", return_value={"hookSpecificOutput": {"additionalContext": "fatti"}}), \
             mock.patch.object(self.runner, "instrada", return_value=("gpt-6-luna", "puntuale")), \
             mock.patch.object(self.runner.shutil, "which", return_value="codex"), \
             mock.patch.object(self.runner, "gestisci") as stop, \
             mock.patch.object(self.runner, "esegui", side_effect=answers) as run, \
             contextlib.redirect_stdout(Capture()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = self.runner.main()
        self.assertEqual(stop.call_count, 1)
        return code, run, output.getvalue()

    def test_luna_escalation_is_bounded(self):
        for first in (self.runner.PASSA, RuntimeError("modello non disponibile")):
            with self.subTest(first=type(first).__name__):
                code, run, output = self.run_main([first, "risposta di ricerca"])
                self.assertEqual(code, 0)
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args_list[1].args[1], "gpt-6.1-sol")
                self.assertIn("risposta di ricerca", output)

    def test_research_failure_is_reported(self):
        code, run, output = self.run_main([self.runner.PASSA, RuntimeError("errore ricerca")])
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("risposta di ricerca", output)


if __name__ == "__main__":
    unittest.main()

"""Installa il kit Teseo in un vault Obsidian, nuovo o già in uso, senza toccare le pagine.

Cosa fa:
  - .graph/          copia gli script; uno script già presente e diverso dal kit si lascia com'è,
                     salvo --aggiorna (copia di sicurezza in .graph_backup/<data-ora>/, poi sostituito).
                     I database .sqlite e modello.json non si toccano mai.
  - --client claude|codex|copilot|entrambi|tutti (predefinito tutti).
  - .claude/settings.json   aggiunge i 4 hook a quelli che ci sono già (copia di sicurezza settings.json.bak-<data-ora>);
                     un hook già registrato (stesso script) non si duplica.
  - .codex/hooks.json       hook nativi Codex (non autorizzati automaticamente), AGENTS.md e ruoli Sol/Astra/Luna.
  - .github/               istruzioni, skill e hook nativi Copilot CLI, locali al vault.
  - Wiki reference.md, index.md, log.md, CLAUDE.md/AGENTS.md, raw/, wiki/   solo se mancano.
  - skill            .claude/skills per Claude, .agents/skills per Codex, .github/skills per Copilot; nel vault per default,
                     utente solo con --skill utente;
                     una skill già presente e diversa si lascia, salvo --aggiorna.
Alla fine controlla PyYAML e FTS5, lancia build_graph.py --check e, su un vault già in uso, dice cosa adattare
(.graph/ADATTA.md, copiato insieme agli script).

Uso:
  python installa.py <vault> [--client claude|codex|copilot|entrambi|tutti] [--skill utente|vault|no] [--aggiorna] [--esempio]
  python installa.py <vault> --client codex --skill vault --solo-integrazione
  python installa.py --prova        installa in una cartella temporanea con il vault d'esempio, verifica e cancella
"""
import argparse
import filecmp
import json
import os
import shutil
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

KIT = Path(__file__).resolve().parent / "kit"
SCHEMA = ["Wiki reference.md", "index.md", "log.md", "CLAUDE.md"]
CODEX_SCRIPT = {"codex_hook.py", "chiedi_codex.py", "leggi.py"}
COPILOT_SCRIPT = {"copilot_hook.py"}
CLAUDE_SCRIPT = {"claude_hook.py"}
CLAUDE_HANDLER = ("modello_hook.py", "learn_hook.py", "claude_hook.py")
FACOLTATIVI = {"banco.py", "candidati.py"}
DOMINIO = ("misura.py (DOMANDE, ATTESE, ROUTING, NEGATIVI, TESTO, ATTESI_FALLITI, MEMORIA), recall.py e build_graph.py "
           "(PAROLE_COMUNI, PAROLE_COMUNI_NOMI, NON_RELAZIONI), domande.py (NON_TERMINI, CON_REFERENTE)")


def adesso():
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


class Rapporto:
    def __init__(self):
        self.righe, self.avvisi = [], []

    def __call__(self, cosa, esito):
        self.righe.append((cosa, esito))

    def avviso(self, testo):
        self.avvisi.append(testo)

    def stampa(self):
        larghezza = max((len(c) for c, _ in self.righe), default=0)
        for cosa, esito in self.righe:
            print(f"  {cosa:<{larghezza}}  {esito}")
        for a in self.avvisi:
            print(f"  ⚠️ {a}")


def copia_file(sorgente, dest, aggiorna, backup_dir, rapporto, nome):
    """Copia sorgente in dest. Uguale: niente; diverso: lasciato, o con --aggiorna salvato in backup_dir e sostituito."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sorgente, dest)
        rapporto(nome, "installato")
        return "nuovo"
    if filecmp.cmp(sorgente, dest, shallow=False):
        rapporto(nome, "già aggiornato")
        return "uguale"
    if not aggiorna:
        rapporto(nome, "diverso dal kit: lasciato (--aggiorna per sostituirlo)")
        return "diverso"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dest, backup_dir / dest.name)
    shutil.copyfile(sorgente, dest)
    rapporto(nome, f"aggiornato (il precedente è in {backup_dir.name}/)")
    return "aggiornato"


def unisci_hook(vault, rapporto):
    """Migra solo gli handler Teseo: Copilot importa anche le impostazioni Claude."""
    kit = json.loads((KIT / "vault" / "settings.json").read_text(encoding="utf-8"))
    argv = [Path(sys.executable).as_posix(), (vault / ".graph" / "claude_hook.py").as_posix()]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    for gruppi in kit["hooks"].values():
        for g in gruppi:
            for h in g["hooks"]:
                h["command"] = command
    path = vault / ".claude" / "settings.json"
    try:
        attuale = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        if not isinstance(attuale, dict) or not isinstance(attuale.get("hooks", {}), dict):
            raise ValueError("hooks deve essere un oggetto JSON")
        for evento in kit["hooks"]:
            gruppi = attuale.get("hooks", {}).get(evento, [])
            if not isinstance(gruppi, list):
                raise ValueError(f"hooks.{evento} deve essere una lista")
            for gruppo in gruppi:
                if not isinstance(gruppo, dict) or not isinstance(gruppo.get("hooks"), list):
                    raise ValueError(f"gruppo hooks.{evento} non valido")
                if any(not isinstance(h, dict) or not isinstance(h.get("command", ""), str)
                       for h in gruppo["hooks"]):
                    raise ValueError(f"handler hooks.{evento} non valido")
    except ValueError as e:
        rapporto.avviso(f".claude/settings.json non valido ({e}): lasciato invariato")
        return False
    prima = json.dumps(attuale, ensure_ascii=False, sort_keys=True)
    hooks = attuale.setdefault("hooks", {})
    for evento, gruppi in kit["hooks"].items():
        nuovi = []
        for gruppo in hooks.get(evento, []):
            altri = [h for h in gruppo["hooks"] if not any(
                script in h.get("command", "") for script in CLAUDE_HANDLER)]
            if altri:
                nuovi.append({**gruppo, "hooks": altri})
        hooks[evento] = nuovi + gruppi
    if prima == json.dumps(attuale, ensure_ascii=False, sort_keys=True):
        rapporto(".claude/settings.json", "hook già registrati")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copyfile(path, path.with_name(f"settings.json.bak-{adesso()}"))
    path.write_text(json.dumps(attuale, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rapporto(".claude/settings.json", "registrati 4 hook con adattatore Claude/Copilot")
    return True


def clienti(client):
    if client == "tutti":
        return ("claude", "codex", "copilot")
    return ("claude", "codex") if client == "entrambi" else (client,)


def ripulisci_hook_claude_locali(vault, rapporto):
    """Gli handler Teseo sono già nel file condiviso; conserva quelli dell'utente."""
    path = vault / ".claude/settings.local.json"
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
            raise ValueError("hooks deve essere un oggetto JSON")
        prima = json.dumps(data, sort_keys=True)
        for evento, gruppi in data.get("hooks", {}).items():
            if not isinstance(gruppi, list):
                raise ValueError(f"hooks.{evento} deve essere una lista")
            nuovi = []
            for gruppo in gruppi:
                if not isinstance(gruppo, dict) or not isinstance(gruppo.get("hooks"), list):
                    raise ValueError(f"gruppo hooks.{evento} non valido")
                if any(not isinstance(h, dict) or not isinstance(h.get("command", ""), str) for h in gruppo["hooks"]):
                    raise ValueError(f"handler hooks.{evento} non valido")
                altri = [h for h in gruppo["hooks"] if not any(s in h.get("command", "") for s in CLAUDE_HANDLER)]
                if altri:
                    nuovi.append({**gruppo, "hooks": altri})
            data["hooks"][evento] = nuovi
    except ValueError as error:
        rapporto.avviso(f".claude/settings.local.json non valido ({error}): lasciato invariato")
        return False
    if prima != json.dumps(data, sort_keys=True):
        shutil.copyfile(path, path.with_name(f"settings.local.json.bak-{adesso()}"))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rapporto(".claude/settings.local.json", "rimossi doppioni Teseo; hook utente conservati")
    return True


def unisci_hook_copilot(vault, rapporto):
    """Configurazione nativa Copilot CLI v1; nessuna modifica al consenso utente."""
    path = vault / ".github" / "hooks" / "teseo.json"
    eventi = {"sessionStart": 15, "userPromptSubmitted": 45, "userPromptTransformed": 45,
              "postToolUse": 10, "agentStop": 10, "sessionEnd": 10}
    try:
        attuale = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {"version": 1}
        if not isinstance(attuale, dict) or attuale.get("version") != 1:
            raise ValueError("version deve essere 1")
        if not isinstance(attuale.get("hooks", {}), dict):
            raise ValueError("hooks deve essere un oggetto JSON")
        for evento in eventi:
            handlers = attuale.get("hooks", {}).get(evento, [])
            if not isinstance(handlers, list) or any(not isinstance(h, dict) for h in handlers):
                raise ValueError(f"hooks.{evento} deve essere una lista di handler")
    except ValueError as error:
        rapporto.avviso(f".github/hooks/teseo.json non valido ({error}): lasciato invariato")
        return False
    prima = json.dumps(attuale, ensure_ascii=False, sort_keys=True)
    hooks = attuale.setdefault("hooks", {})
    script = str(vault / ".graph" / "copilot_hook.py")
    for evento, timeout in eventi.items():
        altri = [h for h in hooks.get(evento, []) if "copilot_hook.py" not in json.dumps(h)]
        hooks[evento] = altri + [{"type": "command", "exec": sys.executable,
                                 "args": [script, evento], "cwd": str(vault), "timeoutSec": timeout}]
    if prima == json.dumps(attuale, ensure_ascii=False, sort_keys=True):
        rapporto(".github/hooks/teseo.json", "hook già registrati")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copyfile(path, path.with_name(f"teseo.json.bak-{adesso()}"))
    path.write_text(json.dumps(attuale, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rapporto(".github/hooks/teseo.json", "registrati 6 hook nativi Copilot CLI")
    return True


def unisci_hook_codex(vault, rapporto):
    """File nativo Codex; conserva gli hook estranei e richiede trust normale."""
    path = vault / ".codex" / "hooks.json"
    try:
        attuale = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        if not isinstance(attuale, dict) or not isinstance(attuale.get("hooks", {}), dict):
            raise ValueError("hooks deve essere un oggetto JSON")
        for evento in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
            gruppi = attuale.get("hooks", {}).get(evento, [])
            if not isinstance(gruppi, list):
                raise ValueError(f"hooks.{evento} deve essere una lista")
            for gruppo in gruppi:
                if not isinstance(gruppo, dict) or not isinstance(gruppo.get("hooks"), list):
                    raise ValueError(f"gruppo hooks.{evento} non valido")
                if any(not isinstance(h, dict) or not isinstance(h.get("command", ""), str)
                       for h in gruppo["hooks"]):
                    raise ValueError(f"handler hooks.{evento} non valido")
    except ValueError as error:
        rapporto.avviso(f".codex/hooks.json non valido ({error}): lasciato invariato")
        return False
    prima = json.dumps(attuale, ensure_ascii=False, sort_keys=True)
    hooks = attuale.setdefault("hooks", {})
    argv = [sys.executable, str(vault / ".graph" / "codex_hook.py")]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    for evento, timeout in (("SessionStart", 15), ("UserPromptSubmit", 45), ("PostToolUse", 10), ("Stop", 10)):
        gruppi = hooks.setdefault(evento, [])
        nuovi = []
        for gruppo in gruppi:
            altri = [h for h in gruppo.get("hooks", []) if "codex_hook.py" not in h.get("command", "")]
            if altri:
                nuovi.append({**gruppo, "hooks": altri})
        handler = {"type": "command", "command": command, "timeout": timeout}
        if evento in ("SessionStart", "UserPromptSubmit"):
            handler["additionalContextLimit"] = 5000
        gruppo = {"hooks": [handler]}
        if evento == "PostToolUse":
            gruppo["matcher"] = "(^Read$|(^|__)(read_file|read_text_file)$)"
        nuovi.append(gruppo)
        hooks[evento] = nuovi
    if prima == json.dumps(attuale, ensure_ascii=False, sort_keys=True):
        rapporto(".codex/hooks.json", "hook già registrati")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"hooks.json.bak-{adesso()}")
        shutil.copyfile(path, backup)
    path.write_text(json.dumps(attuale, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rapporto(".codex/hooks.json", "registrati recall, memoria e avvio (review/trust richiesti da Codex)")
    return True


def installa_skill(modo, vault, aggiorna, rapporto, client="claude"):
    if modo == "no":
        rapporto("skill", "non installate (--skill no)")
        return
    cartella_client = {"claude": ".claude", "codex": ".agents",
                       "copilot": ".copilot" if modo == "utente" else ".github"}[client]
    radice = (Path.home() if modo == "utente" else vault) / cartella_client / "skills"
    for cartella in sorted((KIT / "skills").iterdir()):
        dest = radice / cartella.name / "SKILL.md"
        backup = vault / ".graph_backup" / adesso() / "skills" / client / cartella.name
        copia_file(cartella / "SKILL.md", dest, aggiorna, backup, rapporto,
                   f"skill {cartella.name} ({client}, {modo})")


def copia_esempio(vault, rapporto):
    if any((vault / "wiki").glob("*.md")):
        rapporto.avviso("--esempio ignorato: wiki/ contiene già pagine")
        return
    for f in (KIT / "esempio" / "wiki").glob("*.md"):
        shutil.copyfile(f, vault / "wiki" / f.name)
    for f in (KIT / "esempio" / "raw").glob("*.md"):
        shutil.copyfile(f, vault / "raw" / f.name)
    shutil.copyfile(KIT / "esempio" / "banco.json", vault / ".graph" / "banco.json")
    indice = (vault / "index.md").read_text(encoding="utf-8")
    esempio = (KIT / "esempio" / "index-esempio.md").read_text(encoding="utf-8")
    pagine, punti = esempio.split("## Punti aperti nel vault")
    indice = indice.replace("## Pagine\n\n| Pagina | Descrizione |\n| --- | --- |\n", pagine, 1)
    indice = indice.split("## Punti aperti nel vault")[0] + "## Punti aperti nel vault" + punti
    (vault / "index.md").write_text(indice, encoding="utf-8")
    rapporto("vault d'esempio", "8 pagine, 2 fonti, banco.json, righe dell'indice")


def controlla_ambiente(rapporto, client="claude"):
    try:
        import yaml  # noqa: F401
        rapporto("PyYAML", "presente")
    except ImportError:
        rapporto.avviso(f"PyYAML manca: {sys.executable} -m pip install pyyaml")
    try:
        db = sqlite3.connect(":memory:")
        try:
            db.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        finally:
            db.close()
        rapporto("SQLite FTS5", "presente")
    except sqlite3.Error:
        rapporto.avviso("SQLite di questo Python non ha FTS5: il ripiego sul testo non funzionerà")
    if "claude" in clienti(client) and not shutil.which("claude"):
        rapporto.avviso("eseguibile claude non nel PATH: il routing verso Haiku non partirà (risponde il modello della sessione)")
    if "codex" in clienti(client) and not shutil.which("codex"):
        rapporto.avviso("Codex CLI non nel PATH: gli hook/skill nell'app restano utilizzabili, "
                        "ma chiedi_codex.py richiede la CLI autenticata")
    if "copilot" in clienti(client) and not shutil.which("copilot"):
        rapporto.avviso("Copilot CLI non nel PATH: configurazione locale preparata, installare/autenticare la CLI per usarla")


def controlla_vault(vault, rapporto):
    """Cosa manca a un vault già in uso perché il grafo lo veda bene. Solo lettura."""
    nascoste = {".graph", ".claude", ".codex", ".agents", ".github", ".obsidian", ".git", ".trash", ".graph_backup", ".teseo"}
    fuori = [p for p in vault.rglob("*.md")
             if not set(p.relative_to(vault).parts) & nascoste
             and p.relative_to(vault).parts[0] not in ("wiki", "raw")
             and p.relative_to(vault).as_posix() not in [*SCHEMA, "AGENTS.md"]]
    sotto = [p for p in (vault / "wiki").rglob("*.md") if p.parent != vault / "wiki"]
    if fuori:
        rapporto.avviso(f"{len(fuori)} pagine fuori da wiki/ e raw/ (es. {fuori[0].relative_to(vault).as_posix()}): "
                        "il grafo non le vede. Vedi .graph/ADATTA.md, passo 2")
    if sotto:
        rapporto.avviso(f"{len(sotto)} pagine in sottocartelle di wiki/ (es. {sotto[0].relative_to(vault).as_posix()}): "
                        "il grafo legge solo wiki/*.md. Vedi .graph/ADATTA.md, passo 2")
    ref = vault / "Wiki reference.md"
    testo = ref.read_text(encoding="utf-8") if ref.exists() else ""
    if "## Relazioni tipizzate" not in testo:
        rapporto.avviso("Wiki reference.md senza «## Relazioni tipizzate»: nessun controllo sulle relazioni. "
                        "Vedi .graph/ADATTA.md, passo 3")
    indice = vault / "index.md"
    if indice.exists() and "## Punti aperti nel vault" not in indice.read_text(encoding="utf-8"):
        rapporto.avviso("index.md senza «## Punti aperti nel vault»: le domande aperte di tipo «punto» non si calcolano")


def esegui(vault, *argomenti):
    p = subprocess.run([sys.executable, *argomenti], cwd=vault, capture_output=True,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return p.returncode, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")


def installa(vault, skill="vault", aggiorna=False, esempio=False, client="tutti", solo_integrazione=False,
             dashboard=False):
    vault = vault.resolve()
    if dashboard:
        from kit.dashboard.contracts import inspect_vault
        if solo_integrazione:
            raise ValueError("--dashboard richiede installazione completa")
        if vault.exists() and any(vault.iterdir()) and inspect_vault(vault).mode != "compatible":
            raise ValueError("--dashboard inizializza solo cartelle vuote; nessuna adozione automatica dei legacy")
    if solo_integrazione and not (vault / ".graph" / "recall_hook.py").is_file():
        raise ValueError("--solo-integrazione richiede un vault con Teseo già installato")
    gia_in_uso = vault.exists() and any(vault.rglob("*.md"))
    rapporto = Rapporto()
    print(f"Teseo → {vault}  ({'vault già in uso' if gia_in_uso else 'vault nuovo'})")
    for cartella in ((".graph",) if solo_integrazione else ("raw", "wiki", ".graph")):
        (vault / cartella).mkdir(parents=True, exist_ok=True)

    backup = vault / ".graph_backup" / adesso()
    diversi = []
    selezionati = clienti(client)
    migra_claude = "claude" in selezionati or ("copilot" in selezionati and any(
        (vault / ".claude" / name).exists() for name in ("settings.json", "settings.local.json")))
    adattatori = set()
    if "codex" in selezionati:
        adattatori.update(CODEX_SCRIPT)
    if "copilot" in selezionati:
        adattatori.update(COPILOT_SCRIPT)
    if migra_claude:
        adattatori.update(CLAUDE_SCRIPT)
    sorgenti = sorted((KIT / "graph").glob("*.py"))
    sorgenti = [f for f in sorgenti if f.name not in CODEX_SCRIPT | COPILOT_SCRIPT | CLAUDE_SCRIPT or f.name in adattatori]
    if solo_integrazione:
        sorgenti = [f for f in sorgenti if f.name in adattatori]
    else:
        sorgenti += [KIT / "vault" / "requirements.txt", KIT.parent / "ADATTA.md"]
    for f in sorgenti:
        nome = f".graph/{f.name}" + (" (facoltativo)" if f.name in FACOLTATIVI else "")
        if copia_file(f, vault / ".graph" / f.name, aggiorna, backup, rapporto, nome) == "diverso":
            diversi.append(f.name)
    if not solo_integrazione:
        for f in sorted((KIT / "dashboard").glob("*.py")):
            nome = f".graph/dashboard/{f.name}"
            if copia_file(f, vault / ".graph/dashboard" / f.name, aggiorna,
                          backup / "dashboard", rapporto, nome) == "diverso":
                diversi.append(nome)
        for skill_name in ('obsidian-wiki-ingest', 'obsidian-wiki-lint'):
            source = KIT / 'skills' / skill_name / 'SKILL.md'
            name = f'.graph/dashboard_skill_docs/{skill_name}.md'
            if copia_file(source, vault / name, aggiorna, backup / 'dashboard_skill_docs', rapporto, name) == 'diverso':
                diversi.append(name)
    if aggiorna and backup.exists() and not solo_integrazione:
        rapporto.avviso(f"script sostituiti: riportare a mano i dati di dominio dal backup "
                        f"({backup.relative_to(vault).as_posix()}): {DOMINIO}")
    schema = [] if solo_integrazione else [n for n in SCHEMA if n != "CLAUDE.md"]
    schema += ["CLAUDE.md"] if "claude" in clienti(client) else []
    schema += ["AGENTS.md"] if "codex" in clienti(client) else []
    for nome in schema:
        dest = vault / nome
        if dest.exists():
            rapporto(nome, "già presente, non toccato")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(KIT / "vault" / nome, dest)
            rapporto(nome, "creato dal modello del kit")
    hook_ok = True
    if migra_claude:
        hook_ok = unisci_hook(vault, rapporto) and hook_ok
        if hook_ok and "copilot" in selezionati:
            hook_ok = ripulisci_hook_claude_locali(vault, rapporto) and hook_ok
    if "codex" in clienti(client):
        hook_ok = unisci_hook_codex(vault, rapporto) and hook_ok
        if not (vault / ".graph" / "codex.json").exists():
            shutil.copyfile(KIT / "graph" / "codex.json", vault / ".graph" / "codex.json")
            rapporto(".graph/codex.json", "ruoli Sol/Astra/Luna creati")
    if "copilot" in selezionati:
        hook_ok = unisci_hook_copilot(vault, rapporto) and hook_ok
        dest = vault / ".github/copilot-instructions.md"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(KIT / "vault/copilot-instructions.md", dest)
            rapporto(".github/copilot-instructions.md", "creato dal modello del kit")
        else:
            rapporto(".github/copilot-instructions.md", "già presente, non toccato")
    for selezionato in clienti(client):
        installa_skill(skill, vault, aggiorna, rapporto, selezionato)
    if esempio:
        copia_esempio(vault, rapporto)
    if dashboard and not (vault / ".teseo/project.json").exists():
        from kit.dashboard.contracts import canonical_json, DEFAULT_SHARED_PATHS, KIT_VERSION
        directory = vault / ".teseo"
        directory.mkdir(exist_ok=True)
        with (directory / "project.json").open("xb") as stream:
            stream.write(canonical_json({"format_version": 1, "schema_version": 1,
                "event_version": 1, "minimum_kit_version": KIT_VERSION,
                "vault_id": str(uuid4()), "shared_paths": list(DEFAULT_SHARED_PATHS)}))
        rapporto(".teseo/project.json", "nuovo vault dashboard v1; nessuna migrazione")
    controlla_ambiente(rapporto, client)
    if gia_in_uso and not solo_integrazione:
        controlla_vault(vault, rapporto)
    rapporto.stampa()

    if not hook_ok:
        print("\nIntegrazione incompleta: correggere i file hook segnalati e rilanciare l'installazione.")
        return 1

    if "codex" in clienti(client):
        print("\nCodex: riaprire il vault e revisionare/autorizzare gli hook con /hooks nella CLI "
              "o nel controllo hook dell'app, se disponibile. Il progetto deve essere trusted. "
              "L'installatore non modifica il trust né il modello attivo.")
    if solo_integrazione:
        print("\nIntegrazione completata: pagine, script di dominio e database esistenti non aggiornati.")
        return 0

    codice, uscita = esegui(vault, ".graph/build_graph.py", "--check")
    righe = uscita.strip().splitlines()
    print("\npython .graph/build_graph.py --check")
    problemi = [r for r in righe if r.strip().startswith("⚠️")]
    for r in ([righe[0], *problemi[:15]] if righe else []):
        print(f"  {r.strip()}")
    if len(problemi) > 15:
        print(f"  … e altri {len(problemi) - 15}")
    print(f"  {righe[-1].strip() if righe else 'nessun output'}")
    print('\nDashboard locale: python .graph/teseo_dashboard.py --vault "' + str(vault) + '"')
    if not (vault / ".teseo/project.json").exists():
        print("Vault legacy: dashboard in sola lettura, rebuild via servizio disabilitato.")
    if diversi:
        print(f"\nScript diversi dal kit, lasciati come sono: {', '.join(diversi)}. "
              "Per aggiornarli: python installa.py <vault> --aggiorna")
    print("\nPoi: riaprire il client selezionato nella cartella del vault (gli hook valgono dalla sessione successiva)."
          + ("\nVault già in uso: seguire .graph/ADATTA.md per far vedere le pagine al grafo. Si può chiedere a Claude:"
             "\n  «Adatta questo vault al kit Teseo seguendo .graph/ADATTA.md, un passo alla volta, chiedendomi"
             " conferma prima di spostare o rinominare file.»" if gia_in_uso else ""))
    return codice


def prova(client="tutti", dashboard=False):
    """Installazione di prova con il vault d'esempio in una cartella temporanea: niente esce da lì."""
    cartella = Path(tempfile.mkdtemp(prefix="teseo-prova-"))
    try:
        if installa(cartella, skill="vault", esempio=True, client=client, dashboard=dashboard):
            return 1
        print("\n=== verifica")
        controlli = [
            ("build_graph --check", [".graph/build_graph.py", "--check"], "nessun problema"),
            ("recall a catena", [".graph/recall.py", "devo fare un rilascio in produzione: cosa mi serve e chi me lo dà?"],
             "Incident settimanale → referente → Anna Rossi"),
            ("misura", [".graph/misura.py"], "pagine attese portate dal recall: 12/12"),
            ("misura --routing", [".graph/misura.py", "--routing"], " OK"),
            ("sintesi --verifica", [".graph/sintesi.py", "--verifica"], "nessun problema"),
            ("banco --verifica", [".graph/banco.py", "--verifica"], "nessun problema"),
        ]
        falliti = 0
        for nome, argomenti, atteso in controlli:
            codice, uscita = esegui(cartella, *argomenti)
            ok = codice == 0 and atteso in uscita
            falliti += not ok
            ultima = uscita.strip().splitlines()[-1] if uscita.strip() else ""
            print(f"  {'OK' if ok else 'KO'}  {nome:<22} {ultima[:90]}")
        evento = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "come faccio il rilascio in produzione?",
                             "session_id": "prova"})
        p = subprocess.run([sys.executable, ".graph/recall_hook.py"], cwd=cartella, input=evento.encode("utf-8"),
                           capture_output=True)
        messaggio = json.loads(p.stdout.decode("utf-8") or "{}").get("systemMessage", "")
        ok = "fatti da Rilascio in produzione" in messaggio
        falliti += not ok
        print(f"  {'OK' if ok else 'KO'}  {'hook del recall':<22} {messaggio[:90]}")
        print(f"\n{'tutto OK' if not falliti else f'{falliti} controlli falliti'} · cartella di prova cancellata")
        return 1 if falliti else 0
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vault", nargs="?", type=Path, help="cartella del vault (creata se non esiste)")
    ap.add_argument("--skill", choices=("utente", "vault", "no"), default="vault",
                    help="skill nel vault per default: .claude/skills, .agents/skills, .github/skills; "
                         "utente per l'installazione globale, no per saltarle")
    ap.add_argument("--client", choices=("claude", "codex", "copilot", "entrambi", "tutti"), default="tutti",
                    help="client da configurare (predefinito: tutti, nel vault; entrambi = Claude e Codex)")
    ap.add_argument("--solo-integrazione", action="store_true",
                    help="aggiunge il supporto client a Teseo già installato, senza aggiornare grafo o pagine")
    ap.add_argument("--aggiorna", action="store_true", help="sostituisce script e skill diversi dal kit, con copia di sicurezza")
    ap.add_argument("--dashboard", action="store_true", help="inizializza formato dashboard solo per un vault nuovo; non adotta legacy")
    ap.add_argument("--esempio", action="store_true", help="aggiunge il vault d'esempio (solo se wiki/ è vuota)")
    ap.add_argument("--prova", action="store_true", help="prova completa in una cartella temporanea, poi la cancella")
    args = ap.parse_args()
    if sys.version_info < (3, 10):
        ap.error("Teseo richiede Python 3.10 o successivo")
    if args.prova:
        sys.exit(prova(args.client, args.dashboard))
    if not args.vault:
        ap.error("indicare la cartella del vault, oppure --prova")
    if args.solo_integrazione and args.esempio:
        ap.error("--solo-integrazione non è compatibile con --esempio")
    try:
        result = installa(args.vault, args.skill, args.aggiorna, args.esempio, args.client, args.solo_integrazione,
                         args.dashboard)
    except ValueError as error:
        ap.error(str(error))
    sys.exit(result)


if __name__ == "__main__":
    main()

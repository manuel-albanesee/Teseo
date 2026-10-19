"""Installa il kit Teseo in un vault Obsidian, nuovo o già in uso, senza toccare le pagine.

Cosa fa:
  - .graph/          copia gli script; uno script già presente e diverso dal kit si lascia com'è,
                     salvo --aggiorna (copia di sicurezza in .graph_backup/<data-ora>/, poi sostituito).
                     I database .sqlite e modello.json non si toccano mai.
  - .claude/settings.json   aggiunge i 4 hook a quelli che ci sono già (copia di sicurezza settings.json.bak-<data-ora>);
                     un hook già registrato (stesso script) non si duplica.
  - Wiki reference.md, index.md, log.md, CLAUDE.md, raw/, wiki/   solo se mancano.
  - skill            in ~/.claude/skills/ (--skill utente, predefinito) o in <vault>/.claude/skills/ (--skill vault);
                     una skill già presente e diversa si lascia, salvo --aggiorna.
Alla fine controlla PyYAML e FTS5, lancia build_graph.py --check e, su un vault già in uso, dice cosa adattare
(vedi ADATTA.md).

Uso:
  python installa.py <cartella del vault> [--skill utente|vault|no] [--aggiorna] [--esempio]
  python installa.py --prova        installa in una cartella temporanea con il vault d'esempio, verifica e cancella
"""
import argparse
import filecmp
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

KIT = Path(__file__).resolve().parent / "kit"
SCHEMA = ["Wiki reference.md", "index.md", "log.md", "CLAUDE.md"]
FACOLTATIVI = {"banco.py", "candidati.py"}
DOMINIO = ("misura.py (DOMANDE, ATTESE, ROUTING, NEGATIVI, TESTO, ATTESI_FALLITI, MEMORIA), recall.py e build_graph.py "
           "(PAROLE_COMUNI, PAROLE_COMUNI_NOMI, NON_RELAZIONI), domande.py (NON_TERMINI, CON_REFERENTE)")


def adesso():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


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


def comando_python():
    return "python" if shutil.which("python") else ("py" if shutil.which("py") else "python")


def unisci_hook(vault, rapporto):
    """Aggiunge gli hook del kit a .claude/settings.json senza toccare gli altri."""
    kit = json.loads((KIT / "vault" / "settings.json").read_text(encoding="utf-8"))
    python = comando_python()
    for gruppi in kit["hooks"].values():
        for g in gruppi:
            for h in g["hooks"]:
                h["command"] = h["command"].replace("python ", f"{python} ", 1)
    path = vault / ".claude" / "settings.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rapporto(".claude/settings.json", "creato con i 4 hook")
        return
    try:
        attuale = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        rapporto.avviso(f".claude/settings.json non è JSON valido ({e}): hook NON registrati, correggerlo e rilanciare")
        return
    hooks = attuale.setdefault("hooks", {})
    aggiunti = []
    for evento, gruppi in kit["hooks"].items():
        script = gruppi[0]["hooks"][0]["command"].split("/.graph/")[1].split('"')[0]
        presenti = [h.get("command", "") for g in hooks.get(evento, []) for h in g.get("hooks", [])]
        if any(script in c for c in presenti):
            continue
        hooks.setdefault(evento, []).extend(gruppi)
        aggiunti.append(f"{evento} → {script}")
    if not aggiunti:
        rapporto(".claude/settings.json", "hook già registrati")
        return
    backup = path.with_name(f"settings.json.bak-{adesso()}")
    shutil.copyfile(path, backup)
    path.write_text(json.dumps(attuale, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rapporto(".claude/settings.json", f"aggiunti {', '.join(aggiunti)} (copia in {backup.name})")


def installa_skill(modo, vault, aggiorna, rapporto):
    if modo == "no":
        rapporto("skill", "non installate (--skill no)")
        return
    radice = Path.home() / ".claude" / "skills" if modo == "utente" else vault / ".claude" / "skills"
    for cartella in sorted((KIT / "skills").iterdir()):
        dest = radice / cartella.name / "SKILL.md"
        copia_file(cartella / "SKILL.md", dest, aggiorna, dest.parent / f"backup-{adesso()}", rapporto,
                   f"skill {cartella.name} ({modo})")


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


def controlla_ambiente(rapporto):
    try:
        import yaml  # noqa: F401
        rapporto("PyYAML", "presente")
    except ImportError:
        rapporto.avviso(f"PyYAML manca: {sys.executable} -m pip install pyyaml")
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        rapporto("SQLite FTS5", "presente")
    except sqlite3.Error:
        rapporto.avviso("SQLite di questo Python non ha FTS5: il ripiego sul testo non funzionerà")
    if not shutil.which("claude"):
        rapporto.avviso("eseguibile claude non nel PATH: il routing verso Haiku non partirà (risponde il modello della sessione)")


def controlla_vault(vault, rapporto):
    """Cosa manca a un vault già in uso perché il grafo lo veda bene. Solo lettura."""
    nascoste = {".graph", ".claude", ".obsidian", ".git", ".trash", ".graph_backup"}
    fuori = [p for p in vault.rglob("*.md")
             if not set(p.relative_to(vault).parts) & nascoste
             and p.relative_to(vault).parts[0] not in ("wiki", "raw")
             and p.relative_to(vault).as_posix() not in SCHEMA]
    sotto = [p for p in (vault / "wiki").rglob("*.md") if p.parent != vault / "wiki"]
    if fuori:
        rapporto.avviso(f"{len(fuori)} pagine fuori da wiki/ e raw/ (es. {fuori[0].relative_to(vault).as_posix()}): "
                        "il grafo non le vede. Vedi ADATTA.md, passo 2")
    if sotto:
        rapporto.avviso(f"{len(sotto)} pagine in sottocartelle di wiki/ (es. {sotto[0].relative_to(vault).as_posix()}): "
                        "il grafo legge solo wiki/*.md. Vedi ADATTA.md, passo 2")
    ref = vault / "Wiki reference.md"
    testo = ref.read_text(encoding="utf-8") if ref.exists() else ""
    if "## Relazioni tipizzate" not in testo:
        rapporto.avviso("Wiki reference.md senza «## Relazioni tipizzate»: nessun controllo sulle relazioni. "
                        "Vedi ADATTA.md, passo 3")
    indice = vault / "index.md"
    if indice.exists() and "## Punti aperti nel vault" not in indice.read_text(encoding="utf-8"):
        rapporto.avviso("index.md senza «## Punti aperti nel vault»: le domande aperte di tipo «punto» non si calcolano")


def esegui(vault, *argomenti):
    p = subprocess.run([sys.executable, *argomenti], cwd=vault, capture_output=True,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return p.returncode, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")


def installa(vault, skill="utente", aggiorna=False, esempio=False):
    vault = vault.resolve()
    gia_in_uso = vault.exists() and any(vault.rglob("*.md"))
    rapporto = Rapporto()
    print(f"Teseo → {vault}  ({'vault già in uso' if gia_in_uso else 'vault nuovo'})")
    for cartella in ("raw", "wiki", ".graph"):
        (vault / cartella).mkdir(parents=True, exist_ok=True)

    backup = vault / ".graph_backup" / adesso()
    diversi = []
    for f in sorted((KIT / "graph").glob("*.py")) + [KIT / "vault" / "requirements.txt"]:
        nome = f".graph/{f.name}" + (" (facoltativo)" if f.name in FACOLTATIVI else "")
        if copia_file(f, vault / ".graph" / f.name, aggiorna, backup, rapporto, nome) == "diverso":
            diversi.append(f.name)
    if aggiorna and backup.exists():
        rapporto.avviso(f"script sostituiti: riportare a mano i dati di dominio dal backup "
                        f"({backup.relative_to(vault).as_posix()}): {DOMINIO}")
    for nome in SCHEMA:
        dest = vault / nome
        if dest.exists():
            rapporto(nome, "già presente, non toccato")
        else:
            shutil.copyfile(KIT / "vault" / nome, dest)
            rapporto(nome, "creato dal modello del kit")
    unisci_hook(vault, rapporto)
    installa_skill(skill, vault, aggiorna, rapporto)
    if esempio:
        copia_esempio(vault, rapporto)
    controlla_ambiente(rapporto)
    if gia_in_uso:
        controlla_vault(vault, rapporto)
    rapporto.stampa()

    codice, uscita = esegui(vault, ".graph/build_graph.py", "--check")
    righe = uscita.strip().splitlines()
    print("\npython .graph/build_graph.py --check")
    problemi = [r for r in righe if r.strip().startswith("⚠️")]
    for r in ([righe[0], *problemi[:15]] if righe else []):
        print(f"  {r.strip()}")
    if len(problemi) > 15:
        print(f"  … e altri {len(problemi) - 15}")
    print(f"  {righe[-1].strip() if righe else 'nessun output'}")
    if diversi:
        print(f"\nScript diversi dal kit, lasciati come sono: {', '.join(diversi)}. "
              "Per aggiornarli: python installa.py <vault> --aggiorna")
    print("\nPoi: riaprire Claude Code nella cartella del vault (gli hook valgono dalla sessione successiva)."
          + ("\nVault già in uso: seguire ADATTA.md per far vedere le pagine al grafo." if gia_in_uso else ""))
    return codice


def prova():
    """Installazione di prova con il vault d'esempio in una cartella temporanea: niente esce da lì."""
    cartella = Path(tempfile.mkdtemp(prefix="teseo-prova-"))
    try:
        installa(cartella, skill="vault", esempio=True)
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
    ap.add_argument("--skill", choices=("utente", "vault", "no"), default="utente",
                    help="dove installare le 4 skill: ~/.claude/skills (utente), <vault>/.claude/skills (vault), no")
    ap.add_argument("--aggiorna", action="store_true", help="sostituisce script e skill diversi dal kit, con copia di sicurezza")
    ap.add_argument("--esempio", action="store_true", help="aggiunge il vault d'esempio (solo se wiki/ è vuota)")
    ap.add_argument("--prova", action="store_true", help="prova completa in una cartella temporanea, poi la cancella")
    args = ap.parse_args()
    if args.prova:
        sys.exit(prova())
    if not args.vault:
        ap.error("indicare la cartella del vault, oppure --prova")
    sys.exit(installa(args.vault, args.skill, args.aggiorna, args.esempio))


if __name__ == "__main__":
    main()

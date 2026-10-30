"""Correzioni manuali ricorrenti: se correggi sempre la stessa cosa, il difetto è nelle istruzioni, non nella pagina.

Legge la storia Git di `wiki/` nei vault collaborativi, dove ogni commit porta i trailer `Teseo-Skill` e `Teseo-Agent`. Una
modifica con `Teseo-Skill: manuale` a una pagina che l'ultima volta aveva scritto `ingest` o `lint` è una **correzione**;
si classificano solo i cambiamenti del frontmatter, che è strutturato:

  relazione_aggiunta / relazione_tolta   chiave = nome della relazione (usa, richiede, …)
  alias_aggiunto / alias_tolto           chiave = tipo della pagina
  tipo_cambiato                          chiave = «vecchio->nuovo»
  fonti_aggiunte / fonti_tolte

Dopo una correzione la pagina non è più «dell'ingest» finché una skill non la riscrive: modifiche ripetute di seguito
sono una sola correzione. Una categoria con almeno `--min-occorrenze` correzioni (predefinito 3) su almeno `--min-pagine`
pagine (predefinito 2) diventa una **proposta** di rivedere `Wiki reference.md` o la skill. Le correzioni isolate sono solo
contate. Non scrive nulla e non modifica le istruzioni: la decisione è dell'utente. Senza Git, senza autosync (nessun
trailer) o senza l'installazione `dashboard/` risponde con un messaggio ed esce con 0.

Uso:
  python .graph/correzioni.py [--json] [--min-occorrenze 3] [--min-pagine 2] [--ultimi 1000]
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from build_graph import bersaglio, leggi_testo, valori

NON_RELAZIONI = {"tipo", "tags", "fonti", "aggiornato", "aliases", "relazioni_dettaglio"}
TRAILER = re.compile(r"^Teseo-Skill:[ \t]*([a-z][a-z0-9-]{0,31})[ \t]*$", re.M)
DA_CORREGGERE = {"ingest", "lint"}
MAX_COMMIT = 1000
PROPOSTE = {
    "relazione_tolta": "La relazione «{k}» scritta dalla skill viene tolta a mano: rivedere quando vale «{k}» in Wiki reference.md "
                       "(Relazioni tipizzate) e il passo 5 della skill obsidian-wiki-ingest.",
    "relazione_aggiunta": "La relazione «{k}» viene aggiunta a mano: la skill non la dichiara abbastanza. Rivedere la sua definizione "
                          "in Wiki reference.md (Relazioni tipizzate) e il passo 5 di obsidian-wiki-ingest.",
    "alias_aggiunto": "Gli alias delle pagine di tipo «{k}» vengono aggiunti a mano: rivedere la regola sugli alias "
                      "(Wiki reference.md, Relazioni tipizzate) e il passo 5 di obsidian-wiki-ingest.",
    "alias_tolto": "Gli alias scritti dalla skill sulle pagine di tipo «{k}» vengono tolti a mano: rivedere la regola sugli alias "
                   "ambigui o non verificati.",
    "tipo_cambiato": "Il tipo scelto dalla skill viene cambiato a mano ({k}): rivedere i tipi ammessi e le convenzioni delle pagine "
                     "in Wiki reference.md.",
    "fonti_aggiunte": "Le fonti vengono aggiunte a mano: la skill non le citava tutte. Rivedere Wiki reference.md (Chiavi delle fonti) "
                      "e il passo 4 di obsidian-wiki-ingest.",
    "fonti_tolte": "Le fonti scritte dalla skill vengono tolte a mano: rivedere come si assegnano a ogni pagina.",
}


def _dipendenze():
    """(esecutore di Git, ContractError) dell'installazione: .graph/dashboard nel vault, kit/dashboard nel repository."""
    try:
        from dashboard.contracts import ContractError
        from dashboard.git_sync import _invoke
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from kit.dashboard.contracts import ContractError
        from kit.dashboard.git_sync import _invoke
    return _invoke, ContractError


def _insiemi(prima, dopo, chiave):
    p, d = ({str(x).strip().lower() for x in valori(f.get(chiave))} for f in (prima, dopo))
    return d - p, p - d


def _eventi(prima, dopo):
    """Cambiamenti del frontmatter come [(categoria, chiave)]."""
    eventi = []
    if prima.get("tipo") != dopo.get("tipo"):
        eventi.append(("tipo_cambiato", f"{prima.get('tipo')}->{dopo.get('tipo')}"))
    aggiunti, tolti = _insiemi(prima, dopo, "aliases")
    tipo = str(dopo.get("tipo") or prima.get("tipo"))
    eventi += ([("alias_aggiunto", tipo)] if aggiunti else []) + ([("alias_tolto", tipo)] if tolti else [])
    aggiunte, tolte = _insiemi(prima, dopo, "fonti")
    eventi += ([("fonti_aggiunte", "")] if aggiunte else []) + ([("fonti_tolte", "")] if tolte else [])
    for chiave in sorted((set(prima) | set(dopo)) - NON_RELAZIONI):
        bersagli = [{bersaglio(v).lower() for v in valori(f.get(chiave))} for f in (prima, dopo)]
        eventi += ([("relazione_aggiunta", str(chiave))] if bersagli[1] - bersagli[0] else []) \
            + ([("relazione_tolta", str(chiave))] if bersagli[0] - bersagli[1] else [])
    return eventi


def _frontmatter(testo, nome):
    try:
        return leggi_testo(testo, nome)[0]
    except ValueError:
        return None


def analizza(vault, ultimi=MAX_COMMIT, min_occorrenze=3, min_pagine=2):
    """{commit_manuali, correzioni, isolate, proposte, messaggio}; ogni proposta ha categoria, chiave, occorrenze, pagine, commit, proposta."""
    risultato = {"commit_manuali": 0, "correzioni": 0, "isolate": 0, "proposte": [], "messaggio": None}
    vault = Path(vault)
    try:
        invoke, errore_git = _dipendenze()
    except ImportError:
        risultato["messaggio"] = "Installazione senza dashboard/: correzioni.py usa lo stesso Git rinforzato dell'autosync"
        return risultato

    def git(*argomenti):
        try:
            fatto = invoke(vault, list(argomenti), check=False)
        except errore_git:
            return None
        return fatto.stdout.decode("utf-8", "replace") if fatto.returncode == 0 else None
    if not (vault / ".git").exists() or git("rev-parse", "--verify", "-q", "HEAD") is None:
        risultato["messaggio"] = "Nessun repository Git con commit: le correzioni si riconoscono dalla storia dell'autosync collaborativo"
        return risultato
    uscita = git("log", "--reverse", "--no-merges", "-M", "--name-status", f"--max-count={int(ultimi)}",
                 "--format=%x1e%H%x1f%B%x1f", "--", "wiki/")
    if uscita is None:
        risultato["messaggio"] = "Storia Git non leggibile"
        return risultato
    ultimo, eventi, attribuiti = {}, [], 0
    for record in uscita.split("\x1e")[1:]:
        sha, corpo, modifiche = (record.split("\x1f") + ["", ""])[:3]
        trailer = TRAILER.search(corpo)
        skill = trailer[1] if trailer else None
        attribuiti += bool(skill)
        manuale = skill == "manuale"
        risultato["commit_manuali"] += manuale
        for riga in modifiche.strip().splitlines():
            colonne = riga.split("\t")
            stato, percorsi = colonne[0][:1], colonne[1:]
            if not stato or not percorsi:
                continue
            if stato in "RC" and len(percorsi) == 2:
                if stato == "R":
                    ultimo.pop(percorsi[0], None)
                ultimo[percorsi[1]] = skill
                continue
            percorso = percorsi[0]
            if not (percorso.startswith("wiki/") and percorso.endswith(".md") and percorso.count("/") == 1):
                continue
            if stato == "D":
                ultimo.pop(percorso, None)
            elif stato == "M" and manuale and ultimo.get(percorso) in DA_CORREGGERE:
                prima, dopo = (git("show", f"{sha}^:{percorso}"), git("show", f"{sha}:{percorso}"))
                fm_prima, fm_dopo = (_frontmatter(t, percorso) if t is not None else None for t in (prima, dopo))
                if fm_prima is not None and fm_dopo is not None:
                    eventi += [(categoria, chiave, percorso[5:-3], sha[:8]) for categoria, chiave in _eventi(fm_prima, fm_dopo)]
            if stato in "AM":
                ultimo[percorso] = skill
    risultato["correzioni"] = len(eventi)
    gruppi = defaultdict(list)
    for categoria, chiave, pagina, sha in eventi:
        gruppi[(categoria, chiave)].append((pagina, sha))
    for (categoria, chiave), voci in sorted(gruppi.items(), key=lambda g: (-len(g[1]), g[0])):
        pagine = sorted({p for p, _ in voci})
        if len(voci) >= min_occorrenze and len(pagine) >= min_pagine:
            risultato["proposte"].append({"categoria": categoria, "chiave": chiave, "occorrenze": len(voci), "pagine": pagine,
                                          "commit": sorted({s for _, s in voci}), "proposta": PROPOSTE[categoria].format(k=chiave)})
        else:
            risultato["isolate"] += len(voci)
    if not attribuiti:
        risultato["messaggio"] = "Nessun commit con trailer Teseo-Skill: serve l'autosync collaborativo per riconoscere le correzioni a mano"
    elif not risultato["commit_manuali"]:
        risultato["messaggio"] = "Nessuna modifica manuale (--skill manuale) nella finestra esaminata"
    return risultato


def _intero_positivo(valore):
    try:
        numero = int(valore)
    except ValueError:
        raise argparse.ArgumentTypeError(f"«{valore}» non è un numero intero") from None
    if numero < 1:
        raise argparse.ArgumentTypeError("serve un numero maggiore o uguale a 1")
    return numero


def main(argv=None):
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vault", type=Path, default=qui.parent)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-occorrenze", type=_intero_positivo, default=3, help="correzioni minime per una proposta (predefinito 3)")
    ap.add_argument("--min-pagine", type=_intero_positivo, default=2, help="pagine minime per una proposta (predefinito 2)")
    ap.add_argument("--ultimi", type=_intero_positivo, default=MAX_COMMIT, help=f"commit esaminati (predefinito {MAX_COMMIT})")
    args = ap.parse_args(argv)
    esito = analizza(args.vault, args.ultimi, args.min_occorrenze, args.min_pagine)
    if args.json:
        print(json.dumps(esito, ensure_ascii=False, indent=2))
        return 0
    print(f"Correzioni manuali a pagine di ingest o lint: {esito['correzioni']} in {esito['commit_manuali']} commit manuali "
          f"(ultimi {args.ultimi} commit)")
    if esito["proposte"]:
        print("Proposte da valutare (nessuna modifica è stata fatta):")
    for i, q in enumerate(esito["proposte"], 1):
        etichetta = f"{q['categoria']} «{q['chiave']}»" if q["chiave"] else q["categoria"]
        print(f"{i}. {etichetta}: {q['occorrenze']} volte su {len(q['pagine'])} pagine ({', '.join(q['pagine'][:5])}"
              + (", …" if len(q["pagine"]) > 5 else "") + f")\n   {q['proposta']}")
    if not esito["proposte"]:
        print("Nessuna correzione ricorrente.")
    if esito["isolate"]:
        print(f"Correzioni isolate ignorate: {esito['isolate']}")
    if esito["messaggio"]:
        print(esito["messaggio"])
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

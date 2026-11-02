"""Lo schema del vault a fette (doc/17, fase 1): al modello arriva solo la parte di Wiki reference.md che gli serve.

Wiki reference.md resta l'autorità; questo script lo legge e ne stampa fette, in sola lettura e senza LLM. Tre livelli:
  1  sempre        Regole non negoziabili, Convenzioni delle pagine (senza le pagine generate per entropia), il formato
                   delle Chiavi delle fonti e l'indice dei nomi di tipi, relazioni e categorie, uno per voce e senza
                   descrizioni. Tetto TETTO_LIVELLO_1 token.
  2  mirato        le righe complete dei tipi indicati e dei loro antenati (Sottotipo di), le relazioni che possono partire
                   da quei tipi o arrivarci (come tipo_ammesso: antenati e «qualsiasi» compresi), le righe delle chiavi
                   delle fonti citate. Tetto TETTO_LIVELLO_2 token.
  3  su richiesta  tutto il file: se hai un dubbio, leggi Wiki reference.md per intero (prevale sempre).
Le fette sono tabelle e paragrafi di regola, non sezioni h2 intere: sotto «Relazioni tipizzate» sta anche la descrizione
degli script, che non è schema. I tetti sono avvisi, non errori. Senza il catalogo «Tipi ammessi» il livello 2 stampa tutte
le relazioni; con errori di schema avvisa di leggere il file per intero. Token = caratteri/4, come contratti.py --peso.

Uso:
  python .graph/schema.py --livello 1 [--entropia] [--sezione "Manutenzione del vault"]
  python .graph/schema.py --per-tipi portale,persona [--fonti call-a,call-b]
  python .graph/schema.py --per-pagine "Modulo fatture,Anna Rossi"      i tipi li legge dal grafo
Opzioni comuni: --vault, --json ({testo, token, avvisi}), --tetto N. Exit 0; 2 se manca lo schema o il grafo.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import contratti
from build_graph import parse_ontology

TETTO_LIVELLO_1 = 3000  # token: regole, convenzioni e indice dei nomi
TETTO_LIVELLO_2 = 1500  # token: righe dei tipi toccati, relazioni applicabili, fonti citate
QUALSIASI = "qualsiasi"  # il jolly di ontology.WILDCARDS che vale per ogni tipo; «stesso tipo» non restringe
ENTROPIA = "Pagine generate per entropia"


def stima_token(testo):
    """Stima dei token di un testo: caratteri/4, la stessa di contratti.py --peso."""
    return len(testo) // 4


def _compatta(testo):
    """Il blocco senza righe vuote in testa e in coda e con al più una riga vuota di seguito."""
    righe, vuote = [], 0
    for riga in testo.strip().splitlines():
        vuote = vuote + 1 if not riga.strip() else 0
        if vuote <= 1:
            righe.append(riga.rstrip())
    return "\n".join(righe)


def _formato_fonti(testo):
    """Il titolo e il testo che precede la prima tabella di «Chiavi delle fonti»: il formato, non le chiavi."""
    sezione = contratti.testo_sezione(testo, "Chiavi delle fonti")
    if not sezione:
        return ""
    righe = sezione.splitlines()
    fine = next((i for i, r in enumerate(righe[1:], 1) if r.lstrip().startswith(("|", "#"))), len(righe))
    return _compatta("\n".join(righe[:fine]))


def _indice(ontologia):
    """«Tipi: a, b» / «Relazioni: …» / «Categorie: …»: i soli nomi, nell'ordine del documento."""
    righe = []
    if ontologia.types is not None:
        righe.append("Tipi: " + ", ".join(t.name for t in ontologia.types))
    if ontologia.relations:
        righe.append("Relazioni: " + ", ".join(r.name for r in ontologia.relations))
    if ontologia.categories is not None:
        righe.append("Categorie: " + ", ".join(c.name for c in ontologia.categories))
    return "\n".join(righe)


def _errori(ontologia):
    errori = [f"{i.code}: {i.message}" for i in ontologia.issues if i.severity == "error"]
    if not errori:
        return []
    return [f"schema con errori ({errori[0]}{', …' if len(errori) > 1 else ''}): "
            "le fette potrebbero essere incomplete, leggere Wiki reference.md per intero"]


def _cella(valore):
    return valore.replace("|", "\\|")


def _tabella(intestazione, righe):
    return "\n".join([f"| {' | '.join(intestazione)} |", "| " + " | ".join("---" for _ in intestazione) + " |",
                      *(f"| {' | '.join(riga)} |" for riga in righe)])


def _livello_1(testo, ontologia, entropia, sezioni):
    avvisi, parti = [], []
    if regole := contratti.testo_sezione(testo, "Regole non negoziabili"):
        parti.append(_compatta(regole))
    if convenzioni := contratti.testo_sezione(testo, "Convenzioni delle pagine"):
        entropica = contratti.testo_sezione(testo, ENTROPIA) or ""
        parti.append(_compatta(convenzioni.replace(entropica, "", 1) if entropica else convenzioni))
    if formato := _formato_fonti(testo):
        parti.append(formato)
    if indice := _indice(ontologia):
        parti.append("## Nomi ammessi (le righe complete: schema.py --per-tipi / --per-pagine)\n" + indice)
    for titolo in ([ENTROPIA] if entropia else []) + list(sezioni):
        if sezione := contratti.testo_sezione(testo, titolo):
            parti.append(_compatta(sezione))
        else:
            avvisi.append(f"sezione «{titolo}» assente in Wiki reference.md")
    return parti, avvisi + _errori(ontologia)


def _livello_2(testo, ontologia, tipi, fonti):
    avvisi, parti = [], []
    if tipi:
        if ontologia.types is None:
            avvisi.append("catalogo dei tipi assente: stampate tutte le relazioni, nessuna riga di tipo")
            rilevanti = None
        else:
            dichiarati = {t.name for t in ontologia.types}
            avvisi += [f"tipo «{t}» non dichiarato nel catalogo Tipi ammessi" for t in tipi if t not in dichiarati]
            rilevanti = {t for t in tipi if t in dichiarati}
            for tipo in list(rilevanti):
                rilevanti |= set(ontologia.ancestors.get(tipo, ()))
            righe = [[f"`{t.name}`", _cella(t.description), t.parent] for t in ontologia.types if t.name in rilevanti]
            if righe:
                parti.append("## Tipi\n" + _tabella(["Tipo", "Descrizione", "Sottotipo di"], righe))
        righe = [[f"`{r.name}`", ", ".join(r.from_types), ", ".join(r.to_types), _cella(r.meaning), _cella(r.example)]
                 for r in ontologia.relations
                 if rilevanti is None or any(t in rilevanti or t == QUALSIASI for t in (*r.from_types, *r.to_types))]
        if righe:
            parti.append("## Relazioni applicabili\n"
                         + _tabella(["Relazione", "Da (tipo)", "A (tipo)", "Significato", "Esempio"], righe))
    if fonti:
        trovate = {}
        for riga in testo.splitlines():
            chiave = re.match(r"^\|\s*`([^`]+)`\s*\|", riga)
            if chiave and chiave[1] in fonti:
                trovate.setdefault(chiave[1], riga.rstrip())
        avvisi += [f"fonte «{f}» non censita in Chiavi delle fonti" for f in fonti if f not in trovate]
        if trovate:
            parti.append("## Fonti citate\n" + "\n".join(trovate[f] for f in fonti if f in trovate))
    return parti, avvisi + _errori(ontologia)


def fette(testo, livello=1, tipi=(), fonti=(), entropia=False, sezioni=(), tetto=None):
    """Una fetta di Wiki reference.md: {"testo", "token", "avvisi"}.

    livello 1: regole, convenzioni, indice dei nomi (più la sezione «Pagine generate per entropia» con `entropia` e le
    `sezioni` indicate per titolo). livello 2: le righe dei `tipi` con gli antenati, le relazioni applicabili e le righe
    delle chiavi delle `fonti`. `tetto` (token) sostituisce quello del livello; superarlo è un avviso."""
    ontologia = parse_ontology(testo)
    parti, avvisi = (_livello_1(testo, ontologia, entropia, sezioni) if livello == 1
                     else _livello_2(testo, ontologia, tuple(tipi), tuple(fonti)))
    risultato = "\n\n".join(parti)
    token = stima_token(risultato)
    limite = tetto if tetto is not None else (TETTO_LIVELLO_1 if livello == 1 else TETTO_LIVELLO_2)
    if token > limite:
        avvisi.append(f"fetta del livello {livello} oltre il tetto di {limite} token ({token})")
    return {"testo": risultato, "token": token, "avvisi": avvisi}


def tipi_delle_pagine(db, pagine):
    """(tipi in ordine alfabetico, pagine ignote al grafo) delle pagine indicate per nome (wiki/ del grafo)."""
    noti = dict(db.execute("SELECT id, tipo FROM entities WHERE path LIKE 'wiki/%'").fetchall())
    ignote = [p for p in pagine if p not in noti]
    return tuple(sorted({noti[p] for p in pagine if noti.get(p)})), ignote


def _elenco(valore):
    return [v.strip() for v in valore.split(",") if v.strip()] if valore else []


def main(argv=None):
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vault", type=Path, default=qui.parent)
    ap.add_argument("--db", type=Path, help="grafo (predefinito: .graph/graph.sqlite del vault)")
    ap.add_argument("--livello", type=int, choices=[1], help="livello 1: regole, convenzioni e indice dei nomi")
    ap.add_argument("--entropia", action="store_true", help="con --livello 1: aggiunge «Pagine generate per entropia»")
    ap.add_argument("--sezione", action="append", default=[], metavar="TITOLO",
                    help="con --livello 1: aggiunge questa sezione (si può ripetere)")
    ap.add_argument("--per-tipi", metavar="TIPI", help="livello 2: tipi separati da virgola")
    ap.add_argument("--per-pagine", metavar="PAGINE", help="livello 2: pagine separate da virgola, i tipi dal grafo")
    ap.add_argument("--fonti", metavar="CHIAVI", help="livello 2: chiavi delle fonti citate, separate da virgola")
    ap.add_argument("--tetto", type=int, help="tetto in token (sostituisce quello del livello)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not (args.livello or args.per_tipi or args.per_pagine or args.fonti):
        ap.error("serve --livello 1, --per-tipi, --per-pagine o --fonti")
    percorso = args.vault / "Wiki reference.md"
    if not percorso.is_file():
        print(f"errore: {percorso} non esiste", file=sys.stderr)
        return 2
    testo = percorso.read_text(encoding="utf-8")
    tipi, avvisi_pagine = _elenco(args.per_tipi), []
    if args.per_pagine:
        from graph_db import GraphDatabaseError, connect_graph, resolve_graph
        grafo = args.db or args.vault / ".graph/graph.sqlite"
        if not resolve_graph(grafo).exists():
            print(f"errore: {grafo} non esiste: lanciare prima .graph/build_graph.py", file=sys.stderr)
            return 2
        try:
            db = connect_graph(grafo)
            try:
                dai_dati, ignote = tipi_delle_pagine(db, _elenco(args.per_pagine))
            finally:
                db.close()
        except GraphDatabaseError as errore:
            print(f"errore: {errore}", file=sys.stderr)
            return 2
        tipi += [t for t in dai_dati if t not in tipi]
        if ignote:
            avvisi_pagine.append("pagine non nel grafo (nuove?), senza tipo: " + ", ".join(ignote))
    esiti = []
    if args.livello:
        esiti.append(fette(testo, 1, entropia=args.entropia, sezioni=args.sezione, tetto=args.tetto))
    if tipi or args.fonti:
        esiti.append(fette(testo, 2, tipi=tipi, fonti=_elenco(args.fonti), tetto=args.tetto))
    risultato = {"testo": "\n\n".join(e["testo"] for e in esiti if e["testo"]),
                 "token": sum(e["token"] for e in esiti),
                 "avvisi": avvisi_pagine + [a for e in esiti for a in e["avvisi"]]}
    if args.json:
        print(json.dumps(risultato, ensure_ascii=False, indent=2))
    else:
        print(risultato["testo"])
        for avviso in risultato["avvisi"]:
            print(f"\n⚠️ {avviso}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

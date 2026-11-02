"""KPI di coerenza delle risposte (doc/kpi-coerenza.md): coerenza dei nomi e stabilità fra giri. Deterministico: nessun LLM.

Legge le risposte che `misura.py --modello --giri N --out DIR` salva una per file (`NN-<condizione>-G.json`, con
condizione `ricerca`, `grafo` o `hook`) e conta, per condizione:
  coerenza dei nomi    menzioni di pagine fatte con il nome della pagina, su tutte le menzioni (nome, alias o
                       variante grafica della tabella `varianti`)
  stabilità fra giri   per ogni domanda con almeno 2 giri, la media della somiglianza di Jaccard a coppie fra le pagine
                       menzionate nei giri; poi la media sulle domande. In più quante domande hanno lo stesso esito
                       (campo `corretta`, o tutte le `regex` per le risposte di --hook) in tutti i giri
Una menzione è un nome, un alias o una variante trovato nella risposta come sequenza di parole intere dopo norm (senza
maiuscole né accenti), la forma più lunga per prima e senza sovrapposizioni; una forma che appartiene a più pagine non
conta; i nomi che sono anche parole comuni (recall.PAROLE_COMUNI) contano solo con l'iniziale maiuscola, come nel
recall. La Jaccard di due insiemi vuoti vale 1: due risposte che non nominano pagine sono d'accordo.
I file illeggibili, senza risposta o con un errore del client si scartano e si contano a parte.
La stabilità fra parafrasi del banco la misura misura.py (sezione BANCO), che usa jaccard() di questo modulo.

Uso:
  python .graph/coerenza.py --risposte <cartella di misura.py --out> [--db .graph/graph.sqlite] [--json]
Exit 0; 2 se la cartella non ha risposte da contare.
"""
import argparse
from collections import defaultdict
from itertools import combinations
import json
import re
import sqlite3
import sys
from pathlib import Path

from build_graph import norm
from graph_db import connect_graph, resolve_graph
from recall import PAROLE_COMUNI

FILE_RISPOSTA = re.compile(r"^(\d+)-([a-z]+)-(\d+)\.json$")
PAROLA = re.compile(r"[^\W_]+")


def jaccard(a, b):
    """Somiglianza di Jaccard fra due insiemi: |a∩b| / |a∪b|, 1.0 se sono entrambi vuoti."""
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def nomi_del_grafo(db):
    """Le forme con cui una pagina può essere nominata: {norm(forma): (pagina, canonica)}.

    Canonica = il nome della pagina; non canoniche gli alias e le varianti grafiche. Una forma di più pagine si scarta.
    Le fonti (entità senza percorso in wiki/) non sono pagine. Un grafo senza la tabella `varianti` usa nomi e alias."""
    forme = defaultdict(set)
    for (id_,) in db.execute("SELECT id FROM entities WHERE path LIKE 'wiki/%'"):
        forme[norm(id_)].add((id_, True))
    pagine = {id_ for voci in forme.values() for id_, _ in voci}
    for tabella, colonna in (("aliases", "alias"), ("varianti", "variante")):
        try:
            righe = db.execute(f"SELECT entity_id, {colonna} FROM {tabella}").fetchall()
        except sqlite3.OperationalError:  # grafo di una versione senza la tabella
            continue
        for id_, forma in righe:
            if id_ in pagine and norm(forma):
                forme[norm(forma)].add((id_, False))
    risultato = {}
    for forma, voci in forme.items():
        if len({id_ for id_, _ in voci}) == 1:
            risultato[forma] = (next(iter(voci))[0], any(canonica for _, canonica in voci))
    return risultato


def menzioni(testo, nomi):
    """Le pagine nominate nel testo, nell'ordine: [(pagina, canonica)]; `nomi` come da nomi_del_grafo."""
    parole = [(originale, w) for originale in PAROLA.findall(testo) for w in norm(originale).split()]
    massimo = max((len(forma.split()) for forma in nomi), default=0)
    trovate, i = [], 0
    while i < len(parole):
        for k in range(min(massimo, len(parole) - i), 0, -1):
            forma = " ".join(w for _, w in parole[i:i + k])
            if forma not in nomi or (forma in PAROLE_COMUNI and not parole[i][0][:1].isupper()):
                continue
            trovate.append(nomi[forma])
            i += k
            break
        else:
            i += 1
    return trovate


def leggi_risposte(cartella):
    """Le risposte salvate da misura.py: ({(domanda, condizione): [giri in ordine]}, [(file scartato, motivo)]).

    Ogni giro è {"giro", "risposta", "esito"}; esito = `corretta`, oppure tutte le `regex` (risposte di --hook), o None."""
    risposte, scartate = defaultdict(list), []
    for percorso in sorted(Path(cartella).iterdir()):
        nome = FILE_RISPOSTA.match(percorso.name)
        if not nome or not percorso.is_file():
            continue
        try:
            dati = json.loads(percorso.read_text(encoding="utf-8"))
        except (OSError, ValueError) as errore:
            scartate.append((percorso.name, f"illeggibile: {errore}"))
            continue
        if not isinstance(dati, dict) or not isinstance(dati.get("risposta"), str):
            scartate.append((percorso.name, "senza risposta"))
            continue
        if dati.get("errore"):
            scartate.append((percorso.name, "errore del client"))
            continue
        if "corretta" in dati:
            esito = bool(dati["corretta"])
        elif isinstance(dati.get("regex"), list):
            esito = all(dati["regex"])
        else:
            esito = None
        risposte[(int(nome[1]), nome[2])].append({"giro": int(nome[3]), "risposta": dati["risposta"], "esito": esito})
    for giri in risposte.values():
        giri.sort(key=lambda g: g["giro"])
    return dict(risposte), scartate


def coerenza_nomi(testi, nomi):
    """Coerenza dei nomi su un insieme di risposte: {"menzioni", "canoniche", "quota"} (quota None senza menzioni)."""
    trovate = [canonica for testo in testi for _, canonica in menzioni(testo, nomi)]
    canoniche = sum(trovate)
    return {"menzioni": len(trovate), "canoniche": canoniche, "quota": canoniche / len(trovate) if trovate else None}


def stabilita_giri(risposte, nomi):
    """Per condizione: {"domande", "jaccard_medio", "esito_stabile"} sulle domande con almeno 2 giri."""
    per_condizione = defaultdict(lambda: {"domande": 0, "jaccard": [], "esito_stabile": 0})
    for (_, condizione), giri in sorted(risposte.items()):
        conti = per_condizione[condizione]
        if len(giri) < 2:
            continue
        insiemi = [{pagina for pagina, _ in menzioni(g["risposta"], nomi)} for g in giri]
        coppie = [jaccard(a, b) for a, b in combinations(insiemi, 2)]
        conti["domande"] += 1
        conti["jaccard"].append(sum(coppie) / len(coppie))
        esiti = {g["esito"] for g in giri}
        conti["esito_stabile"] += len(esiti) == 1 and None not in esiti
    return {condizione: {"domande": c["domande"],
                         "jaccard_medio": sum(c["jaccard"]) / len(c["jaccard"]) if c["jaccard"] else None,
                         "esito_stabile": c["esito_stabile"]}
            for condizione, c in per_condizione.items()}


def riepilogo(risposte, nomi):
    """Coerenza dei nomi e stabilità fra giri per condizione, in ordine di nome: {condizione: {...}}."""
    stabilita = stabilita_giri(risposte, nomi)
    risultato = {}
    for condizione in sorted({c for _, c in risposte}):
        testi = [g["risposta"] for (_, c), giri in risposte.items() if c == condizione for g in giri]
        risultato[condizione] = {**coerenza_nomi(testi, nomi), **stabilita[condizione], "risposte": len(testi)}
    return risultato


def riga(condizione, r):
    """La riga di testo di una condizione del riepilogo."""
    nomi = (f"nomi canonici {r['canoniche']}/{r['menzioni']} ({100 * r['quota']:.0f}%)" if r["quota"] is not None
            else "nessuna pagina nominata")
    giri = (f"stabilità fra giri {r['jaccard_medio']:.2f} · esito stabile {r['esito_stabile']}/{r['domande']}"
            if r["domande"] else "stabilità fra giri - (un solo giro)")
    return f"{condizione}: {nomi} · {giri} · {r['risposte']} risposte"


def main(argv=None):
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--risposte", type=Path, required=True, help="cartella --out di misura.py --modello")
    ap.add_argument("--db", type=Path, default=qui / "graph.sqlite")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.risposte.is_dir():
        print(f"errore: {args.risposte} non è una cartella", file=sys.stderr)
        return 2
    if not resolve_graph(args.db).exists():
        print(f"errore: {args.db} non esiste: lanciare prima .graph/build_graph.py", file=sys.stderr)
        return 2
    db = connect_graph(args.db)
    try:
        nomi = nomi_del_grafo(db)
    finally:
        db.close()
    risposte, scartate = leggi_risposte(args.risposte)
    condizioni = riepilogo(risposte, nomi)
    if args.json:
        print(json.dumps({"condizioni": condizioni, "scartate": scartate}, ensure_ascii=False, indent=2))
    else:
        for condizione, r in condizioni.items():
            print(riga(condizione, r))
        for nome, motivo in scartate:
            print(f"scartata {nome}: {motivo}")
        if not risposte:
            print(f"nessuna risposta in {args.risposte}: lanciare misura.py --modello … --out {args.risposte}")
    return 0 if risposte else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

"""Domande a cui il vault sa già rispondere, ma solo mettendo insieme più pagine: candidate a una pagina di sintesi.

Complementare a domande.py, che elenca le domande aperte da rivolgere all'autore. Qui la risposta c'è già,
sparsa: una pagina di sintesi la raccoglie, e il recall la trova senza percorrere la catena ogni volta.
Deterministico, nessun LLM: la pagina la scrive la skill di lint, questo script sceglie cosa e verifica.

Quattro famiglie di domande:
  memoria   domande reali che il grafo non riconosceva, con le pagine lette per rispondere (memoria.sqlite)
  catena    da un processo o sistema, le relazioni usa/richiede/referente seguite fino a 3 passi,
            se toccano almeno 2 pagine oltre al punto di partenza (Rilascio in produzione → Console di rilascio →
            Incident settimanale → Anna Rossi). Sono le domande in cui la ricerca
            senza grafo sbaglia di più
  termine   identificatori citati in 3+ pagine di 3+ aree senza pagina né alias (domande.termini)
  persona   le pagine di cui una persona è `referente`, se sono almeno 2

Una domanda è **coperta** se esiste già una pagina che linka tutte le pagine della risposta (o è una di
esse e linka le altre); per un termine, se una pagina lo ha come titolo o alias. Scrivere la pagina di
sintesi è quindi anche il modo di chiudere la domanda, e rilanciare lo script è la verifica.
L'entropia resta governata perché le pagine generate non generano domande nuove: sono `riferimento`
(non partono catene), non dichiarano `referente`, e domande.py e domande.termini le ignorano (tag `entropia`).
Una domanda che il vault non basta a chiudere si scarta con --scarta: esce da qui ed entra nelle domande
aperte di domande.py, cioè va all'autore.

--verifica controlla le pagine con tag `entropia` già scritte: avviso «Informazioni generate da entropia
del vault» con la domanda a cui rispondono, `riguarda`, domanda risultata coperta, nessuna fonte che
non sia già in una delle pagine linkate (un fatto nuovo porterebbe una fonte nuova).

Uso:
  python .graph/sintesi.py                     candidate non coperte, in ordine di priorità
  python .graph/sintesi.py --tutte             anche quelle coperte, con la pagina che le copre
  python .graph/sintesi.py --json              per la skill di lint
  python .graph/sintesi.py --scarta "domanda" --motivo "manca il referente: chiedere all'autore"
  python .graph/sintesi.py --verifica          controlla le pagine generate (exit 1 se ci sono problemi)
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import domande
from build_graph import LINK, bersaglio, leggi, valori

PASSI = 3
CATENA = ("usa", "richiede", "referente")  # non precede: dice cosa viene dopo, non cosa serve
DA_CATENA = {"processo", "sistema"}
MIN_ALTRE = 2   # pagine della risposta oltre al punto di partenza
PRIORITA = {"memoria": 0, "catena": 1, "termine": 2, "persona": 3}
AVVISO = "Informazioni generate da entropia del vault"
RISPONDE = re.compile(r"Risponde a: «(.+?)»")


def collegamenti(db):
    """Pagina → pagine linkate, nel testo o nel frontmatter."""
    uscenti = defaultdict(set)
    for s, t in db.execute("SELECT source_id, target_id FROM relations WHERE type != 'documentato_in'"):
        uscenti[s].add(t)
    return uscenti


def copertura(uscenti, pagine):
    """La prima pagina che da sola collega tutte quelle della risposta, o None."""
    per_prima = sorted(uscenti, key=lambda p: (p not in pagine, p))
    for p in per_prima:
        if pagine <= uscenti[p] | {p}:
            return p
    return None


def catene(db):
    tipi = dict(db.execute("SELECT id, tipo FROM entities"))
    avanti = defaultdict(list)
    for s, t, rel in db.execute("SELECT source_id, target_id, type FROM relations "
                                f"WHERE type IN ({','.join('?' * len(CATENA))})", CATENA):
        avanti[s].append((rel, t))
    for partenza in sorted(avanti):
        if tipi.get(partenza) not in DA_CATENA:
            continue
        raggiunte, fronte, archi = {}, [partenza], []
        for _ in range(PASSI):
            nuovo = []
            for n in fronte:
                for rel, t in avanti.get(n, []):
                    if t != partenza and t not in raggiunte:
                        raggiunte[t] = rel
                        archi.append(f"{n} →{rel}→ {t}")
                        nuovo.append(t)
            fronte = nuovo
        if len(raggiunte) < MIN_ALTRE or len({a.split(" →")[0] for a in archi}) < 2:
            continue  # serve almeno un passo oltre il primo: altrimenti risponde la pagina di partenza
        chi = " e a chi mi rivolgo" if "referente" in raggiunte.values() else ""
        yield {"famiglia": "catena", "domanda": f"Per {partenza}: cosa serve, in che ordine{chi}?",
               "partenza": partenza, "pagine": [partenza, *raggiunte], "percorso": archi}


def termini(db, vault):
    for ts, dove in domande.termini(db, vault):
        nomi = ", ".join(f"`{t}`" for t in ts)
        yield {"famiglia": "termine", "domanda": f"Cos'è {nomi}, dove sta e chi lo usa?",
               "partenza": dove[0], "pagine": dove, "termini": ts,
               "percorso": [f"{p} cita {nomi}" for p in dove]}


def persone(db):
    per_persona = defaultdict(list)
    for s, t in db.execute("SELECT source_id, target_id FROM relations WHERE type = 'referente' ORDER BY source_id"):
        per_persona[t].append(s)
    for persona, di in sorted(per_persona.items()):
        if len(di) >= 2:
            yield {"famiglia": "persona", "domanda": f"Per cosa mi rivolgo a {persona}?",
                   "partenza": persona, "pagine": [persona, *di],
                   "percorso": [f"{s} →referente→ {persona}" for s in di]}


def memoria(qui, esistenti):
    path = qui / "memoria.sqlite"
    if not path.exists():
        return
    mem = sqlite3.connect(path)
    try:
        for id_, testo in mem.execute("SELECT id, testo FROM domande ORDER BY volte DESC, ultima DESC"):
            lette = [p for (p,) in mem.execute("SELECT pagina FROM pagine_lette WHERE domanda_id = ? "
                                               "ORDER BY volte DESC, rowid", (id_,)) if p in esistenti]
            if len(lette) >= 2:
                yield {"famiglia": "memoria", "domanda": testo, "partenza": lette[0], "pagine": lette,
                       "percorso": ["pagine lette per rispondere"]}
    finally:
        mem.close()


def candidate(db, qui, tutte=False):
    uscenti = collegamenti(db)
    esistenti = {id_ for (id_,) in db.execute("SELECT id FROM entities WHERE tipo != 'fonte'")}
    archivio = domande.apri(qui / "domande.sqlite")
    scartate = {d for (d,) in archivio.execute("SELECT domanda FROM scartate")}
    archivio.close()
    viste, elenco = set(), []
    for c in [*memoria(qui, esistenti), *catene(db), *termini(db, qui.parent), *persone(db)]:
        chiave = (c["famiglia"] == "termine", frozenset(c["pagine"]))
        if c["domanda"] in scartate or chiave in viste:
            continue
        viste.add(chiave)
        # un termine è coperto solo da una pagina col suo nome: domande.termini li ha già esclusi
        c["coperta_da"] = None if c["famiglia"] == "termine" else copertura(uscenti, set(c["pagine"]))
        if tutte or not c["coperta_da"]:
            elenco.append(c)
    return sorted(elenco, key=lambda c: (PRIORITA[c["famiglia"]], -len(c["pagine"]), c["domanda"]))


def verifica(db, qui):
    """Problemi delle pagine generate per entropia: [(pagina, problema)]."""
    vault = qui.parent
    pagine = {p.stem: leggi(p) for p in sorted((vault / "wiki").glob("*.md"))}
    candidate_ = {c["domanda"]: c for c in candidate(db, qui, tutte=True)}
    problemi = []
    for nome, (fm, corpo) in pagine.items():
        if domande.TAG_ENTROPIA not in valori(fm.get("tags")):
            continue
        if AVVISO.lower() not in corpo.lower():
            problemi.append((nome, f"manca l'avviso «{AVVISO}»"))
        if not valori(fm.get("riguarda")):
            problemi.append((nome, "manca `riguarda` nel frontmatter"))
        m = RISPONDE.search(corpo)
        if not m:
            problemi.append((nome, "manca la riga «Risponde a: «…»»"))
        elif m.group(1) in candidate_ and not candidate_[m.group(1)]["coperta_da"]:
            # coperta, la domanda non comparirebbe tra le candidate (un termine) o vi comparirebbe coperta
            c = candidate_[m.group(1)]
            if c["famiglia"] == "termine":
                problemi.append((nome, f"{', '.join(c['termini'])} non è né titolo né alias della pagina"))
            else:
                mancano = sorted(set(c["pagine"]) - {bersaglio(l) for l in LINK.findall(corpo)} - {nome})
                problemi.append((nome, f"la domanda risulta ancora scoperta: mancano link a {mancano}"))
        linkate = {bersaglio(l) for l in LINK.findall(corpo)} & set(pagine)
        ammesse = {f for p in linkate for f in valori(pagine[p][0].get("fonti"))}
        nuove = sorted(set(valori(fm.get("fonti"))) - ammesse)
        if nuove:
            problemi.append((nome, f"fonti che nessuna pagina linkata cita: {nuove} (fatto nuovo?)"))
    return problemi


def main():
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=qui / "graph.sqlite")
    ap.add_argument("--tutte", action="store_true", help="anche le domande già coperte")
    ap.add_argument("--max", type=int, help="al più N candidate")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--scarta", metavar="DOMANDA", help="la passa alle domande aperte per l'autore")
    ap.add_argument("--motivo", default="")
    ap.add_argument("--verifica", action="store_true", help="controlla le pagine generate per entropia")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    db = sqlite3.connect(args.db)

    if args.verifica:
        problemi = verifica(db, qui)
        for nome, p in problemi:
            print(f"  ⚠️ {nome}: {p}")
        print(f"{len(problemi)} problemi" if problemi else "pagine generate: nessun problema")
        sys.exit(1 if problemi else 0)

    if args.scarta:
        trovata = next((c for c in candidate(db, qui, tutte=True) if c["domanda"] == args.scarta), None)
        if not trovata:
            sys.exit(f"domanda non tra le candidate: «{args.scarta}»")
        archivio = domande.apri(qui / "domande.sqlite")
        archivio.execute("INSERT OR REPLACE INTO scartate VALUES (?,?,?,?)",
                         (args.scarta, args.motivo, datetime.now().isoformat(timespec="seconds"),
                          json.dumps(trovata["pagine"], ensure_ascii=False)))
        archivio.commit()
        archivio.close()
        print(f"scartata, ora è una domanda aperta per l'autore: «{args.scarta}»")
        return

    elenco = candidate(db, qui, args.tutte)[:args.max]
    if args.json:
        print(json.dumps(elenco, ensure_ascii=False, indent=2))
        return
    for i, c in enumerate(elenco, 1):
        stato = f"coperta da [[{c['coperta_da']}]]" if c["coperta_da"] else "da scrivere"
        print(f"{i}. [{c['famiglia']}] {c['domanda']}  ({stato})")
        print(f"   pagine: {', '.join(c['pagine'])}")
        for a in c["percorso"]:
            print(f"   - {a}")
    if not elenco:
        print("nessuna domanda da sintetizzare")


if __name__ == "__main__":
    main()

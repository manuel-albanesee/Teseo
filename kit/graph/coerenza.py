"""KPI di coerenza delle risposte del modello (doc/kpi-coerenza.md): nomi canonici (K1) e stabilità fra giri (K2).

Legge le risposte salvate da `misura.py --modello --out DIR` e `misura.py --hook --out DIR`: un file
`NN-<condizione>-G.json` per domanda NN, condizione (ricerca, grafo, hook) e giro G, con il campo «risposta». Non
chiama modelli: conta soltanto, sul grafo corrente.

Menzione: un nome di pagina della wiki, un alias (tabella `aliases`) o una variante grafica (tabella `varianti`)
trovato nella risposta come sequenza di parole intere, senza maiuscole e accenti (build_graph.norm). Vince la forma
più lunga, senza sovrapposizioni. Una forma che appartiene a più pagine non conta: non si sa quale sia. Un nome che è
anche parola comune (recall.PAROLE_COMUNI) conta solo scritto con la maiuscola, come nel recall. La menzione è
canonica se la forma trovata è il nome della pagina.
  K1  menzioni canoniche su tutte le menzioni, per condizione.
  K2  per ogni domanda con almeno 2 giri: media della somiglianza di Jaccard, a coppie di giri, fra gli insiemi di
      pagine nominate (due insiemi vuoti valgono 1); e se l'esito è lo stesso in tutti i giri. L'esito di un giro è
      il campo «corretta» (misura.py --modello) o, per --hook, tutte le «regex» trovate.
I file che non si leggono o senza «risposta» si elencano come illeggibili e non entrano nei numeri.

Stampa una riga per condizione, per esempio
  grafo: nomi canonici 41/50 (82%) · stabilità fra giri 0.74 · esito stabile 4/5 · 15 risposte
--json stampa gli stessi numeri in JSON. Exit 0; exit 2 se nella cartella non c'è nessuna risposta.

Uso:
  python .graph/coerenza.py --risposte <cartella> [--db .graph/graph.sqlite] [--json]
"""
import argparse
from itertools import combinations
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

from build_graph import norm
from graph_db import connect_graph, resolve_graph
from recall import PAROLE_COMUNI

QUI = Path(__file__).resolve().parent
CONDIZIONI = ("ricerca", "grafo", "hook")  # l'ordine delle righe
FILE_RISPOSTA = re.compile(r"^(\d+)-(" + "|".join(CONDIZIONI) + r")-(\d+)\.json$")


def jaccard(a, b):
    """Somiglianza di Jaccard di due insiemi: |a ∩ b| / |a ∪ b|, 1.0 se sono entrambi vuoti."""
    unione = set(a) | set(b)
    return len(set(a) & set(b)) / len(unione) if unione else 1.0


def nomi_del_grafo(db):
    """{forma normalizzata: (pagina, canonica)} dei nomi, alias e varianti delle pagine della wiki.

    canonica è True per il nome della pagina. Le forme che appartengono a più pagine si scartano."""
    pagine = {id_ for (id_,) in db.execute("SELECT id FROM entities WHERE path LIKE 'wiki/%'")}
    forme = [(id_, id_, True) for id_ in pagine]
    for tabella, colonna in (("aliases", "alias"), ("varianti", "variante")):
        try:
            forme += [(id_, nome, False) for id_, nome in db.execute(f"SELECT entity_id, {colonna} FROM {tabella}")
                      if id_ in pagine]
        except sqlite3.OperationalError:  # graph.sqlite di una versione senza la tabella
            pass
    proprietari, canoniche = {}, set()
    for id_, nome, canonica in forme:
        n = norm(nome)
        if not n:
            continue
        proprietari.setdefault(n, set()).add(id_)
        if canonica:
            canoniche.add(n)
    return {n: (next(iter(p)), n in canoniche) for n, p in proprietari.items() if len(p) == 1}


def parole(testo):
    """Le parole del testo senza accenti, con le maiuscole originali: lowercase danno le parole di norm."""
    testo = "".join(c for c in unicodedata.normalize("NFKD", str(testo)) if not unicodedata.combining(c))
    return re.findall(r"[A-Za-z0-9]+", testo)


def menzioni(testo, nomi):
    """[(pagina, canonica)] delle menzioni di pagina nel testo, in ordine; nomi è il dizionario di nomi_del_grafo."""
    originali = parole(testo)
    basse = [w.lower() for w in originali]
    massimo = max((len(n.split()) for n in nomi), default=0)
    trovate = []  # (inizio, fine, forma)
    for i in range(len(basse)):
        for lunghezza in range(1, min(massimo, len(basse) - i) + 1):
            forma = " ".join(basse[i:i + lunghezza])
            if forma not in nomi:
                continue
            if forma in PAROLE_COMUNI and not originali[i][:1].isupper():
                continue
            trovate.append((i, i + lunghezza, forma))
    prese, occupate = [], set()
    for inizio, fine, forma in sorted(trovate, key=lambda t: (t[0] - t[1], t[0])):  # più lunghe prima
        if occupate.isdisjoint(range(inizio, fine)):
            occupate.update(range(inizio, fine))
            prese.append((inizio, forma))
    return [nomi[forma] for _, forma in sorted(prese)]


def leggi_risposte(cartella):
    """Le risposte di una cartella --out: ({(domanda, condizione): [giri in ordine]}, [file illeggibili]).

    Ogni giro è {"giro", "risposta", "esito"}; esito è «corretta», o tutte le «regex», o None se non c'è."""
    risposte, illeggibili = {}, []
    for percorso in sorted(Path(cartella).iterdir()):
        trovato = FILE_RISPOSTA.match(percorso.name)
        if not trovato:
            continue
        try:
            dati = json.loads(percorso.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dati = None
        if not isinstance(dati, dict) or not isinstance(dati.get("risposta"), str):
            illeggibili.append(percorso.name)
            continue
        if "corretta" in dati:
            esito = bool(dati["corretta"])
        elif isinstance(dati.get("regex"), list):
            esito = all(dati["regex"])
        else:
            esito = None
        chiave = (int(trovato.group(1)), trovato.group(2))
        risposte.setdefault(chiave, []).append({"giro": int(trovato.group(3)), "risposta": dati["risposta"],
                                                "esito": esito})
    for giri in risposte.values():
        giri.sort(key=lambda g: g["giro"])
    return risposte, illeggibili


def coerenza_nomi(risposte, nomi):
    """K1 su una lista di risposte ({"risposta"}): {"menzioni", "canoniche", "quota"}; quota None senza menzioni."""
    trovate = [m for r in risposte for m in menzioni(r["risposta"], nomi)]
    canoniche = sum(1 for _, canonica in trovate if canonica)
    return {"menzioni": len(trovate), "canoniche": canoniche, "quota": canoniche / len(trovate) if trovate else None}


def stabilita_giri(risposte, nomi):
    """K2 per condizione: {condizione: {"domande", "jaccard_medio", "esito_stabile"}}, sulle domande con 2+ giri."""
    esito = {}
    ordine = lambda c: (CONDIZIONI.index(c) if c in CONDIZIONI else len(CONDIZIONI), c)  # noqa: E731
    for condizione in sorted({c for _, c in risposte}, key=ordine):
        medie, stabili = [], 0
        for (_, c), giri in sorted(risposte.items()):
            if c != condizione or len(giri) < 2:
                continue
            insiemi = [{p for p, _ in menzioni(g["risposta"], nomi)} for g in giri]
            coppie = [jaccard(a, b) for a, b in combinations(insiemi, 2)]
            medie.append(sum(coppie) / len(coppie))
            stabili += len({g["esito"] for g in giri}) == 1
        esito[condizione] = {"domande": len(medie), "jaccard_medio": sum(medie) / len(medie) if medie else None,
                             "esito_stabile": stabili}
    return esito


def misura(risposte, nomi):
    """K1 e K2 per condizione: {condizione: {"coerenza", "stabilita", "risposte"}}, nell'ordine di CONDIZIONI."""
    stabilita = stabilita_giri(risposte, nomi)
    return {c: {"coerenza": coerenza_nomi([g for (_, cc), giri in sorted(risposte.items()) if cc == c
                                           for g in giri], nomi),
                "stabilita": s,
                "risposte": sum(len(giri) for (_, cc), giri in risposte.items() if cc == c)}
            for c, s in stabilita.items()}


def riga(condizione, dati):
    """La riga stampata per una condizione."""
    k1, k2 = dati["coerenza"], dati["stabilita"]
    quota = f"{100 * k1['quota']:.0f}%" if k1["quota"] is not None else "n/d"
    jacc = f"{k2['jaccard_medio']:.2f}" if k2["jaccard_medio"] is not None else "n/d"
    return (f"{condizione}: nomi canonici {k1['canoniche']}/{k1['menzioni']} ({quota}) · stabilità fra giri {jacc}"
            f" · esito stabile {k2['esito_stabile']}/{k2['domande']} · {dati['risposte']} risposte")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--risposte", type=Path, required=True, help="la cartella --out di misura.py")
    ap.add_argument("--db", type=Path, default=QUI / "graph.sqlite")
    ap.add_argument("--json", action="store_true", help="i numeri in JSON")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not args.risposte.is_dir():
        ap.error(f"{args.risposte} non è una cartella")
    if not resolve_graph(args.db).exists():
        sys.exit(f"{args.db} non esiste: lanciare prima .graph/build_graph.py")
    db = connect_graph(args.db)
    try:
        nomi = nomi_del_grafo(db)
    finally:
        db.close()
    risposte, illeggibili = leggi_risposte(args.risposte)
    for nome in illeggibili:
        print(f"illeggibile: {nome}", file=sys.stderr)
    if not risposte:
        print(f"nessuna risposta in {args.risposte} (servono i file NN-<condizione>-G.json di misura.py --out)",
              file=sys.stderr)
        sys.exit(2)
    dati = misura(risposte, nomi)
    if args.json:
        print(json.dumps({"condizioni": dati, "illeggibili": illeggibili}, ensure_ascii=False, indent=2))
        return
    for condizione, valori in dati.items():
        print(riga(condizione, valori))


if __name__ == "__main__":
    main()

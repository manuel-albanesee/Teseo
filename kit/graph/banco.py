"""Materiale e controllo del banco di misura del recall: le domande che il vault deve saper trovare.

Il banco (.graph/banco.json) è una lista di {"domanda", "attese", "origine", "note", "tipo"}: la domanda, le pagine che
il recall deve portare, da dove viene (sintesi, hub, isolata, atteso_ko, manuale), perché e, facoltativo, il tipo di
domanda: «locale» (un'entità, predefinito) o «globale» (un insieme di pagine), che misura.py riepiloga a parte. misura.py lo misura nella
sezione BANCO, che è informativa e non fa uscire con 1. Le domande le scrive chi usa il banco: questo script non ne crea.
  --semi      scrive .graph/banco_semi.json, il materiale da cui scrivere le domande:
              (a) le domande di sintesi.py --tutte con le pagine della risposta: dall'uscita JSON di sintesi.py,
                  o, se non si ottiene, importando la sua candidate();
              (b) i 15 hub più citati con menziona che non hanno relazioni tipizzate in entrata;
              (c) le pagine isolate nel grafo tipizzato: nessuna relazione tipizzata in entrata né in uscita.
              Per ogni pagina: id, tipo, descrizione, alias, i 10 vicini più collegati e il percorso del file.
  --verifica  controlla banco.json. ERRORE (exit 1): pagina attesa inesistente, domanda doppia, voce malformata,
              tipo diverso da locale e globale.
              AVVISO (exit 0): la domanda usa metà delle parole del titolo di una pagina attesa, e il test sarebbe
              banale. Conta solo il titolo, cioè il nome della pagina, non gli alias; non vale per atteso_ko.

Uso:
  python .graph/banco.py --semi
  python .graph/banco.py --verifica
"""
import argparse
import json
import os
import sqlite3
from graph_db import connect_graph, resolve_graph
import subprocess
import sys
from pathlib import Path

import sintesi
from build_graph import norm
from recall import GENERICHE, radici

QUI = Path(__file__).resolve().parent
N_HUB = 15      # hub da includere in --semi
N_VICINI = 10   # vicini per pagina
ORIGINI = {"sintesi", "hub", "isolata", "atteso_ko", "manuale"}
TIPI_DOMANDA = ("locale", "globale")  # uguale a misura.TIPI_DOMANDA (misura importa hook e modelli: qui non serve)


def connetti(percorso):
    if not resolve_graph(percorso).exists():
        sys.exit(f"{percorso} non esiste: lanciare prima .graph/build_graph.py")
    return connect_graph(percorso)


def relazioni_tipizzate(db):
    """(sorgente, destinazione, tipo) delle relazioni tipizzate: tutte tranne menziona e documentato_in."""
    segnaposto = ",".join("?" * len(GENERICHE))
    return db.execute(f"SELECT source_id, target_id, type FROM relations WHERE type NOT IN ({segnaposto})",
                      sorted(GENERICHE)).fetchall()


def hub(db, pagine, tipizzate):
    """Le pagine più citate con menziona (in entrata) che non hanno relazioni tipizzate in entrata."""
    con_tipizzate_in = {t for _, t, _ in tipizzate}
    citate = db.execute("SELECT target_id, COUNT(*) FROM relations WHERE type = 'menziona' GROUP BY target_id").fetchall()
    ordine = sorted(citate, key=lambda c: (-c[1], c[0]))
    return [p for p, _ in ordine if p in pagine and p not in con_tipizzate_in][:N_HUB]


def isolate(pagine, tipizzate):
    """Le pagine senza relazioni tipizzate né in entrata né in uscita."""
    collegate = {s for s, _, _ in tipizzate} | {t for _, t, _ in tipizzate}
    return sorted(p for p in pagine if p not in collegate)


def indice_vicini(db, pagine):
    """{pagina: {vicino: [relazioni]}} fra pagine di wiki/ (le fonti non sono vicini). «usa →»: la pagina linka il
    vicino; «usa ←»: il vicino linka la pagina."""
    indice = {}
    for s, t, tipo in db.execute("SELECT source_id, target_id, type FROM relations"):
        if s in pagine and t in pagine:
            indice.setdefault(s, {}).setdefault(t, []).append(f"{tipo} →")
            indice.setdefault(t, {}).setdefault(s, []).append(f"{tipo} ←")
    return indice


def vicini_di(indice, pagina):
    """I N_VICINI vicini più collegati: prima quelli con relazioni tipizzate, poi per numero di relazioni."""
    collegati = indice.get(pagina, {})
    ordine = sorted(collegati, key=lambda v: (-sum(not r.startswith("menziona") for r in collegati[v]),
                                              -len(collegati[v]), v))
    return [{"id": v, "relazioni": collegati[v]} for v in ordine[:N_VICINI]]


def domande_sintesi(db_path):
    """Le candidate di sintesi.py --tutte: dalla sua uscita JSON; se non si ottiene, da sintesi.candidate()."""
    try:
        esito = subprocess.run([sys.executable, str(QUI / "sintesi.py"), "--db", str(db_path), "--tutte", "--json"],
                               capture_output=True, timeout=300, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if esito.returncode == 0:
            return json.loads(esito.stdout.decode("utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    db = connect_graph(db_path)
    try:
        return sintesi.candidate(db, QUI, tutte=True)
    finally:
        db.close()


def scrivi_semi(db_path, db, out):
    """Scrive banco_semi.json: le domande di sintesi, gli hub e le pagine isolate, con le pagine descritte."""
    pagine = {id_: (tipo, descr, path) for id_, tipo, descr, path in
              db.execute("SELECT id, tipo, descrizione, path FROM entities WHERE tipo IS NOT 'fonte'")}
    tipizzate = relazioni_tipizzate(db)
    voci = domande_sintesi(db_path)
    hub_ids = hub(db, pagine, tipizzate)
    isolate_ids = isolate(pagine, tipizzate)
    indice = indice_vicini(db, pagine)
    alias = {}
    for id_, a in db.execute("SELECT entity_id, alias FROM aliases ORDER BY alias"):
        alias.setdefault(id_, []).append(a)
    usate = set(hub_ids) | set(isolate_ids) | {p for v in voci for p in v["pagine"]}
    dettagli = {}
    for p in sorted(usate):
        tipo, descr, path = pagine.get(p, (None, None, None))
        dettagli[p] = {"id": p, "tipo": tipo, "descrizione": descr, "alias": alias.get(p, []),
                       "vicini": vicini_di(indice, p), "percorso": path}
    dati = {
        "conteggi": {"sintesi": len(voci), "hub": len(hub_ids), "isolate": len(isolate_ids), "pagine": len(dettagli)},
        "sintesi": [{"domanda": v["domanda"], "famiglia": v["famiglia"], "coperta_da": v["coperta_da"],
                     "pagine": v["pagine"]} for v in voci],
        "hub": hub_ids,
        "isolate": isolate_ids,
        "pagine": dettagli,
    }
    out.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"scritto {out}: {len(voci)} domande di sintesi, {len(hub_ids)} hub, {len(isolate_ids)} pagine isolate, "
          f"{len(dettagli)} pagine descritte")


def eco_del_titolo(domanda, pagina):
    """True se la domanda ha almeno metà delle radici del titolo della pagina (recall.radici)."""
    titolo = radici(pagina)
    return bool(titolo) and 2 * len(titolo & radici(domanda)) >= len(titolo)


def verifica(db, percorso):
    """Problemi di banco.json: [(livello, testo)], con livello ERRORE o AVVISO."""
    if not percorso.exists():
        return [("ERRORE", f"{percorso.name} non esiste")]
    try:
        voci = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [("ERRORE", f"{percorso.name} non si legge: {e}")]
    if not isinstance(voci, list):
        return [("ERRORE", f"{percorso.name}: serve una lista di oggetti")]
    pagine = {id_ for (id_,) in db.execute("SELECT id FROM entities")}
    problemi, viste = [], {}
    for i, voce in enumerate(voci, 1):
        domanda = voce.get("domanda") if isinstance(voce, dict) else None
        if not isinstance(domanda, str) or not domanda.strip():
            problemi.append(("ERRORE", f"voce {i}: manca «domanda» o non è un testo"))
            continue
        dove = f"voce {i} «{domanda[:50]}»"
        attese = voce.get("attese")
        if not isinstance(attese, list) or not all(isinstance(p, str) for p in attese):
            problemi.append(("ERRORE", f"{dove}: «attese» deve essere una lista di nomi di pagina"))
            attese = []
        if voce.get("tipo", "locale") not in TIPI_DOMANDA:
            problemi.append(("ERRORE", f"{dove}: «tipo» deve essere uno tra {', '.join(TIPI_DOMANDA)}"))
        origine = voce.get("origine")
        if not isinstance(origine, str) or origine not in ORIGINI:
            problemi.append(("ERRORE", f"{dove}: «origine» deve essere una tra {', '.join(sorted(ORIGINI))}"))
        if not isinstance(voce.get("note"), str):
            problemi.append(("ERRORE", f"{dove}: manca «note» (testo, anche vuoto)"))
        chiave = norm(domanda)
        if chiave in viste:
            problemi.append(("ERRORE", f"{dove}: domanda uguale alla voce {viste[chiave]}"))
        viste.setdefault(chiave, i)
        for p in attese:
            if p not in pagine:
                problemi.append(("ERRORE", f"{dove}: pagina attesa inesistente «{p}»"))
        # i casi atteso_ko misurano proprio le varianti del titolo (rilasciare/rilascio): l'eco è voluta
        eco = [p for p in attese if p in pagine and origine != "atteso_ko" and eco_del_titolo(domanda, p)]
        if eco:
            nomi = ", ".join(f"«{p}»" for p in eco)
            problemi.append(("AVVISO", f"{dove}: usa le parole del titolo di {nomi}, il test sarebbe banale"))
    return problemi


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=QUI / "graph.sqlite")
    ap.add_argument("--banco", type=Path, default=QUI / "banco.json")
    ap.add_argument("--semi", action="store_true", help="scrive banco_semi.json: il materiale per le domande")
    ap.add_argument("--verifica", action="store_true", help="controlla banco.json (exit 1 se ci sono errori)")
    args = ap.parse_args()
    if args.semi == args.verifica:
        ap.error("serve --semi oppure --verifica")
    sys.stdout.reconfigure(encoding="utf-8")
    db = connetti(args.db)
    if args.semi:
        scrivi_semi(db.graph_path, db, QUI / "banco_semi.json")
        return
    problemi = verifica(db, args.banco)
    for livello, testo in problemi:
        print(f"{livello}: {testo}")
    errori = sum(1 for livello, _ in problemi if livello == "ERRORE")
    avvisi = len(problemi) - errori
    print(f"banco: {errori} {'errore' if errori == 1 else 'errori'}, {avvisi} {'avviso' if avvisi == 1 else 'avvisi'}"
          if problemi else "banco: nessun problema")
    sys.exit(1 if errori else 0)


if __name__ == "__main__":
    main()

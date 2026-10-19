"""Domande aperte del vault: quelle a cui il vault non sa rispondere, e che vanno rivolte all'autore.

Le domande a cui il vault risponde già, mettendo insieme più pagine, non sono qui: le elenca sintesi.py e
diventano pagine di sintesi durante il lint. Qui restano quattro segnali, calcolati senza LLM:
  punto      voce di "## Punti aperti nel vault" in index.md che linka la pagina
  verifica   riga della pagina con il marcatore ⚠️ "da verificare" ancora applicato
  referente  sistema, processo o progetto senza relazione `referente` e non parte di altro
             (se il testo lo dice, il lint aggiunge la relazione e la domanda sparisce)
  scartata   domanda di sintesi.py che il lint non ha potuto chiudere con i dati del vault (`--scarta`)
Le pagine generate per entropia (tag `entropia`) non contano: ripetono i ⚠️ delle pagine da cui vengono.

recall_hook.py ne mette al massimo MAX nel contesto, solo per le pagine riconosciute nel prompt,
e mai due volte la stessa nella stessa sessione (tabella `poste` in domande.sqlite).
Con GRAFO_SENZA_DOMANDE=1 (lo imposta misura.py) non si calcolano.

Ogni domanda rilevata è archiviata nella tabella `aperte` di domande.sqlite, con stato e date. Il calcolo dalle
pagine comanda: una domanda che il calcolo non rileva più passa a `chiusa` (non sparisce), una che riappare si
riapre. La chiave è segnale + pagina + prime parole del testo, non il testo intero: ritoccare la riga non la
trasforma in una domanda nuova. Punti aperti e domande scartate non hanno la pagina nella chiave: sono una domanda
sola anche quando linkano più pagine, e un rinvio le nasconde ovunque. Un rinvio (--rinvia) nasconde la domanda per
GIORNI_RINVIO giorni; dopo MAX_RINVII rinvii non si rinvia più, la domanda esce con l'avviso «rinviata N volte» e il
lint la riporta all'autore (--da-decidere), perché il recall la mostrerebbe solo parlando delle sue pagine.

Uso:
  python .graph/domande.py                 tutte le domande aperte del vault, per segnale
  python .graph/domande.py "Rilascio"        le domande per le pagine riconosciute nel testo
  python .graph/domande.py --stato         tutte le domande archiviate, per stato (aperta, rinviata, chiusa)
  python .graph/domande.py --rinvia TESTO  rinvia di 30 giorni la domanda con chiave TESTO, o l'unica che lo contiene
  python .graph/domande.py --da-decidere   le domande rinviate 3 volte, da portare all'autore nel lint
  python .graph/domande.py --json [--strutturali]   le domande aperte in JSON, per la skill delle lacune
  python .graph/domande.py --risposta CHIAVE --testo "..." [--pagine "A · B"]   archivia la risposta dell'autore
  python .graph/domande.py --risposte      le risposte non ancora consolidate dal lint (--consolida le chiude)
"""
import argparse
import datetime
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from build_graph import CODICE, LINK, bersaglio, leggi, norm, valori

QUI = Path(__file__).resolve().parent
TAG_ENTROPIA = "entropia"  # pagine scritte dal lint con sintesi.py
MAX = 3
GIORNI_RINVIO = 30  # un rinvio vale 30 giorni, poi la domanda torna aperta
MAX_RINVII = 3      # al terzo rinvio la domanda va risolta: si segnala e non si rinvia più
PAROLE_CHIAVE = 6   # parole iniziali del testo che identificano una domanda anche se la riga viene ritoccata
PER_DOMANDA = {"punto", "scartata"}  # una voce dell'indice o una domanda scartata: una sola, anche se linka più pagine
MIN_PAGINE = 3
MIN_AREE = 3
ORDINE = ("scartata", "punto", "verifica", "referente")
CON_REFERENTE = {"sistema", "processo", "progetto"}
TERMINE = re.compile(r"`([A-Za-z][\w.]{4,40})`")
HASH = re.compile(r"^[0-9a-f]{7,40}$")
# Nomi di framework o di file di codice: citati spesso, ma non sono concetti del vault (da adattare)
NON_TERMINI = {"SqlParameter", "Generics.cs"}


def pulisci(testo, lunghezza=170):
    testo = re.sub(r"\[\[([^\]|]+?)(?:\\?\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), testo)
    testo = re.sub(r"[*>#]|^\s*-\s*", "", testo).replace("⚠️", "").strip(" |")
    testo = re.sub(r"\s+", " ", testo)
    return testo if len(testo) <= lunghezza else testo[:lunghezza].rsplit(" ", 1)[0] + "…"


def punti_aperti(vault):
    indice = vault / "index.md"
    testo = indice.read_text(encoding="utf-8") if indice.exists() else ""
    m = re.search(r"^## Punti aperti.*?$(.*?)(?=^## |\Z)", testo, re.M | re.S)
    voci, corrente = [], None
    for riga in (m.group(1) if m else "").splitlines():
        if riga.startswith("- "):
            corrente = [riga]
            voci.append(corrente)
        elif corrente is not None and riga.strip():
            corrente.append(riga)
    return [" ".join(v) for v in voci]


def pagine_fonte(vault):
    """Le pagine di wiki/ tranne quelle generate per entropia, che non sono fonte di domande."""
    pagine = {p.stem: leggi(p) for p in sorted((vault / "wiki").glob("*.md"))}
    return {n: (fm, c) for n, (fm, c) in pagine.items() if TAG_ENTROPIA not in valori(fm.get("tags"))}


def termini(db, vault):
    """Identificatori senza pagina né alias, citati in 3+ pagine di 3+ aree: [(termini, pagine)].

    Area = la pagina parte_di, altrimenti la pagina stessa: i nomi interni a un solo sistema, come i
    componenti di un modulo, restano fuori. Termini citati sempre insieme (i campi di una tabella,
    due codici profilo) fanno una voce sola. La domanda la gestisce sintesi.py, perché le pagine che li
    citano di solito bastano a dire cosa sono.
    """
    nomi = {norm(p.stem) for p in (vault / "wiki").glob("*.md")}
    nomi |= {norm(a) for (a,) in db.execute("SELECT alias FROM aliases")}
    area = dict(db.execute("SELECT source_id, target_id FROM relations WHERE type = 'parte_di'"))
    citato = defaultdict(set)
    for nome, (_, corpo) in pagine_fonte(vault).items():
        for t in set(TERMINE.findall(re.sub(r"^```.*?^```", "", corpo, flags=re.M | re.S))):
            if not HASH.match(t) and not t.islower() and t not in NON_TERMINI and norm(t) not in nomi:  # `count`, `detail`: parole, non nomi
                citato[t].add(nome)
    insieme = defaultdict(list)
    for t, dove in sorted(citato.items()):
        if len(dove) >= MIN_PAGINE and len({area.get(p, p) for p in dove}) >= MIN_AREE:
            insieme[frozenset(dove)].append(t)
    return [(ts, sorted(dove)) for dove, ts in insieme.items()]


def apri(path=QUI / "domande.sqlite"):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS poste (sessione TEXT, testo TEXT, quando TEXT DEFAULT CURRENT_TIMESTAMP,
                                          UNIQUE (sessione, testo));
        CREATE TABLE IF NOT EXISTS scartate (domanda TEXT PRIMARY KEY, motivo TEXT, quando TEXT, pagine TEXT);
        CREATE TABLE IF NOT EXISTS aperte (chiave TEXT PRIMARY KEY, segnale TEXT, pagina TEXT, testo TEXT,
                                           stato TEXT DEFAULT 'aperta', prima_vista TEXT, ultima_vista TEXT,
                                           fino_al TEXT, rinvii INTEGER DEFAULT 0, chiusa_il TEXT);
        CREATE TABLE IF NOT EXISTS risposte (id INTEGER PRIMARY KEY, chiave TEXT, segnale TEXT, domanda TEXT,
                                             risposta TEXT, pagine TEXT, quando TEXT, consolidata INTEGER DEFAULT 0);
    """)
    if "pagine" not in {r[1] for r in db.execute("PRAGMA table_info(scartate)")}:
        db.execute("ALTER TABLE scartate ADD COLUMN pagine TEXT")
    return db


def stabile(testo):
    """Le prime parole del testo, senza maiuscole, accenti e punteggiatura."""
    return " ".join(re.findall(r"\w+", norm(pulisci(testo)))[:PAROLE_CHIAVE])


def rileva(db, vault):
    """{pagina: [(segnale, testo, chiave)]}, in ordine di segnale. La chiave è segnale|pagina|parte stabile,
    senza pagina per i segnali PER_DOMANDA: la stessa domanda su più pagine ha una chiave sola."""
    pagine = pagine_fonte(vault)
    domande = defaultdict(list)
    viste = {}  # chiave → testo

    def aggiungi(pagina, segnale, testo, parte):
        base = f"{segnale}|{'' if segnale in PER_DOMANDA else pagina}|{parte}"
        chiave, n = base, 2
        while viste.get(chiave, testo) != testo:  # due righe diverse con le stesse prime parole
            chiave = f"{base}#{n}"
            n += 1
        viste[chiave] = testo
        domande[pagina].append((segnale, testo, chiave))

    archivio = apri()
    try:
        for domanda, motivo, elenco in archivio.execute("SELECT domanda, motivo, pagine FROM scartate ORDER BY quando"):
            for p in json.loads(elenco or "[]") or ["(vault)"]:  # su ogni pagina della risposta mancata
                aggiungi(p, "scartata", f"«{domanda}» Il vault non basta a rispondere: {motivo}", norm(domanda))
    finally:
        archivio.close()

    for voce in punti_aperti(vault):
        for pagina in dict.fromkeys(bersaglio(l) for l in LINK.findall(voce)):
            if pagina in pagine:
                aggiungi(pagina, "punto", f"Punto aperto: «{pulisci(voce)}»", stabile(voce))

    for nome, (_, corpo) in pagine.items():
        for riga in corpo.splitlines():
            # Conta solo il marcatore applicato: non quello tra backtick ("cade un `⚠️ da verificare`"),
            # non quello barrato (~~…~~ Risolto), non "la prima cosa da verificare" senza ⚠️
            viva = re.sub(r"~~.*?~~", "", CODICE.sub("", riga))
            if "⚠️" in viva and "da verificare" in viva.lower() and "risolt" not in viva.lower():
                aggiungi(nome, "verifica", f"In [[{nome}]] resta da verificare: «{pulisci(riga)}»", stabile(riga))

    # Una parte (parte_di) ha il referente del tutto: la domanda vale solo per chi non è parte di nulla
    area = dict(db.execute("SELECT source_id, target_id FROM relations WHERE type = 'parte_di'"))
    con_ref = {s for (s,) in db.execute("SELECT source_id FROM relations WHERE type = 'referente'")}
    for nome, tipo in db.execute("SELECT id, tipo FROM entities"):
        if tipo in CON_REFERENTE and nome in pagine and nome not in con_ref and nome not in area:
            aggiungi(nome, "referente", f"Chi è il referente di [[{nome}]]? "
                                        f"(nessuna relazione `referente` nel frontmatter)", "")

    for nome in domande:
        domande[nome].sort(key=lambda d: ORDINE.index(d[0]))
    return domande


def calcola(db, vault):
    """{pagina: [(segnale, testo)]}, in ordine di segnale."""
    return {p: [(s, t) for s, t, _ in elenco] for p, elenco in rileva(db, vault).items()}


def oggi():
    return datetime.date.today().isoformat()


def sincronizza(archivio, rilevate):
    """Allinea la tabella `aperte` a ciò che il calcolo rileva ora. Il calcolo comanda.

    nuova → aperta; riapparsa dopo `chiusa` → riaperta; rinvio scaduto → aperta; non più rilevata → chiusa.
    Il testo si aggiorna: se la riga è stata ritoccata la domanda resta la stessa (stessa chiave).
    Ritorna {chiave: (stato, rinvii)} per le domande rilevate.
    """
    giorno = oggi()
    esistenti = {c: (stato, fino, n) for c, stato, fino, n in
                 archivio.execute("SELECT chiave, stato, fino_al, rinvii FROM aperte")}
    stato_di = {}
    attuali = {}  # chiave → (segnale, testo, pagine): una domanda può stare su più pagine
    for pagina, elenco in rilevate.items():
        for segnale, testo, chiave in elenco:
            attuali.setdefault(chiave, (segnale, testo, []))[2].append(pagina)
    for chiave, (segnale, testo, pagine) in attuali.items():
        pagina = " · ".join(dict.fromkeys(pagine))
        if chiave not in esistenti:
            archivio.execute("INSERT INTO aperte (chiave, segnale, pagina, testo, stato, prima_vista, ultima_vista) "
                             "VALUES (?,?,?,?, 'aperta', ?, ?)", (chiave, segnale, pagina, testo, giorno, giorno))
            stato_di[chiave] = ("aperta", 0)
            continue
        stato, fino, rinvii = esistenti[chiave]
        if stato == "chiusa" or (stato == "rinviata" and (fino or "") <= giorno):
            stato, fino = "aperta", None
        archivio.execute("UPDATE aperte SET pagina=?, testo=?, stato=?, fino_al=?, chiusa_il=NULL, ultima_vista=? "
                         "WHERE chiave=?", (pagina, testo, stato, fino, giorno, chiave))
        stato_di[chiave] = (stato, rinvii)
    for chiave, (stato, _, _) in esistenti.items():
        if chiave not in attuali and stato != "chiusa":
            archivio.execute("UPDATE aperte SET stato='chiusa', fino_al=NULL, chiusa_il=? WHERE chiave=?", (giorno, chiave))
    archivio.commit()
    return stato_di


def rinvia(archivio, cerca):
    """Rinvia di GIORNI_RINVIO giorni la domanda non chiusa con chiave `cerca`, o l'unica che lo contiene
    (nella chiave o nel testo)."""
    trovate = archivio.execute("SELECT chiave, rinvii FROM aperte WHERE stato != 'chiusa' AND chiave = ?",
                               (cerca,)).fetchall() or \
              archivio.execute("SELECT chiave, rinvii FROM aperte WHERE stato != 'chiusa' "
                               "AND (chiave LIKE ? OR testo LIKE ?)", (f"%{cerca}%", f"%{cerca}%")).fetchall()
    if len(trovate) != 1:
        esito = "precisa meglio" if trovate else "nessuna da rinviare"
        return f"{len(trovate)} domande corrispondono a «{cerca}»: {esito}" + "".join(f"\n  - {c}" for c, _ in trovate)
    chiave, rinvii = trovate[0]
    if rinvii >= MAX_RINVII:
        return (f"{chiave} è già stata rinviata {rinvii} volte: non si rinvia più. Risolvila, oppure correggi la pagina "
                f"perché il calcolo non la rilevi più.")
    fino = (datetime.date.today() + datetime.timedelta(days=GIORNI_RINVIO)).isoformat()
    archivio.execute("UPDATE aperte SET stato='rinviata', fino_al=?, rinvii=? WHERE chiave=?", (fino, rinvii + 1, chiave))
    archivio.commit()
    avviso = " Terzo rinvio: alla scadenza va risolta." if rinvii + 1 >= MAX_RINVII else ""
    return f"Rinviata fino al {fino} ({rinvii + 1}/{MAX_RINVII}): {chiave}.{avviso}"


def vicine(db, pagine):
    """Le pagine del prompt, poi i vicini per relazione tipizzata, poi le altre parti dello stesso tutto.

    Così una pagina senza lacune proprie (Modulo fatture) porta quelle dei processi che la riguardano, e una
    pagina di sintesi (Prerequisiti del rilascio) quelle delle pagine sorelle.
    """
    ordine = list(pagine)
    def aggiungi(nuove):
        ordine.extend(p for p in nuove if p not in ordine)
    segnaposto = ",".join("?" * len(pagine))
    if pagine:
        aggiungi(s for (s,) in db.execute(
            f"SELECT DISTINCT CASE WHEN source_id IN ({segnaposto}) THEN target_id ELSE source_id END "
            f"FROM relations JOIN entities e ON e.id = CASE WHEN source_id IN ({segnaposto}) THEN target_id ELSE source_id END "
            f"WHERE (source_id IN ({segnaposto}) OR target_id IN ({segnaposto})) "
            f"AND type NOT IN ('menziona', 'documentato_in') AND e.tipo != 'persona' ORDER BY 1",
            pagine * 4))
        aggiungi(s for (s,) in db.execute(
            f"SELECT source_id FROM relations WHERE type = 'parte_di' AND target_id IN "
            f"(SELECT target_id FROM relations WHERE type = 'parte_di' AND source_id IN ({segnaposto})) ORDER BY 1",
            pagine))
    return ordine


def per_pagine(db, vault, pagine, sessione="", archivio=None, massimo=MAX):
    """Al più `massimo` domande, a turno sulle pagine (vedi vicine), saltando quelle già poste nella sessione."""
    pagine = vicine(db, pagine)
    rilevate = rileva(db, vault)
    avvisi = {}  # testo → prefisso per le domande già rinviate MAX_RINVII volte
    if archivio:
        stato_di = sincronizza(archivio, rilevate)
        tutte = {}
        for p, elenco in rilevate.items():
            tutte[p] = []
            for s, t, c in elenco:
                stato, rinvii = stato_di[c]
                if stato == "rinviata":
                    continue  # nascosta fino alla scadenza
                if rinvii >= MAX_RINVII:
                    avvisi[t] = f"(rinviata {rinvii} volte: risolvila) "
                tutte[p].append((s, t, c))
    else:
        tutte = rilevate
    gia = {t for (t,) in archivio.execute("SELECT testo FROM poste WHERE sessione = ?", (sessione,))} if archivio else set()
    code = [[d for d in tutte.get(p, []) if d[1] not in gia] for p in pagine]
    scelte = []
    while len(scelte) < massimo and any(code):
        for coda in code:
            while coda and coda[0][1] in {s[1] for s in scelte}:
                coda.pop(0)  # la stessa voce può arrivare da due pagine
            if coda and len(scelte) < massimo:
                scelte.append(coda.pop(0))
    if archivio:
        archivio.executemany("INSERT OR IGNORE INTO poste (sessione, testo) VALUES (?, ?)",
                             [(sessione, t) for _, t, _ in scelte])
        archivio.commit()
    return [(s, avvisi.get(t, "") + t, c) for s, t, c in scelte]


def formatta(scelte):
    righe = ["Domande aperte del vault su queste pagine (al più una, a fine risposta, solo se pertinente; "
             "se l'autore risponde, proporre di registrarla come [nota-utente] nella pagina indicata o in una nuova; "
             f"se dice che per ora non può o non vuole rispondere, rinviarla di {GIORNI_RINVIO} giorni con "
             "`python .graph/domande.py --rinvia \"<chiave>\"` e riportargli l'esito del comando):"]
    righe += [f"- [{segnale}] {testo} (chiave: {chiave})" for segnale, testo, chiave in scelte]
    return "\n".join(righe)


def strutturali(db, vault):
    """Lacune di struttura, non archiviate in `aperte` né proposte dal recall: sistemi, processi e progetti
    senza nessuna relazione tipizzata in uscita oltre a `referente`. Le chiede solo la skill delle lacune."""
    pagine = pagine_fonte(vault)
    isolate = db.execute("SELECT id FROM entities e WHERE tipo IN ('sistema', 'processo', 'progetto') AND NOT EXISTS "
                         "(SELECT 1 FROM relations r WHERE r.source_id = e.id "
                         "AND r.type NOT IN ('menziona', 'documentato_in', 'referente')) ORDER BY id")
    return [{"chiave": f"relazioni|{n}|", "segnale": "relazioni", "pagine": [n], "rinvii": 0,
             "testo": f"[[{n}]] non dichiara relazioni tipizzate: di cosa fa parte, cosa usa o richiede, "
                      f"cosa precede o sostituisce?"} for (n,) in isolate if n in pagine]


def da_porre(db, vault, archivio):
    """Le domande aperte e non rinviate, nell'ordine in cui la skill delle lacune le pone: prima quelle da
    decidere (rinviate MAX_RINVII volte), poi per segnale (ORDINE) e per pagina, così si resta su un argomento."""
    sincronizza(archivio, rileva(db, vault))
    righe = archivio.execute("SELECT chiave, segnale, testo, pagina, rinvii, prima_vista FROM aperte "
                             "WHERE stato = 'aperta'").fetchall()
    domande = [{"chiave": c, "segnale": s, "testo": t, "pagine": p.split(" · "), "rinvii": r, "prima_vista": pv}
               for c, s, t, p, r, pv in righe]
    return sorted(domande, key=lambda d: (d["rinvii"] < MAX_RINVII, ORDINE.index(d["segnale"]), d["pagine"][0]))


def registra(archivio, chiave, risposta, pagine="", domanda=None):
    """Archivia la risposta dell'autore (tabella `risposte`): resta anche dopo che la domanda si è chiusa.

    Una domanda scartata esce da `scartate`: sintesi.py la ripropone e il lint, ora che la pagina ha la
    risposta, scrive la pagina per entropia. Le altre si chiudono da sole quando la pagina è corretta.
    """
    riga = archivio.execute("SELECT segnale, testo FROM aperte WHERE chiave = ?", (chiave,)).fetchone()
    segnale, testo = riga if riga else (chiave.split("|", 1)[0], domanda or chiave)
    archivio.execute("INSERT INTO risposte (chiave, segnale, domanda, risposta, pagine, quando) VALUES (?,?,?,?,?,?)",
                     (chiave, segnale, domanda or testo, risposta, pagine, datetime.datetime.now().isoformat(timespec="seconds")))
    if segnale == "scartata":
        parte = chiave.split("|", 2)[2]
        for (d,) in archivio.execute("SELECT domanda FROM scartate").fetchall():
            if norm(d) == parte:
                archivio.execute("DELETE FROM scartate WHERE domanda = ?", (d,))
    archivio.commit()
    return f"Risposta archiviata per {chiave}" + (" · tolta dalle scartate: il lint la riprende" if segnale == "scartata" else "")


def da_decidere(archivio):
    """Le domande non chiuse già rinviate MAX_RINVII volte: il lint le porta all'autore, perché il recall
    le mostra solo quando si parla delle loro pagine."""
    return archivio.execute("SELECT chiave, testo, pagina, stato FROM aperte WHERE stato != 'chiusa' AND rinvii >= ? "
                            "ORDER BY prima_vista, chiave", (MAX_RINVII,)).fetchall()


def main():
    from recall import punti_di_partenza
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("testo", nargs="?", help="prompt da cui riconoscere le pagine; assente = tutto il vault")
    ap.add_argument("--db", type=Path, default=QUI / "graph.sqlite")
    ap.add_argument("--stato", action="store_true", help="le domande archiviate, per stato")
    ap.add_argument("--rinvia", metavar="TESTO", help=f"rinvia di {GIORNI_RINVIO} giorni la domanda che contiene TESTO")
    ap.add_argument("--da-decidere", action="store_true", help=f"le domande rinviate {MAX_RINVII} volte, per il lint")
    ap.add_argument("--json", action="store_true", help="le domande aperte non rinviate, in JSON, nell'ordine della skill")
    ap.add_argument("--strutturali", action="store_true", help="con --json: anche le lacune di struttura")
    ap.add_argument("--risposta", metavar="CHIAVE", help="archivia la risposta dell'autore (con --testo)")
    ap.add_argument("--testo", dest="testo_risposta", help="il testo della risposta")
    ap.add_argument("--pagine", default="", help="dove è stata scritta la risposta, separate da ' · '")
    ap.add_argument("--risposte", action="store_true", help="le risposte non ancora consolidate dal lint")
    ap.add_argument("--consolida", action="store_true", help="segna come consolidate le risposte (fine del lint)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    db = sqlite3.connect(args.db)
    if args.json or args.risposta or args.risposte or args.consolida:
        archivio = apri()
        if args.json:
            fuori = da_porre(db, QUI.parent, archivio) + (strutturali(db, QUI.parent) if args.strutturali else [])
            print(json.dumps(fuori, ensure_ascii=False, indent=1))
        elif args.risposta:
            if not args.testo_risposta:
                sys.exit("--risposta richiede --testo")
            print(registra(archivio, args.risposta, args.testo_risposta, args.pagine))
        elif args.risposte:
            righe = archivio.execute("SELECT quando, chiave, risposta, pagine FROM risposte WHERE consolidata = 0 "
                                     "ORDER BY id").fetchall()
            print(f"## risposte da consolidare ({len(righe)})")
            for quando, chiave, risposta, pagine in righe:
                print(f"- {quando} · {chiave}\n  risposta: {risposta}\n  scritta in: {pagine or '-'}")
        else:
            n = archivio.execute("UPDATE risposte SET consolidata = 1 WHERE consolidata = 0").rowcount
            archivio.commit()
            print(f"{n} risposte segnate come consolidate")
        return
    if args.stato or args.rinvia or args.da_decidere:
        archivio = apri()
        sincronizza(archivio, rileva(db, QUI.parent))
        if args.rinvia:
            print(rinvia(archivio, args.rinvia))
            return
        if args.da_decidere:
            righe = da_decidere(archivio)
            print(f"## da decidere: rinviate {MAX_RINVII} volte ({len(righe)})")
            for chiave, testo, pagina, stato in righe:
                print(f"- {testo}\n  pagine: {pagina} · {stato} · chiave: {chiave}")
            return
        for stato in ("aperta", "rinviata", "chiusa"):
            righe = archivio.execute("SELECT chiave, prima_vista, fino_al, rinvii, chiusa_il FROM aperte "
                                     "WHERE stato = ? ORDER BY segnale, pagina, chiave", (stato,)).fetchall()
            print(f"\n## {stato} ({len(righe)})")
            for chiave, prima, fino, rinvii, chiusa in righe:
                extra = {"aperta": f"dal {prima}, rinvii {rinvii}", "rinviata": f"fino al {fino}, rinvii {rinvii}",
                         "chiusa": f"chiusa il {chiusa}"}[stato]
                print(f"- {chiave}  ({extra})")
        return
    if args.testo:
        pagine = punti_di_partenza(db, args.testo)
        scelte = per_pagine(db, QUI.parent, pagine)
        print(formatta(scelte) if scelte else f"nessuna domanda per {pagine or 'nessuna pagina riconosciuta'}")
        return
    per_segnale = defaultdict(dict)
    archivio = apri()
    rilevate = rileva(db, QUI.parent)
    stato_di = sincronizza(archivio, rilevate)
    archivio.close()
    rinviate = set()
    for pagina, elenco in rilevate.items():
        for segnale, testo, chiave in elenco:
            stato, rinvii = stato_di[chiave]
            if stato == "rinviata":
                rinviate.add(chiave)  # una domanda su più pagine conta una volta
                continue
            avviso = f"(rinviata {rinvii} volte: risolvila) " if rinvii >= MAX_RINVII else ""
            per_segnale[segnale].setdefault(avviso + testo, pagina)
    if rinviate:
        print(f"({len(rinviate)} domande rinviate e nascoste: python .graph/domande.py --stato)")
    for segnale in ORDINE:
        print(f"\n## {segnale} ({len(per_segnale[segnale])})")
        for testo in per_segnale[segnale]:
            print(f"- {testo}")


if __name__ == "__main__":
    main()

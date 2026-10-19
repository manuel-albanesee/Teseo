"""Candidati per migliorare il grafo: report in sola lettura, nessuna pagina viene modificata.

Tre sezioni, deterministiche (nessun LLM), per chi rivede il vault o per un agente che classifica:
  termini    parole di una domanda del banco (banco.json) presenti nel corpo della pagina attesa ma non nel suo titolo
             né nei suoi alias: un alias le porterebbe il recall a partire da quella pagina. Solo le domande con pagine
             attese mancanti o senza semi dal grafo (banco_base.json). Un bigramma vale se le sue due parole stanno nella
             stessa frase.
  alias      sigle tra parentesi («Console di Rilascio (CDR)») e forme ridotte del titolo («monitor» per DBMonitor,
             parti di CamelCase), presenti nel corpo di una pagina che linka quella del titolo. Solo le pagine con meno
             di POCHI_ALIAS alias.
  relazioni  coppie A→B con un [[wikilink]] in A e nessuna relazione tipizzata fra le due, ammissibile per i tipi secondo
             la tabella «Relazioni tipizzate» di Wiki reference. Prima le coppie verso gli hub, poi le reciproche.
Per ogni candidato: df (in quante pagine compare, da `testo`), AMBIGUO se df > SOGLIA_AMBIGUO, CONFLITTO se coincide con
il titolo o un alias di un'altra pagina, PAROLE_COMUNI se è una parola comune, e la frase del file in cui compare.
Le pagine `entropia` (riassunti generati da sintesi.py) non sono né bersagli né sorgenti.

Uso:
  python .graph/candidati.py                       report markdown in .graph/candidati.md
  python .graph/candidati.py --json                dati in .graph/candidati.json (per l'agente che classifica)
  python .graph/candidati.py --sezione alias --limite 80 --out FILE
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from build_graph import CODICE, LINK, SPEZZA, bersaglio, leggi, leggi_vocabolario, norm, tipo_ammesso
from domande import TAG_ENTROPIA
from recall import GENERICHE, PAROLE_COMUNI, radice

SOGLIA_AMBIGUO = 5   # df oltre cui un termine o un alias compare in troppe pagine per indicarne una sola
POCHI_ALIAS = 2      # sezione alias: solo le pagine con meno alias di così
MIN_PAROLA = 4       # lunghezza minima (norm) di una parola sola o di una forma ridotta
MIN_COPPIA = 3       # lunghezza minima delle due parole di un bigramma
HUB_MENZIONA = 10    # hub: almeno tanti menziona in entrata (da pagine non entropia) e nessuna tipizzata in entrata
MAX_FORMA = 6        # parole massime di un alias
MAX_FRASE = 250      # caratteri della frase citata; più lunga, una finestra con …
LIMITE = 40          # candidati per sezione nel markdown; il JSON contiene tutto
SEZIONI = ("termini", "alias", "relazioni")
PAROLE_COMUNI_NORM = {norm(p) for p in PAROLE_COMUNI}

# Parole che non dicono di cosa parla una domanda: articoli, preposizioni, pronomi, verbi d'uso e richieste
STOPWORD_ITA = set("""
a al alla alle agli allo ai che chi ci cio cosa cosi come con contro cui da dal dalla dalle dagli dai dei del della
delle degli dello dentro dopo dove e ed il in io la le lei lo loro lui ma mi mia mio ne nel nella nelle negli nei
no noi non o oppure per perche piu poi prima quale quali quando quanto quanta quanti quante quello quella quelle
questo questa queste questi se sei sia siamo sono su sua sue suo suoi sul sulla sulle sugli tra fra ti tu tua
tutti tutto tutta tutte un una uno voi vi ho hai ha hanno abbiamo avere essere fare serve servono deve devo
posso puoi voglio vorrei fammi dimmi dammi spiegami mostrami scrivi elenca elencami aiutami riassumi crea
andare viene vengono ciao grazie prego oggi ieri domani stanotte stasera adesso ora anche ancora
farmi dirmi sapere cerco chiedo sento
""".split())
ARTICOLI = {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "l"}
CONNETTORI = {"di", "del", "della", "dei", "degli", "delle", "dello", "e", "da", "per", "in", "con"}
FORMA = re.compile(r"[\w][\w'’&\- ]*")


def radici_di(testo):
    """Radici (stemmer di recall) delle parole di un testo: le stesse delle colonne `radici_*` di `testo`."""
    return {radice(w) for w in norm(testo).split()}


def frasi(corpo):
    """Span (inizio, fine) delle frasi di un corpo: una riga, spezzata dopo . ! ? e spazio. Sono sottostringhe esatte
    del file, quindi si cercano con grep."""
    bordi, inizio = [], 0
    for m in re.finditer(r"\n|(?<=[.!?])[ \t]+", corpo):
        bordi.append((inizio, m.start()))
        inizio = m.end()
    bordi.append((inizio, len(corpo)))
    out = []
    for a, b in bordi:
        while a < b and corpo[a].isspace():
            a += 1
        while b > a and corpo[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def frase_in(spans, pos):
    """Lo span della frase che contiene `pos`, o None."""
    for a, b in spans:
        if a <= pos < b:
            return a, b
    return None


def breve(testo, centro=0):
    """Il testo, o una finestra di MAX_FRASE caratteri attorno a `centro`, con … dove taglia."""
    if len(testo) <= MAX_FRASE:
        return testo
    inizio = max(0, min(centro - MAX_FRASE // 2, len(testo) - MAX_FRASE))
    fine = inizio + MAX_FRASE
    return ("…" if inizio else "") + testo[inizio:fine] + ("…" if fine < len(testo) else "")


def centro_di(testo, radici_cercate):
    """Posizione in `testo` della prima parola che ha una di queste radici (0 se nessuna)."""
    for m in re.finditer(r"\S+", testo):
        if any(radice(w) in radici_cercate for w in norm(m.group(0)).split()):
            return m.start()
    return 0


def termini_domanda(domanda):
    """{radici: chiave}: le parole piene della domanda (fuori STOPWORD_ITA, senza numeri) e le coppie di parole piene
    adiacenti nella domanda («Java su Tomcat» non dà la coppia «java tomcat»), come insiemi di radici. La chiave è la
    forma norm («manifesto», «coda fpp»)."""
    parole = norm(domanda).split()
    piena = [len(w) >= MIN_COPPIA and w not in STOPWORD_ITA and not w.isdigit() for w in parole]
    out = {}
    for i, w in enumerate(parole):
        if piena[i] and len(w) >= MIN_PAROLA:
            out.setdefault(frozenset([radice(w)]), w)
    for i in range(len(parole) - 1):
        if piena[i] and piena[i + 1]:
            r = frozenset([radice(parole[i]), radice(parole[i + 1])])
            if len(r) == 2:
                out.setdefault(r, f"{parole[i]} {parole[i + 1]}")
    return out


def nome_prima(corpo, pos):
    """Il nome che precede una parentesi in `pos`, sulla stessa riga: «La Console di Rilascio (CDR)» → «Console di
    Rilascio». Si tengono le parole maiuscole e i connettori; l'articolo iniziale no."""
    tenute = []
    for p in reversed(corpo[:pos].split("\n")[-1].split()[-10:]):
        w = p.strip(".,;:!?\"'«»[]*_`")
        if not w or not (w[0].isupper() or w.lower() in CONNETTORI) or len(tenute) == MAX_FORMA:
            break
        tenute.insert(0, w)
    while tenute and tenute[0].lower() in ARTICOLI | CONNETTORI:
        tenute.pop(0)
    while tenute and tenute[-1].lower() in CONNETTORI:
        tenute.pop()
    return " ".join(tenute)


def forma_valida(f):
    """Un alias plausibile: 1-MAX_FORMA parole, che inizia con una maiuscola o una cifra (non «vedi sotto»)."""
    f = f.strip()
    return bool(f) and f[0].isupper() and len(f.split()) <= MAX_FORMA and len(norm(f)) >= 2 and bool(FORMA.fullmatch(f))


def forme_ridotte(titolo):
    """Forme ridotte di un titolo: l'ultima parola piena (dopo aver spezzato i CamelCase: DBMonitor → «Monitor») e le
    parti piene di ogni CamelCase (FattureRicevuteWeb → Fatture, Ricevute, Web)."""
    parti = [p for w in titolo.split() for p in SPEZZA.split(w) if p]
    piene = [p for p in parti if len(norm(p)) >= MIN_PAROLA and norm(p) not in STOPWORD_ITA]
    forme = piene[-1:]
    for w in titolo.split():
        pezzi = [p for p in SPEZZA.split(w) if p]
        if len(pezzi) > 1:
            forme += [p for p in pezzi if len(norm(p)) >= MIN_PAROLA and norm(p) not in STOPWORD_ITA]
    viste, out = set(), []
    for f in forme:
        if norm(f) not in viste:
            viste.add(norm(f))
            out.append(f)
    return out


def _titolo_re(titolo):
    """Il titolo come regex: spazi qualsiasi fra le parole, il resto letterale."""
    return r"\s+".join(re.escape(p) for p in titolo.split())


def leggi_json(percorso, avvisi):
    if not percorso.exists():
        avvisi.append(f"{percorso.name} non trovato: la sezione termini non ha domande da cercare")
        return None
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except ValueError as e:
        avvisi.append(f"{percorso.name} non leggibile: {e}")
        return None


def carica(qui):
    """Tutto ciò che serve alle sezioni, letto in sola lettura: il grafo (mode=ro), le pagine, il vocabolario e il banco."""
    vault, avvisi = qui.parent, []
    grafo = qui / "graph.sqlite"
    d = SimpleNamespace(avvisi=avvisi, pagine={}, titolo_radici={}, corpo_radici={}, radici_pagina={},
                        alias_di=defaultdict(list), alias_norm=defaultdict(set), nomi=defaultdict(set),
                        collegate=defaultdict(set))
    db = sqlite3.connect(grafo.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        for id_, tipo, tags in db.execute("SELECT id, tipo, tags FROM entities WHERE tipo != 'fonte'"):
            d.pagine[id_] = {"tipo": tipo, "entropia": TAG_ENTROPIA in (tags or "").split(", ")}
            d.nomi[norm(id_)].add(id_)
        for id_, rt, rc in db.execute("SELECT id, radici_titolo, radici_corpo FROM testo"):
            d.titolo_radici[id_] = set(rt.split())
            d.corpo_radici[id_] = set(rc.split())
            d.radici_pagina[id_] = d.titolo_radici[id_] | d.corpo_radici[id_]
        for id_, alias in db.execute("SELECT entity_id, alias FROM aliases"):
            d.alias_di[id_].append(alias)
            d.alias_norm[id_].add(norm(alias))
            d.nomi[norm(alias)].add(id_)
        d.relazioni = db.execute("SELECT source_id, target_id, type FROM relations").fetchall()
    finally:
        db.close()
    # il corpo di ogni pagina dal file (senza frontmatter): le frasi citate sono sottostringhe esatte del file
    d.corpi = {}
    for p in sorted((vault / "wiki").glob("*.md")):
        if p.stem not in d.pagine:
            avvisi.append(f"{p.stem}: pagina nel vault ma non nel grafo (ricostruisci con build_graph.py)")
            continue
        try:
            d.corpi[p.stem] = leggi(p)[1]
        except ValueError as e:
            sys.exit(f"errore: {e}")
    for id_ in list(d.pagine):
        if id_ not in d.corpi:
            avvisi.append(f"{id_}: nel grafo ma non nel vault (grafo non aggiornato)")
            del d.pagine[id_]
    d.frasi = {id_: frasi(c) for id_, c in d.corpi.items()}
    d.frasi_radici = {id_: [(a, b, radici_di(c[a:b])) for a, b in d.frasi[id_]] for id_, c in d.corpi.items()}
    # vicini tipizzati (un passo, in entrambi i versi): da lì il recall arriva alla pagina seguendo la relazione
    d.tipizzati = defaultdict(set)
    for a, b, tipo in d.relazioni:
        if tipo not in GENERICHE and a in d.pagine and b in d.pagine and a != b:
            d.tipizzati[a].add(b)
            d.tipizzati[b].add(a)
    for a, b, tipo in d.relazioni:
        if tipo != "documentato_in" and a != b and a in d.pagine and b in d.pagine and not d.pagine[a]["entropia"]:
            d.collegate[b].add(a)
    ultima = max((p.stat().st_mtime for p in (vault / "wiki").glob("*.md")), default=0)
    if ultima > grafo.stat().st_mtime:
        avvisi.append("graph.sqlite è più vecchio di wiki/: ricostruiscilo con build_graph.py prima di leggere il report")
    d.generato = datetime.now().strftime("%Y-%m-%d %H:%M")
    d.grafo_data = datetime.fromtimestamp(grafo.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    rif = vault / "Wiki reference.md"
    d.vocabolario = leggi_vocabolario(rif.read_text(encoding="utf-8")) if rif.exists() else None
    # banco: le domande da cercare sono quelle con attese non vuote e pagine mancanti o senza semi dal grafo
    banco = leggi_json(qui / "banco.json", avvisi) or []
    base = {v["domanda"]: v for v in (leggi_json(qui / "banco_base.json", avvisi) or [])}
    d.eligibili = []
    for voce in banco:
        b = base.get(voce["domanda"])
        if voce.get("attese") and b and (b.get("mancanti") or not b.get("semi_grafo")):
            d.eligibili.append((voce["domanda"], voce["attese"], b.get("mancanti", [])))
    d.termini = {v["domanda"]: termini_domanda(v["domanda"]) for v in banco}
    d.usano = defaultdict(list)  # radici → domande del banco che le contengono
    for domanda in dict.fromkeys(v["domanda"] for v in banco):
        for rad in d.termini[domanda]:
            d.usano[rad].append(domanda)
    return d


def df_di(d, radici):
    """In quante pagine del vault (titolo e corpo, da `testo`) compaiono tutte queste radici."""
    return sum(1 for rs in d.radici_pagina.values() if radici <= rs)


def frase_con(d, P, rad):
    """(testo, centro) della prima frase del corpo di P che contiene tutte le radici `rad`, o None."""
    for a, b, rs in d.frasi_radici[P]:
        if rad <= rs:
            testo = d.corpi[P][a:b]
            return testo, centro_di(testo, rad)
    return None


def frase_di(d, S, pos):
    """La frase di S che contiene la posizione `pos`, o None."""
    span = frase_in(d.frasi[S], pos)
    return d.corpi[S][span[0]:span[1]] if span else None


def sezione_termini(d):
    """Parole delle domande del banco presenti nel corpo della pagina attesa, non nel suo titolo né nei suoi alias.
    Si cercano anche nei vicini tipizzati delle attese (`via`): un seme lì porta all'attesa lungo la relazione
    («notte» è nel corpo di Modulo fatture, che è `parte_di` del Gestionale e ha Anna Rossi come referente)."""
    gruppi, mancate = {}, set()
    for domanda, attese, mancanti in d.eligibili:
        bersagli = [(P, None) for P in attese]
        bersagli += [(V, P) for P in attese for V in sorted(d.tipizzati.get(P, ())) if V not in attese]
        for P, via in bersagli:
            if P not in d.pagine:
                mancate.add(P)
                continue
            if d.pagine[P]["entropia"]:
                continue
            for rad, chiave in d.termini[domanda].items():
                if not rad <= d.corpo_radici.get(P, set()) or rad <= d.titolo_radici.get(P, set()):
                    continue
                if any(rad <= radici_di(a) for a in d.alias_di[P]):
                    continue
                fr = frase_con(d, P, rad)
                if fr is None:
                    continue
                c = gruppi.setdefault((P, rad), {"pagina": P, "termine": chiave, "radici": sorted(rad),
                                                 "frase": breve(fr[0], fr[1]), "mancante": False, "via": []})
                c["mancante"] |= (via or P) in mancanti
                if via and via not in c["via"]:
                    c["via"].append(via)
    for P in sorted(mancate):
        d.avvisi.append(f"pagina attesa «{P}» non nel grafo: nessun termine da cercare")
    out = []
    for (P, rad), c in gruppi.items():
        c["df"] = df_di(d, rad)
        c["domande"] = d.usano.get(rad, [])
        c["ambiguo"] = c["df"] > SOGLIA_AMBIGUO
        c["conflitto"] = bool(d.nomi.get(c["termine"], set()) - {P})
        out.append(c)
    out.sort(key=lambda c: (c["df"], -len(c["domande"]), c["termine"], c["pagina"]))
    return out


def sezione_alias(d):
    """Sigle tra parentesi e forme ridotte del titolo, per pagine con meno di POCHI_ALIAS alias."""
    bersagli = {P for P in d.pagine if not d.pagine[P]["entropia"] and len(d.alias_di[P]) < POCHI_ALIAS}
    trovati = {}

    def aggiungi(P, forma, via, fonte, frase):
        n = norm(forma)
        if P not in bersagli or not n or n == norm(P) or n in d.alias_norm[P]:
            return
        c = trovati.get((P, n))
        if c is None:
            c = trovati[(P, n)] = {"pagina": P, "alias": forma, "via": [], "fonti": [], "frase": frase}
        if via not in c["via"]:
            c["via"].append(via)
        if fonte not in c["fonti"]:
            c["fonti"].append(fonte)

    # sigle tra parentesi: il titolo di una pagina seguito, o preceduto, da una parentesi con l'altra forma
    sorgenti = [S for S in d.corpi if not d.pagine[S]["entropia"]]
    for T in d.pagine:
        avanti = re.compile(rf"(?<!\w){_titolo_re(T)}\s*\(\s*([^()\n]{{1,60}}?)\s*\)", re.I)
        dietro = re.compile(rf"\(\s*{_titolo_re(T)}\s*\)", re.I)
        for S in sorgenti:
            corpo = d.corpi[S]
            for m in avanti.finditer(corpo):
                forma, frase = m.group(1).strip(), frase_di(d, S, m.start())
                if frase and forma_valida(forma):
                    aggiungi(T, forma, "parentesi", S, frase)
            for m in dietro.finditer(corpo):
                forma, frase = nome_prima(corpo, m.start()), frase_di(d, S, m.start())
                if frase and forma_valida(forma):
                    aggiungi(T, forma, "parentesi", S, frase)
    # forme ridotte del titolo, presenti nel corpo di una pagina che linka quella
    for P in bersagli:
        for forma in forme_ridotte(P):
            pat = re.compile(rf"(?<![a-z0-9]){re.escape(norm(forma))}(?![a-z0-9])")
            for A in sorted(d.collegate[P]):
                for a, b in d.frasi[A]:
                    testo = d.corpi[A][a:b]
                    if pat.search(norm(testo)):
                        aggiungi(P, forma, "forma ridotta", A, testo)
                        break
    out = []
    for c in trovati.values():
        n = norm(c["alias"])
        rad = {radice(w) for w in n.split() if w not in STOPWORD_ITA} or radici_di(n)
        c["df"] = df_di(d, rad)
        c["ambiguo"] = c["df"] > SOGLIA_AMBIGUO
        c["conflitto"] = bool(d.nomi.get(n, set()) - {c["pagina"]})
        c["parola_comune"] = n in PAROLE_COMUNI_NORM
        c["frase"] = breve(c["frase"], centro_di(c["frase"], radici_di(n)))
        out.append(c)
    # la stessa forma proposta per più pagine («Monitor» per tutte le «… di DBMonitor») non identifica una pagina sola
    per_forma = defaultdict(list)
    for c in out:
        per_forma[norm(c["alias"])].append(c["pagina"])
    for c in out:
        c["condivisa_con"] = sorted(p for p in per_forma[norm(c["alias"])] if p != c["pagina"])
        c["condivisa"] = bool(c["condivisa_con"])
    out.sort(key=lambda c: (c["conflitto"], c["ambiguo"], c["df"], c["pagina"], c["alias"]))
    return out


def frase_link(d, A, B):
    """(testo, centro) della prima frase di A che contiene [[B]] o [[B|…]] fuori dal codice, o None."""
    corpo = d.corpi[A]
    codice = [m.span() for m in CODICE.finditer(corpo)]
    for m in LINK.finditer(corpo):
        if any(i <= m.start() < j for i, j in codice) or bersaglio(m.group(1)).lower() != B.lower():
            continue
        span = frase_in(d.frasi[A], m.start())
        if span:
            a, b = span
            return corpo[a:b], m.start() - a
    return None


def sezione_relazioni(d):
    """Coppie A→B con un menziona e nessuna relazione tipizzata fra A e B, per cui Wiki reference ammetterebbe una."""
    if d.vocabolario is None:
        d.avvisi.append("vocabolario «Relazioni tipizzate» non trovato in Wiki reference: sezione relazioni vuota")
        return [], []
    menziona, tipizzate = set(), set()
    entrata_menz, entrata_tip = Counter(), Counter()
    for a, b, tipo in d.relazioni:
        if a not in d.pagine or b not in d.pagine or tipo == "documentato_in":
            continue
        if tipo == "menziona":
            menziona.add((a, b))
            if not d.pagine[a]["entropia"]:
                entrata_menz[b] += 1
        elif tipo not in GENERICHE:
            tipizzate.add(frozenset((a, b)))
            entrata_tip[b] += 1
    hub = {b for b in entrata_menz if entrata_menz[b] >= HUB_MENZIONA and not entrata_tip[b]}
    cands = []
    for a, b in sorted(menziona):
        if a == b or d.pagine[a]["entropia"] or d.pagine[b]["entropia"] or frozenset((a, b)) in tipizzate:
            continue
        ta, tb = d.pagine[a]["tipo"], d.pagine[b]["tipo"]
        ammesse = sorted(rel for rel, (da, a_) in d.vocabolario.items()
                         if tipo_ammesso(da, ta, tb) and tipo_ammesso(a_, tb, ta))
        fr = frase_link(d, a, b)
        if not ammesse or fr is None:
            continue
        cands.append({"da": a, "a": b, "tipo_da": ta, "tipo_a": tb, "ammesse": ammesse,
                      "reciproca": (b, a) in menziona, "hub": b in hub,
                      "menziona_in_entrata": entrata_menz[b], "frase": breve(fr[0], fr[1])})
    cands.sort(key=lambda c: (not c["hub"], not c["reciproca"], -c["menziona_in_entrata"], c["da"], c["a"]))
    coppie = Counter(c["a"] for c in cands)
    hubs = [{"hub": h, "menziona_in_entrata": entrata_menz[h], "coppie": coppie[h]}
            for h in sorted(hub, key=lambda h: (-coppie[h], -entrata_menz[h], h))]
    return cands, hubs


def bandiere(*coppie):
    """Le etichette (nome, vero/falso) che valgono: « · AMBIGUO » e simili."""
    return "".join(f" · {nome}" for nome, on in coppie if on)


def unita(s, cands):
    """Le voci del report: per gli alias una per forma (le pagine che la condividono stanno nella stessa voce),
    per le altre sezioni una per candidato."""
    if s != "alias":
        return [[c] for c in cands]
    gruppi = defaultdict(list)
    for c in cands:
        gruppi[norm(c["alias"])].append(c)
    return list(gruppi.values())


def righe_termini(cands, limite):
    tot = Counter(c["pagina"] for c in cands)
    gruppi = defaultdict(list)
    for c in cands[:limite]:
        gruppi[c["pagina"]].append(c)
    righe = []
    for P, lista in gruppi.items():
        righe += [f"### [[{P}]] · {len(lista)} di {tot[P]}", ""]
        for c in lista:
            n = len(c["domande"])
            righe.append(f"- **{c['termine']}** · df {c['df']}"
                         + bandiere(("AMBIGUO", c["ambiguo"]), ("CONFLITTO", c["conflitto"]), ("mancante", c["mancante"]))
                         + (f" · via {', '.join(f'[[{v}]]' for v in c['via'])}" if c["via"] else "")
                         + f" · {n} {'domanda' if n == 1 else 'domande'} del banco")
            righe.append(f"  > {c['frase']}")
            altre = f" e altre {n - 1}" if n > 1 else ""
            righe.append(f"  - «{c['domande'][0][:110]}»{altre}")
        righe.append("")
    return righe


def righe_alias(voci):
    """Una voce per forma: le pagine che la condividono sono tutte elencate."""
    righe = []
    for lista in voci:
        c = lista[0]
        pagine = ", ".join(f"[[{x['pagina']}]]" for x in lista)
        fonti = ", ".join(f"[[{f}]]" for f in c["fonti"][:3])
        if len(c["fonti"]) > 3:
            fonti += f" e altre {len(c['fonti']) - 3}"
        via = " + ".join(sorted({v for x in lista for v in x["via"]}))
        righe.append(f"- **{c['alias']}** → {pagine} · df {c['df']} · via {via} · fonte {fonti}"
                     + bandiere(("AMBIGUO", c["ambiguo"]), ("CONFLITTO", any(x["conflitto"] for x in lista)),
                                ("PAROLE_COMUNI", c["parola_comune"]), ("CONDIVISA", len(lista) > 1)))
        righe.append(f"  > {c['frase']}")
    return righe


def righe_relazioni(cands, hubs, limite):
    righe = ["| Hub | menziona in entrata | coppie candidate |", "|---|---:|---:|"]
    righe += [f"| [[{h['hub']}]] | {h['menziona_in_entrata']} | {h['coppie']} |" for h in hubs]
    righe.append("")
    for c in cands[:limite]:
        ammesse = ", ".join(f"`{r}`" for r in c["ammesse"])
        righe.append(f"- [[{c['da']}]] → [[{c['a']}]] · {c['tipo_da']} → {c['tipo_a']} · ammesse: {ammesse}"
                     + ("" if not c["reciproca"] else " · reciproca") + (" · hub" if c["hub"] else ""))
        righe.append(f"  > {c['frase']}")
    return righe


SPIEGAZIONE = {
    "termini": (f"Parole di una domanda del banco (con pagine attese mancanti o senza semi dal grafo) presenti nel "
                f"corpo della pagina attesa, non nel titolo né negli alias. Ordine: df crescente. AMBIGUO: df > "
                f"{SOGLIA_AMBIGUO}. Un bigramma vale se le due parole stanno nella stessa frase."),
    "alias": (f"Sigle tra parentesi («Forma lunga (SIGLA)») e forme ridotte del titolo, presenti nel corpo di una pagina "
              f"che linka quella. Solo pagine con meno di {POCHI_ALIAS} alias. Una riga per forma: se la forma spetta "
              f"a più pagine (CONDIVISA) sono tutte elencate, e non identifica una pagina sola. Ordine: prima i non "
              f"CONFLITTO e i non AMBIGUO."),
    "relazioni": (f"Coppie A→B con un wikilink in A e nessuna relazione tipizzata fra le due, ammissibile per i tipi "
                  f"secondo Wiki reference. Prima verso gli hub ({HUB_MENZIONA}+ menziona in entrata, nessuna "
                  f"tipizzata), poi le reciproche."),
}
TITOLI = {"termini": "1. Termini", "alias": "2. Alias", "relazioni": "3. Relazioni"}


def markdown(d, r, sezioni, limite):
    righe = ["# Candidati per il grafo", "",
             f"Generato il {d.generato} · sola lettura: nessuna pagina modificata · grafo del {d.grafo_data} · "
             "JSON completo: `.graph/candidati.json`", ""]
    if d.avvisi:
        righe += ["Avvisi:", ""] + [f"- {a}" for a in d.avvisi] + [""]
    voci = {s: unita(s, r[s]) for s in sezioni}
    righe += ["| Sezione | Candidati | Voci nel report |", "|---|---:|---:|"]
    righe += [f"| {s} | {len(r[s])} | {min(len(voci[s]), limite)} |" for s in sezioni]
    righe.append("")
    for s in sezioni:
        righe += [f"## {TITOLI[s]}", "", SPIEGAZIONE[s], ""]
        if s == "termini":
            righe += righe_termini(r[s], limite)
        elif s == "alias":
            righe += righe_alias(voci[s][:limite])
        else:
            righe += righe_relazioni(r[s], r["hub"], limite)
        if len(voci[s]) > limite:
            righe += [f"… altre {len(voci[s]) - limite} voci: nel JSON, o con --limite.", ""]
    return "\n".join(righe) + "\n"


def json_out(d, r, sezioni):
    out = {"generato": d.generato, "grafo": d.grafo_data, "avvisi": d.avvisi,
           "conteggi": {s: len(r[s]) for s in sezioni}}
    for s in sezioni:
        out[s] = r[s]
    if "relazioni" in sezioni:
        out["hub"] = r["hub"]
    return out


def main():
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="scrive i dati in .graph/candidati.json (default: markdown)")
    ap.add_argument("--out", type=Path, help="file di output (default .graph/candidati.md o .json)")
    ap.add_argument("--sezione", choices=SEZIONI, help="una sola sezione")
    ap.add_argument("--limite", type=int, default=LIMITE,
                    help="candidati per sezione nel markdown (default %(default)s; il JSON contiene tutto)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    d = carica(qui)
    sezioni = (args.sezione,) if args.sezione else SEZIONI
    r = {}
    if "termini" in sezioni:
        r["termini"] = sezione_termini(d)
    if "alias" in sezioni:
        r["alias"] = sezione_alias(d)
    if "relazioni" in sezioni:
        r["relazioni"], r["hub"] = sezione_relazioni(d)
    out = args.out or qui / ("candidati.json" if args.json else "candidati.md")
    testo = (json.dumps(json_out(d, r, sezioni), ensure_ascii=False, indent=1) if args.json
             else markdown(d, r, sezioni, max(args.limite, 0)))
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(testo)
    print(" · ".join(f"{s} {len(r[s])}" for s in sezioni)
          + (f" · hub {len(r['hub'])}" if "relazioni" in sezioni else ""))
    for a in d.avvisi:
        print(f"avviso: {a}")
    print(f"→ {out}")


if __name__ == "__main__":
    main()

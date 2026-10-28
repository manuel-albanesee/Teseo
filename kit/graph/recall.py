"""Richiama dal grafo i fatti legati a una domanda, da mettere nel contesto prima di rispondere.

Punti di partenza: nomi di pagina e alias citati nella domanda (senza maiuscole e accenti,
vince il nome più lungo: "Portale clienti nuovo" batte "Portale clienti"), più le loro varianti grafiche generate da
build_graph (tabella `varianti`: «Service Desk» e «service desk» trovano ServiceDesk, «modulofatture» il Modulo fatture);
poi le pagine di cui la domanda contiene le parole del titolo (o di un alias a più parole), confrontate per radice
(stemmer.py, Snowball italiano: flesse e derivate, «rilasciare in produzione» → Rilascio in produzione) e
vicine fra loro (finestra di len(titolo)+FINESTRA_EXTRA parole): "caricamento fallito" → Recupero di un caricamento fallito.
Cammino: 1° passo su tutti gli archi; dal 2° solo lungo relazioni tipizzate, solo da nodi
raggiunti con una relazione tipizzata e nello stesso verso, perché i link generici portano sempre
agli hub (le pagine del sistema principale) e i "fratelli" (altre pagine che puntano allo stesso nodo) sono rumore.
In avanti fino al 3° passo, perché le catene si stringono verso prerequisiti e referenti
(Rilascio in produzione → Console di rilascio → Incident settimanale → Anna Rossi); a ritroso
fino al 2°, perché si allargano (le parti delle parti).
Potatura: 3 o più fratelli diventano un fatto solo (le 10 pagine parte_di uno stesso sistema), così un hub
non riempie i posti e le catene lunghe restano dentro.
Limiti per tipo, non un top-k unico: tutte le relazioni tipizzate (tetto di sicurezza MAX_TIPIZZATE) e al più
MAX_MENZIONA link generici (`menziona`), i migliori per punteggio; i `menziona` pesano molto meno e un top-k unico
tagliava anche relazioni tipizzate (le catene) per far posto a loro o a hub. Quello che resta fuori è contato
(omessi) e formatta() lo dichiara in coda, così il modello sa che il contesto è parziale e può cercare.
Le pagine generate per entropia (tag `entropia`, sintesi.py) sono punti di partenza solo se nominate:
raggiunte dal cammino contano come un link generico e non proseguono catene.
Solo il testo scritto dall'utente conta (scritto()): i blocchi <pasted_content> incollati e i rapporti dei sub agent
(<agent-message>, che Claude Code consegna come prompt) nominano pagine senza che la
domanda le riguardi, e sono tolti prima di cercare i punti di partenza (e dal routing, dalla memoria, dalle domande aperte).
I nomi che sono anche parole comuni (PAROLE_COMUNI, es. Portale) valgono solo scritti con la maiuscola.
Nessun punto di partenza → nessun output. L'hook aggiunge come punti di partenza anche le pagine
lette in passato per domande simili (memoria.py); da riga di comando no.
Ripiego sul testo (per_testo, usato dall'hook solo se né il grafo né la memoria danno punti di partenza): ricerca
FTS5 nel corpo delle pagine (tabella `testo` di build_graph.py), per parole significative ridotte a radice con lo
stemmer (le colonne `radici_titolo` e `radici_corpo` hanno il testo già ridotto: FTS5 non può usare uno stemmer Python
come tokenizer; tollera flessioni e derivazioni, «rilasciare» trova «rilascio»; la radice è un termine intero, non un
prefisso) e per date in linguaggio naturale («10 settembre», «31/08»), che sono mappate alle fonti
`call-AAAA-MM-GG*` e quindi alle pagine che le citano. Al più MAX_TESTO pagine, sopra soglia: un aggancio debole,
che l'hook dichiara come tale. Le pagine `entropia` non si cercano nel testo (riassumono altre pagine).
Le parole comuni presenti in più di SOGLIA_FREQUENTE delle pagine (stesso, query, error: la frequenza viene
dall'indice FTS stesso, frequenti_testo) non distinguono nulla: non contano come «prese» né per il minimo e non vanno
nella query; con meno di due parole comuni utili e nessun identificatore o data il ripiego non dà pagine.
Una parola presente in al più SOGLIA_RARA pagine, di almeno MIN_RARA lettere e dall'aspetto di un nome (sembra_nome:
finisce per consonante o ha j k w x y; «fatturix» sì, «riunione» e «lunedì» no) conta come identificatore: basta da sola.
Le sole parole comuni (nessun identificatore) devono anche stare vicine nella pagina: almeno la metà di quelle cercate
(il minimo) in una finestra di FINESTRA_TESTO parole. Parole rare ma sparse in pagine lunghe («il collega mi ha chiesto
il report settimanale»: chiesto e settimanale a 58 parole in una pagina, a 144 in un'altra) non dicono che la pagina
parli di quello; le pagine giuste le hanno a 4-16 parole.
Se il primo giro non trova nulla, un secondo giro (per_testo_a_cascata) allarga finestra e soglia
(FINESTRA_TESTO_LARGA, SOGLIA_FREQUENTE_LARGA) e porta al più MAX_TESTO_LARGO pagine: le domande parafrasate hanno le
parole un po' più lontane o un po' più frequenti di quelle che nominano la pagina.

Uso: python .graph/recall.py "il file delle fatture non arriva, a chi scrivo?" [--menziona 10] [--tipizzate 30] [--json]
"""
import argparse
import json
import math
import re
import sqlite3
from graph_db import connect_graph, resolve_graph
import sys
from collections import Counter, namedtuple
from pathlib import Path

from build_graph import norm
from stemmer import stem
from domande import TAG_ENTROPIA

GENERICHE = {"menziona", "documentato_in"}
PASSI = {"avanti": 3, "indietro": 2}  # passi massimi lungo le catene tipizzate, per verso
PUNTI = {1: 100, 2: 50, 3: 40}       # punteggio base di una relazione tipizzata, per passo
FRATELLI = 3                          # da quanti fratelli in su si raccolgono in un fatto solo
MAX_TIPIZZATE = 30                    # tetto di sicurezza: di norma passano tutte le relazioni tipizzate
MAX_MENZIONA = 10                     # link generici: i migliori per punteggio
# Nomi di pagina che sono anche parole comuni: valgono solo scritti con la maiuscola
PAROLE_COMUNI = {"portale"}  # da adattare, uguale a build_graph.PAROLE_COMUNI_NOMI
# Testo incollato dall'utente, o rapporto di un sub agent che Claude Code consegna come prompt:
# può nominare pagine senza che la domanda le riguardi
INCOLLATO = re.compile(r"<(pasted_content|agent-message)\b[^>]*>.*?</\1\b[^>]*>", re.S)
# per_titolo: le parole del titolo stanno in una finestra di len(titolo) + FINESTRA_EXTRA parole del testo.
# 4 è il minimo che, nel vault di origine, teneva una domanda con tre parole fra quelle del titolo;
# l'episodio e la soglia di un testo lungo tornano titolo solo da ~20 in su: 6 lascia margine a entrambi i lati
FINESTRA_EXTRA = 6
MAX_TESTO = 3          # pagine al più dal ripiego sul testo
MIN_SCORE_TESTO = 5.0  # bm25 (positivo = migliore) minimo di una pagina trovata solo da parole comuni; sotto è rumore
SOGLIA_FREQUENTE = 0.20  # una parola comune in più di questa quota delle pagine non distingue (stess, query, error, server)
FINESTRA_TESTO = 30    # parole: finestra in cui devono stare le parole comuni prese da una pagina trovata senza identificatori
# Secondo giro del ripiego (per_testo_a_cascata), solo se il primo non trova nulla: finestra e soglia più larghe, meno
# pagine. Su un vault reale (213 pagine, banco di 106 domande) 88 → 102 pagine attese su 134, 0 domande peggiorate
# (doc/analisi-retrieval-ecc.md). Con 60 parole o soglia 0.30 «come gestisco un errore di timeout sul server?» porta una
# pagina fuori tema.
FINESTRA_TESTO_LARGA = 45
SOGLIA_FREQUENTE_LARGA = 0.25
MAX_TESTO_LARGO = 2
MIN_PREFISSO = 5       # identificatori: sotto questa lunghezza si cercano interi, non come prefisso («acme0» non è «acme01»)
SOGLIA_RARA = 2        # una parola in al più questo numero di pagine (e dall'aspetto di un nome: sembra_nome) è un identificatore
MIN_RARA = 5           # lettere minime di una parola rara per valere da identificatore
# Parole di conversazione e di richiesta, che non dicono di cosa si parla: «grazie mille», «dimmi quanto costa»
STOPWORD_TESTO = set("ciao grazie mille prego dimmi dammi fammi fammela scrivi scrivimi spiegami mostrami "
                     "aiutami vorrei voglio potresti riassumi riassumimi quanto costa tutto tutti ancora "
                     "stasera oggi domani ieri ok va bene procedi".split())
MESI = {m: i for i, m in enumerate("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre "
                                   "novembre dicembre".split(), 1)}
DATA_TESTUALE = re.compile(rf"\b(\d{{1,2}})\s+({'|'.join(MESI)})\b(?:\s+(20\d\d))?", re.I)
DATA_NUMERICA = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?\b")
STOPWORD = set("come cosa dove quando quale quali sono della delle degli dello nella nelle negli "
               "questo questa quello quella perche anche ancora dopo prima fare serve deve devo "
               "posso puoi abbiamo hanno essere viene cosi solo "
               "dei del dal dalla per con nel una uno gli che non sul sulla".split())

# Richieste che scrivono nel vault: Haiku può solo leggere, e la memoria non deve imparare da comandi.
# Imperativi (anche con pronome: salvala) e infiniti. Stanno qui, modulo neutro, perché li usano sia
# modello_hook.py (routing) sia memoria.py (che modello_hook importa indirettamente via recall_hook).
IMPERATIVI = ("ingerisci archivia aggiorna modifica scrivi crea aggiungi correggi rinomina cancella elimina "
              "rimuovi sposta colma integra registra annota inserisci sostituisci salva").split()
INFINITI = ("ingerire archiviare aggiornare modificare scrivere creare aggiungere correggere rinominare cancellare "
            "eliminare rimuovere spostare colmare integrare registrare annotare inserire sostituire salvare lintare").split()
INGLESE = "ingest lint save update write edit fix create add delete remove rename".split()
SCRITTURA = re.compile(
    r"\b(?:lint\w*|(?:" + "|".join(IMPERATIVI) + r")(?:la|lo|le|li|ne|mi|ci)?|(?:"
    + "|".join(i[:-1] for i in INFINITI) + r")(?:e|la|lo|le|li|ne|mi|ci)|" + "|".join(INGLESE) + r")\b")
# Domande su questo sistema (hook, modelli, routing, grafo, recall, script .py come parole: «misura py») e non sul contenuto del vault: le gestisce Opus.
META = re.compile(r"\b(?:haiku|opus|sonnet|claude|hook|prompt|routing|grafo|graph|recall|sub ?agent|py)\b")


def scritto(prompt):
    """Il prompt senza i blocchi incollati: quello che l'utente ha scritto davvero."""
    return INCOLLATO.sub(" ", prompt)


def radice(parola):
    """Radice di una parola già normalizzata (norm): lo stemmer Snowball italiano (stemmer.py), non più le sole vocali
    finali. Forme flesse E derivate si incontrano:
        rilasciare  rilascio  rilasciato   → rilasc      (prima: «rilasciar» e «rilasc», mai uguali)
        collaudare  collaudo               → collaud     (prima: «collaudar» e «collaud»)
        approva  approvazione  approvare   → approv      (prima: «approva» e «approvazion»)
        caricamento  caricamenti  caricare → caric       chiave  chiavi → chiav
    Con radici più corte di prima (caric, rilasc) il confronto per PREFISSO sarebbe troppo largo («caric» è prefisso di
    «carica», «caricatore»...): per questo il ripiego sul testo non cerca più prefissi di radici, ma la radice intera
    in colonne già ridotte (`radici_titolo`, `radici_corpo`, build_graph.ridotto). Il prefisso resta solo per gli
    identificatori (FattureRicevute), che non si riducono."""
    return stem(parola)


def radici(testo):
    return {radice(w) for w in norm(testo).split() if len(w) >= 3 and w not in STOPWORD}


def per_titolo(db, domanda, semi):
    """Pagine con almeno due parole del titolo vicine nella domanda, che pesano almeno metà del titolo.

    Il titolo può essere anche un alias a più parole (non le sigle). Una parola pesa meno quanti più titoli la contengono (il nome del sistema principale pesa poco).
    Serve almeno una parola che non sia già nel nome di una pagina riconosciuta per intero:
    "soglie del portale" porta Episodi e soglie del portale, "portale" da solo no.
    Le parole prese devono stare in una finestra di len(titolo) + FINESTRA_EXTRA parole consecutive del testo
    (stopword comprese): «un episodio» e «la soglia» a due paragrafi di distanza non portano un titolo.
    """
    # Ogni pagina ha più «titoli»: il nome e gli alias scritti con più parole (non le sigle: «CDR» ha una radice sola).
    # «collaudare un pacchetto» porta la pagina con l'alias «Pacchetto di collaudo»: le stesse due radici.
    titoli = {id_: [(radici(id_), id_)] for (id_,) in db.execute("SELECT id FROM entities WHERE tipo != 'fonte'")}
    for id_, alias in db.execute("SELECT entity_id, alias FROM aliases"):
        if len(radici(alias)) >= 2:
            titoli[id_].append((radici(alias), alias))
    quanti = Counter(r for tt in titoli.values() for rr, _ in tt for r in rr)
    peso = lambda r: math.log((len(titoli) + 1) / quanti[r])
    parole = [radice(w) if len(w) >= 3 and w not in STOPWORD else None for w in norm(domanda).split()]
    gia = {r for s in semi for rr, _ in titoli[s] for r in rr}
    trovati = []
    for id_, alternative in titoli.items():
        if id_ in semi:
            continue
        migliore = 0
        for rr, nome in alternative:
            if len(rr & set(parole)) < 2:
                continue
            larghezza = len(norm(nome).split()) + FINESTRA_EXTRA
            for i in range(len(parole)):
                prese = rr & set(parole[i:i + larghezza])
                if len(prese) < 2 or not prese - gia:
                    continue
                migliore = max(migliore, sum(map(peso, prese)) / sum(map(peso, rr)))
        if migliore >= 0.5:
            trovati.append((migliore, id_))
    return [id_ for _, id_ in sorted(trovati, reverse=True)]


def punti_di_partenza(db, domanda):
    domanda = scritto(domanda)
    q = f" {norm(domanda)} "
    candidati = [(id_, id_) for (id_,) in db.execute("SELECT id FROM entities WHERE tipo != 'fonte'")]
    candidati += db.execute("SELECT entity_id, alias FROM aliases").fetchall()
    try:  # varianti grafiche generate (ServiceDesk → «service desk», «Modulo fatture» → «modulofatture»)
        candidati += db.execute("SELECT entity_id, variante FROM varianti").fetchall()
    except sqlite3.OperationalError:  # graph.sqlite di una versione senza la tabella
        pass
    trovati = []
    for id_, nome in candidati:
        n = norm(nome)
        if n in PAROLE_COMUNI and not re.search(rf"\b{re.escape(nome)}\b", domanda):
            continue
        i = q.find(f" {n} ")
        while n and i != -1:
            trovati.append((i, i + len(n) + 1, id_))
            i = q.find(f" {n} ", i + 1)
    presi, occupato = [], []
    for inizio, fine, id_ in sorted(trovati, key=lambda t: t[0] - t[1]):  # più lunghi prima
        if all(fine <= a or inizio >= b for a, b in occupato):
            occupato.append((inizio, fine))
            if id_ not in presi:
                presi.append(id_)
    return presi + per_titolo(db, domanda, presi)


def date_nel_testo(testo):
    """[(giorno, mese, anno o None)] delle date scritte come «10 settembre», «31 agosto 2026», «10/09»."""
    date = [(int(g), MESI[m.lower()], int(a) if a else None) for g, m, a in DATA_TESTUALE.findall(testo)]
    for g, m, a in DATA_NUMERICA.findall(testo):
        if 1 <= int(m) <= 12:
            date.append((int(g), int(m), (2000 + int(a) if len(a) == 2 else int(a)) if a else None))
    return [d for d in date if 1 <= d[0] <= 31]


def pagine_per_data(db, testo, tolte):
    """Pagine che citano in `fonti` una chiamata (call-AAAA-MM-GG*) di una data scritta nel testo, prima quelle
    che la citano più volte nel corpo: «riassumi la call del 10 settembre». Senza anno vale quello delle fonti
    che hanno quel giorno e quel mese (nessuna fonte → nessuna pagina)."""
    pagine = {}
    for giorno, mese, anno in date_nel_testo(testo):
        modello = f"call-{anno or '[0-9][0-9][0-9][0-9]'}-{mese:02d}-{giorno:02d}*"
        for (chiave,) in db.execute("SELECT id FROM entities WHERE tipo = 'fonte' AND id GLOB ?", (modello,)).fetchall():
            frase = '{titolo corpo} : "' + norm(chiave) + '"'  # le citazioni nel corpo sono [call-2026-09-10 12:34]
            citazioni = {id_: -score for id_, score in db.execute(
                "SELECT id, bm25(testo) FROM testo WHERE testo MATCH ?", (frase,))}
            for (id_,) in db.execute("SELECT source_id FROM relations WHERE target_id = ? AND type = 'documentato_in'",
                                     (chiave,)):
                if id_ not in tolte:
                    pagine[id_] = pagine.get(id_, 0) + 1 + citazioni.get(id_, 0) / 100  # fonti prima, poi citazioni
    return sorted(pagine, key=lambda p: (-pagine[p], p))


# frase FTS5, chiave di verifica, forte, radice (la chiave sta nel testo ridotto a radici), parola (norm, per sembra_nome)
Termine = namedtuple("Termine", "frase chiave forte radice parola", defaults=(False, ""))
COLONNE_TESTO = "{titolo corpo}"
COLONNE_RADICI = "{radici_titolo radici_corpo}"


def termini_testo(testo):
    """[Termine(frase FTS5, chiave di verifica, forte, radice, parola)] dal testo, senza date.

    Parole comuni (una parola italiana qualsiasi): si cercano per RADICE (stemmer) nelle colonne `radici_*` della
    tabella `testo`, già ridotte allo stesso modo: «rilasciare» trova «rilascio», «approvazione» trova «approva».
    Frase `{radici_titolo radici_corpo} : "rilasc"`, chiave `" rilasc "` (parola intera della pagina ridotta a radici,
    `radice=True`). Parole diverse con la stessa radice (caricamento, caricamenti) sono un termine solo.
    Identificatori: una parola con `_`, `-`, `.` interni o con maiuscole interne o cifre (id_fattura, call-2026-09-10,
    FattureRicevute) è forte, basta lei da sola; non si riduce (le radici di «IdFattura» non significano nulla) e
    si cerca scritta, in titolo e corpo interi: prefisso se lunga (chiave `" parola"`), intera se corta o in più parole
    (chiave `" a b "`). Le frasi contengono solo [a-z0-9 ] (norm) fra virgolette: nessun carattere speciale di FTS5."""
    termini = {}
    for grezza in re.findall(r"\w+(?:[-.]\w+)*", DATA_NUMERICA.sub(" ", DATA_TESTUALE.sub(" ", testo))):
        pezzi = norm(grezza).split()
        forte = len(pezzi) > 1 or bool(re.search(r"[a-z][A-Z]|\d", grezza) and re.search(r"[a-zA-Z]", grezza))
        if len(pezzi) > 1:
            t = Termine(f'{COLONNE_TESTO} : "{" ".join(pezzi)}"', f" {' '.join(pezzi)} ", True)
        elif pezzi and len(pezzi[0]) >= 4 and pezzi[0] not in STOPWORD | STOPWORD_TESTO:
            if forte and len(pezzi[0]) >= MIN_PREFISSO:
                t = Termine(f'{COLONNE_TESTO} : "{pezzi[0]}"*', f" {pezzi[0]}", True)
            elif forte:
                t = Termine(f'{COLONNE_TESTO} : "{pezzi[0]}"', f" {pezzi[0]} ", True)
            else:
                r = radice(pezzi[0])
                t = Termine(f'{COLONNE_RADICI} : "{r}"', f" {r} ", False, True, pezzi[0])
        else:
            continue
        termini.setdefault(t.chiave, t)
    return list(termini.values())


def sembra_nome(parola):
    """True se una parola (norm) non ha la forma di una parola italiana comune: finisce per consonante o ha una lettera
    che l'italiano non usa (j k w x y). «fatturix», «deploy», «timeout», «report» sì; «riunione», «lunedi», «fornitore»,
    «settimanale» no. Serve a SOGLIA_RARA: una parola presente in poche pagine è un nome (un identificatore) solo se
    non è un'ordinaria parola italiana che il vault usa di rado; altrimenti «organizzo la riunione di lunedì» (riunione e
    lunedì stanno in una pagina sola) aggancerebbe quella pagina."""
    return parola[-1] not in "aeiou" or any(c in "jkwxy" for c in parola)


def frequenze_testo(db, termini, escluse):
    """(totale, {chiave: pagine}) delle parole comuni di `termini`: in quante pagine non `escluse` (rowid di `testo`)
    compaiono, su `totale` pagine non escluse. La frequenza documentale viene dal vocabolario dell'indice stesso
    (fts5vocab, 'instance': una riga per occorrenza, doc = rowid), contando le pagine distinte, e per le parole comuni
    guarda solo le colonne `radici_*`: la radice è un termine intero dell'indice, non un prefisso (e non c'è più da
    sommare «error» ed «errors»: sono la stessa radice). Nessuna lista a mano."""
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.vocabolario_testo USING fts5vocab(main, testo, 'instance')")
    totale = db.execute("SELECT count(*) FROM testo").fetchone()[0] - len(escluse)
    frequenze = {}
    for t in termini:
        if t.forte or not totale:
            continue
        pagine = {r[0] for r in db.execute(
            "SELECT doc FROM temp.vocabolario_testo WHERE term = ? AND col IN ('radici_titolo', 'radici_corpo')",
            (t.chiave.strip(),))}
        frequenze[t.chiave] = len(pagine - escluse)
    return totale, frequenze


def frequenti_testo(db, termini, escluse, soglia=None):
    """Chiavi (t.chiave) delle parole comuni di `termini` presenti in più di `soglia` (di norma SOGLIA_FREQUENTE) delle
    pagine non `escluse` (rowid di `testo`): stesso, query, error non distinguono nessuna pagina (vedi frequenze_testo)."""
    soglia = SOGLIA_FREQUENTE if soglia is None else soglia
    totale, frequenze = frequenze_testo(db, termini, escluse)
    return {k for k, n in frequenze.items() if n / totale > soglia}


def rare_testo(db, termini, escluse):
    """Chiavi delle parole comuni di `termini` che valgono da identificatore: in al più SOGLIA_RARA pagine non `escluse`
    (almeno una), almeno MIN_RARA lettere e dall'aspetto di un nome (sembra_nome). «fatturix» sta in due pagine sole:
    chi lo nomina parla di quelle. Una parola italiana ordinaria e rara («riunione») no: vedi sembra_nome."""
    _, frequenze = frequenze_testo(db, termini, escluse)
    return {t.chiave for t in termini if not t.forte and 1 <= frequenze.get(t.chiave, 0) <= SOGLIA_RARA
            and len(t.parola) >= MIN_RARA and sembra_nome(t.parola)}


def vicine(pagina, chiavi, minimo, finestra=None):
    """True se almeno `minimo` chiavi distinte (forma di termini_testo: `" radice "`, parola intera) stanno in
    `finestra` (di norma FINESTRA_TESTO) parole consecutive di `pagina` (la pagina ridotta a radici, con spazi ai bordi:
    le chiavi sono radici e si confrontano con radici)."""
    finestra = FINESTRA_TESTO if finestra is None else finestra
    parole = pagina.split()
    posizioni = sorted((i, k) for k in chiavi for i, w in enumerate(parole) if w == k.strip())
    for a, (inizio, _) in enumerate(posizioni):
        if len({k for i, k in posizioni[a:] if i < inizio + finestra}) >= minimo:
            return True
    return False


def per_testo(db, domanda, n=MAX_TESTO, tolte=(), finestra=None, soglia_frequente=None):
    """Ripiego quando il grafo non riconosce nulla: [pagine] trovate nel corpo (FTS5 `testo`), al più n.

    Prima le pagine delle fonti delle date citate, poi la ricerca per parole (bm25, titolo pesa più del corpo, nelle
    colonne intere e in quelle ridotte a radici).
    Una pagina passa se contiene un identificatore della domanda, oppure almeno metà delle sue parole comuni
    (non meno di due) con punteggio da MIN_SCORE_TESTO e vicine nella pagina (vicine): «fammi un commit» non porta
    «Branch e commit del Gestionale», «il report settimanale» non porta pagine che hanno le due parole lontane.
    Le parole comuni si cercano e si verificano come radici (termini_testo, `radici_*`): le radici della pagina si
    confrontano con quelle della domanda, parola intera su parola intera. Le parole comuni troppo frequenti
    (frequenti_testo) sono tolte prima di tutto: dalla query, dalle parole prese e dal minimo; se ne restano meno di
    due e non c'è un identificatore, la ricerca per parole non dà nulla (le date e gli identificatori funzionano come
    prima). Una parola comune molto rara che sembra un nome (rare_testo: «fatturix») conta invece come un
    identificatore. `tolte`: pagine da non ripetere (già semi). `finestra` e `soglia_frequente` sostituiscono
    FINESTRA_TESTO e SOGLIA_FREQUENTE (il secondo giro di per_testo_a_cascata)."""
    testo = scritto(domanda)
    entropia = {id_ for id_, tags in db.execute("SELECT id, tags FROM entities")
                if TAG_ENTROPIA in (tags or "").split(", ")}
    tolte = set(tolte) | entropia
    try:
        trovate = pagine_per_data(db, testo, tolte)[:n]
        termini = termini_testo(testo)
        escluse_rowid = {r for (r,) in db.execute(f"SELECT rowid FROM testo WHERE id IN ({','.join('?' * len(entropia))})",
                                                  sorted(entropia))}
        frequenti = frequenti_testo(db, termini, escluse_rowid, soglia_frequente)
        rare = rare_testo(db, termini, escluse_rowid)
        # fuori le parole comuni troppo frequenti; le rare con aspetto di nome diventano identificatori
        utili = [t._replace(forte=True) if t.chiave in rare else t for t in termini if t.chiave not in frequenti]
        deboli = [t for t in utili if not t.forte]
        if len(deboli) < 2 and not any(t.forte for t in utili):
            utili = []
        if utili and len(trovate) < n:
            minimo = max(2, -(-len(deboli) // 2))
            for id_, titolo, corpo, rtitolo, rcorpo, score in db.execute(
                    "SELECT id, titolo, corpo, radici_titolo, radici_corpo, "
                    "-bm25(testo, 0, 5.0, 1.0, 5.0, 1.0) AS score FROM testo WHERE testo MATCH ? "
                    "ORDER BY score DESC LIMIT 20", (" OR ".join(t.frase for t in utili),)):
                if id_ in tolte or id_ in trovate:
                    continue
                pagina = f" {norm(titolo + ' ' + corpo)} "  # intera, per gli identificatori
                pagina_radici = f" {rtitolo} {rcorpo} "
                presi = [t for t in utili if t.chiave in (pagina_radici if t.radice else pagina)]
                if any(t.forte for t in presi) or (score >= MIN_SCORE_TESTO and len(presi) >= minimo
                                                   and vicine(pagina_radici, [t.chiave for t in presi], minimo,
                                                              finestra)):
                    trovate.append(id_)
                    if len(trovate) == n:
                        break
        return trovate
    except sqlite3.OperationalError:  # graph.sqlite di una versione senza la tabella `testo` o senza le colonne radici_*
        return []


def per_testo_a_cascata(db, domanda, tolte=()):
    """Il ripiego sul testo in due giri: per_testo; se non trova nulla, un secondo giro con FINESTRA_TESTO_LARGA e
    SOGLIA_FREQUENTE_LARGA, al più MAX_TESTO_LARGO pagine. Recupera le domande parafrasate («il manifesto di
    collaudo», «il codice della settimana») con le parole un po' più lontane nella pagina o un po' più frequenti nel
    vault, senza toccare le domande che il primo giro già serve. Al più due giri: lo stop è fisso, non dipende
    dalle pagine trovate."""
    return (per_testo(db, domanda, tolte=tolte)
            or per_testo(db, domanda, MAX_TESTO_LARGO, tolte, FINESTRA_TESTO_LARGA, SOGLIA_FREQUENTE_LARGA))


def archi(db, nodi, solo_tipizzate, colonne=("source_id", "target_id")):
    segnaposto = ",".join("?" * len(nodi))
    escluse = sorted(GENERICHE if solo_tipizzate else {"documentato_in"})
    dove = " OR ".join(f"{c} IN ({segnaposto})" for c in colonne)
    return db.execute(
        f"SELECT source_id, target_id, type FROM relations "
        f"WHERE ({dove}) AND type NOT IN ({','.join('?' * len(escluse))})",
        [*(nodi * len(colonne)), *escluse]).fetchall()


def richiama(db, domanda, max_tipizzate=MAX_TIPIZZATE, max_menziona=MAX_MENZIONA, extra=()):
    """(semi, fatti, omessi): omessi = {"tipizzate": n, "menziona": n} sono i fatti fuori dai limiti."""
    # extra: punti di partenza venuti da fuori, es. le pagine lette per domande simili (memoria.py)
    domanda = scritto(domanda)
    semi = punti_di_partenza(db, domanda)
    semi += [p for p in extra if p not in semi]
    if not semi:
        return semi, [], {"tipizzate": 0, "menziona": 0}
    info = {id_: (tipo, descr) for id_, tipo, descr in db.execute("SELECT id, tipo, descrizione FROM entities")}
    grado = dict(db.execute(
        "SELECT id, COUNT(*) FROM (SELECT source_id AS id FROM relations WHERE type = 'menziona' "
        "UNION ALL SELECT target_id FROM relations WHERE type = 'menziona') GROUP BY id").fetchall())
    parole = {w for w in norm(domanda).split() if (len(w) >= 4 or w.isdigit()) and w not in STOPWORD}
    parole -= {w for s in semi for w in norm(s).split()}
    # Le pagine generate per entropia riassumono altre pagine: nominate nella domanda partono come le altre,
    # raggiunte dal cammino valgono un link generico, così non tolgono posti ai fatti delle pagine originali
    entropia = {id_ for id_, tags in db.execute("SELECT id, tags FROM entities")
                if TAG_ENTROPIA in (tags or "").split(", ")} - set(semi)

    fatti = {}  # coppia non orientata → fatto
    def aggiungi(s, t, tipo, passo, verso):
        chiave = frozenset((s, t))
        vecchio = fatti.get(chiave)
        if tipo == "menziona":
            if vecchio and vecchio["tipo"] != "menziona":
                return
            if vecchio and (vecchio["s"], vecchio["t"]) == (t, s):
                vecchio["reciproco"] = True
                return
            if vecchio:
                return
        elif vecchio and vecchio["tipo"] != "menziona" and vecchio["passo"] <= passo:
            return
        fatti[chiave] = {"s": s, "tipo": tipo, "t": t, "passo": passo, "verso": verso, "reciproco": False}

    for s, t, tipo in archi(db, semi, solo_tipizzate=False):
        if tipo == "menziona" and s in semi and t in semi:
            continue  # due pagine già nella domanda: il link fra loro non aggiunge nulla
        aggiungi(s, t, "menziona" if s in entropia else tipo, 1, "avanti" if s in semi else "indietro")
    # Dal 2° passo si proseguono solo le catene tipizzate, nello stesso verso del 1°:
    # A → X continua con X → Y, W → A con V → W; mai A → X ← B, perché B è solo un "fratello" di A
    for verso, colonna in (("avanti", "source_id"), ("indietro", "target_id")):
        visti = set(semi)
        for passo in range(2, PASSI[verso] + 1):
            fronte = sorted({f["t"] if verso == "avanti" else f["s"] for f in fatti.values()
                             if f["passo"] == passo - 1 and f["verso"] == verso and f["tipo"] != "menziona"} - visti)
            if not fronte:
                break
            visti |= set(fronte)
            for s, t, tipo in archi(db, fronte, True, (colonna,)):
                if s not in entropia:
                    aggiungi(s, t, tipo, passo, verso)

    def punteggio(f):
        altro = f["t"] if f["verso"] == "avanti" else f["s"]
        testo = set(norm(f"{altro} {info[altro][1] or ''}").split())
        p = PUNTI[f["passo"]] if f["tipo"] != "menziona" else 10
        p += 5 * f["reciproco"] + 3 * len(parole & testo) - math.log2(1 + grado.get(altro, 0))
        return round(p, 1)

    # Potatura: i fratelli (stessa relazione verso lo stesso nodo già raggiunto) diventano un fatto solo,
    # col punteggio del migliore, perché un hub non occupi tutti i posti
    gruppi = {}
    for f in fatti.values():
        f["punteggio"] = punteggio(f)
        chiave = (f["tipo"], f["verso"], f["s"] if f["verso"] == "avanti" else f["t"])
        gruppi.setdefault(chiave if f["tipo"] != "menziona" else id(f), []).append(f)
    elenco = []
    for membri in gruppi.values():
        membri.sort(key=lambda f: f["punteggio"], reverse=True)
        if len(membri) < FRATELLI:
            elenco += membri
        else:
            lato = "t" if membri[0]["verso"] == "avanti" else "s"
            elenco.append({**membri[0], lato: [m[lato] for m in membri]})
    # Un fatto raccolto da fratelli conta come uno. L'ordine finale resta per punteggio (le tipizzate vengono prima)
    ordinati = sorted(elenco, key=lambda f: f["punteggio"], reverse=True)
    tipizzate = [f for f in ordinati if f["tipo"] != "menziona"]
    generici = [f for f in ordinati if f["tipo"] == "menziona"]
    omessi = {"tipizzate": max(0, len(tipizzate) - max_tipizzate), "menziona": max(0, len(generici) - max_menziona)}
    tenuti = sorted(tipizzate[:max_tipizzate] + generici[:max_menziona], key=lambda f: f["punteggio"], reverse=True)
    return [(s, *info[s]) for s in semi], tenuti, omessi


def nodi(fatto):
    return [n for k in ("s", "t") for n in (fatto[k] if isinstance(fatto[k], list) else [fatto[k]])]


def formatta(semi, fatti, info, omessi=None):
    ids = {s[0] for s in semi}
    righe = [f"Dal grafo della wiki ({len(fatti)} fatti):"]
    for id_, tipo, descr in semi:
        righe.append(f"- {id_} [{tipo}]: {descr}")
    nome = lambda n: f"{len(n)} pagine ({', '.join(n)})" if isinstance(n, list) else n
    for f in fatti:
        freccia = "↔ menziona ↔" if f["reciproco"] else f"→ {f['tipo']} →"
        nuovo = f["t"] if f["verso"] == "avanti" else f["s"]
        dettaglio = "" if isinstance(nuovo, list) or nuovo in ids else f"  ({nuovo} [{info[nuovo][0]}]: {info[nuovo][1]})"
        righe.append(f"- {nome(f['s'])} {freccia} {nome(f['t'])}{dettaglio}")
    parti = [f"{omessi[k]} {testo}" for k, testo in (("tipizzate", "relazioni tipizzate omesse"),
                                                    ("menziona", "link generici omessi")) if omessi and omessi[k]]
    if parti:
        righe.append(f"({'; '.join(parti)}: il contesto è parziale, cercare nelle pagine se serve)")
    return "\n".join(righe)


def main():
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("domanda", nargs="?", help="la domanda; se assente si legge da stdin")
    ap.add_argument("--db", type=Path, default=qui / "graph.sqlite")
    ap.add_argument("--tipizzate", type=int, default=MAX_TIPIZZATE, help="tetto delle relazioni tipizzate")
    ap.add_argument("--menziona", type=int, default=MAX_MENZIONA, help="massimo di link generici")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not resolve_graph(args.db).exists():
        sys.exit(f"{args.db} non esiste: lanciare prima .graph/build_graph.py")

    db = connect_graph(args.db)
    domanda = args.domanda if args.domanda is not None else sys.stdin.read()
    semi, fatti, omessi = richiama(db, domanda, args.tipizzate, args.menziona)
    if not semi:
        return
    if args.json:
        result = {"semi": semi, "fatti": fatti, "omessi": omessi}
        if db.content_revision:
            result.update(content_revision=db.content_revision, graph_generation=db.graph_generation)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute("SELECT id, tipo, descrizione FROM entities")}
        print(formatta(semi, fatti, info, omessi))


if __name__ == "__main__":
    main()

"""La semantica delle relazioni letta dal grafo (doc/17, fase 2): ruoli, inverse, vincoli e il blocco di schema del recall.

Wiki reference.md dichiara, in sezioni facoltative, il ruolo di una relazione («dipendenza», «responsabile»,
«composizione», «causale», «sequenza»), il nome della sua inversa e le proprietà transitiva e simmetrica («Semantica
delle relazioni»), e i vincoli di cardinalità per tipo («Vincoli»). Il builder le copia in onto_relazioni
(ruolo, inversa, transitiva, simmetrica) e onto_cardinalita; questo modulo le legge per sintesi.py, domande.py, recall.py
e la dashboard. Sola lettura, nessun LLM.

I default sono quelli che il codice usava prima della fase 2 (RUOLI_DEFAULT) e non si scrivono mai nelle tabelle: una
relazione senza ruolo dichiarato ha il ruolo di default, una dichiarata lo sostituisce, e una sezione che dichiara solo
inverse non toglie a «causa» il suo ruolo causale. Senza le sezioni nulla cambia, byte per byte. Le generazioni del grafo
precedenti alla fase 2 (senza le colonne) usano i default. La sezione «Vincoli», se c'è, sostituisce il vincolo di
default sul referente (vincoli() restituisce None quando manca).
"""
import os
import sqlite3

# Il ruolo che le costanti di sintesi.py (CATENA), domande.py (CON_REFERENTE, parte_di) e read_api (/causal) davano a
# queste relazioni. L'ordine è quello di CATENA: relazioni_con_ruolo() lo conserva.
RUOLI_DEFAULT = {"usa": "dipendenza", "richiede": "dipendenza", "referente": "responsabile",
                 "parte_di": "composizione", "causa": "causale"}
MAX_SCHEMA_TOKEN = 300  # tetto del blocco «Schema pertinente» del recall (doc/17, livello 2)
GENERICHE = ("menziona", "documentato_in")  # archi derivati: non sono relazioni dell'ontologia


def _valore(db, chiave):
    try:
        riga = db.execute("SELECT valore FROM onto_metadata WHERE chiave = ?", (chiave,)).fetchone()
    except sqlite3.OperationalError:  # generazione precedente alle tabelle onto_*
        return None
    return riga[0] if riga else None


def dichiarata(db):
    """True se Wiki reference.md ha la sezione «Semantica delle relazioni» (metadato `semantica` del grafo)."""
    return _valore(db, "semantica") == "presente"


def _dichiarati(db):
    """{relazione: (ruolo, inversa)} come dichiarati, in ordine di tabella; vuoto se il grafo non ha le colonne."""
    try:
        return {nome: (ruolo, inversa) for nome, ruolo, inversa in
                db.execute("SELECT nome, ruolo, inversa FROM onto_relazioni ORDER BY posizione")}
    except sqlite3.OperationalError:
        return {}


def ruoli(db):
    """{relazione: ruolo}: i default di oggi, sostituiti dai ruoli dichiarati in Wiki reference.md."""
    risultato = dict(RUOLI_DEFAULT)
    for nome, (ruolo, _) in _dichiarati(db).items():
        if ruolo:
            risultato[nome] = ruolo
    return risultato


def relazioni_con_ruolo(db, *cercati):
    """Le relazioni che hanno uno dei ruoli `cercati`: prima i default nel loro ordine, poi le aggiunte dichiarate."""
    assegnati = ruoli(db)
    return tuple(nome for nome, ruolo in assegnati.items() if ruolo in cercati)


def inverse(db):
    """{relazione: nome dell'inversa} dichiarati; è un'etichetta di lettura, non un arco."""
    return {nome: inversa for nome, (_, inversa) in _dichiarati(db).items() if inversa}


def vincoli(db):
    """I vincoli dichiarati [{tipo, relazione, minimo, massimo, se_manca}] in ordine di tabella; None senza la sezione."""
    if _valore(db, "vincoli") != "presente":
        return None
    campi = ("tipo", "relazione", "minimo", "massimo", "se_manca")
    try:
        return [dict(zip(campi, riga)) for riga in db.execute(
            "SELECT tipo, relazione, minimo, massimo, se_manca FROM onto_cardinalita ORDER BY posizione")]
    except sqlite3.OperationalError:
        return None


def nomi_attributi(db):
    """I nomi degli attributi dichiarati in «Attributi» (onto_attributi); vuoto senza la sezione o in una generazione
    precedente alla fase 4."""
    try:
        return {nome for (nome,) in db.execute("SELECT DISTINCT nome FROM onto_attributi")}
    except sqlite3.OperationalError:
        return set()


def tipi_sotto(db, tipo):
    """Il tipo e tutti i suoi sottotipi (onto_tipi.padre): un vincolo su un tipo vale anche per loro."""
    try:
        padri = dict(db.execute("SELECT nome, padre FROM onto_tipi WHERE padre IS NOT NULL").fetchall())
    except sqlite3.OperationalError:
        return {tipo}
    trovati, cambiato = {tipo}, True
    while cambiato:
        nuovi = {nome for nome, padre in padri.items() if padre in trovati} - trovati
        cambiato = bool(nuovi)
        trovati |= nuovi
    return trovati


def schema_pertinente(db, fatti, massimo=MAX_SCHEMA_TOKEN):
    """Il blocco «Schema pertinente» del recall: il significato delle sole relazioni presenti nei `fatti`.

    Righe «- usa (dipendenza; inversa: è usato da): X funziona tramite Y», con i soli ruoli e le sole inverse dichiarati,
    entro `massimo` token (caratteri/4). Vuoto se la semantica non è dichiarata (senza la sezione il contesto non cambia),
    se nessun fatto ha una relazione dell'ontologia, se nemmeno una riga entra nel tetto, o con GRAFO_SENZA_SCHEMA=1."""
    if os.environ.get("GRAFO_SENZA_SCHEMA") or not dichiarata(db):
        return ""
    presenti = {fatto["tipo"] for fatto in fatti if fatto["tipo"] not in GENERICHE}
    if not presenti:
        return ""
    try:
        righe = db.execute("SELECT nome, significato, ruolo, inversa FROM onto_relazioni ORDER BY posizione").fetchall()
    except sqlite3.OperationalError:
        return ""
    intestazione = "Schema pertinente (relazioni dei fatti):"
    linee = []
    for nome, significato, ruolo, inversa in righe:
        if nome not in presenti:
            continue
        qualifiche = "; ".join(q for q in (ruolo, f"inversa: {inversa}" if inversa else "") if q)
        linea = f"- {nome}" + (f" ({qualifiche})" if qualifiche else "") + (f": {significato}" if significato else "")
        if len("\n".join([intestazione, *linee, linea])) // 4 > massimo:
            break
        linee.append(linea)
    return "\n".join([intestazione, *linee]) if linee else ""

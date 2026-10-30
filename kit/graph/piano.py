"""Controllo del piano di ingest: lo verifica prima che si scrivano le pagine, così l'utente corregge un file e non quindici.

Un piano (di norma `lavorazioni/_ingest/<fonte>-piano.md`, personale e fuori da Git) ha un titolo con la fonte e cinque sezioni:

  # Piano di ingest — raw/manuale-rilascio.md
  ## Pagine da creare            - [[Finestra di rilascio]] — tipo: processo — motivo
  ## Pagine da aggiornare        - [[Rilascio in produzione]] — motivo
  ## Relazioni                   - [[Rilascio in produzione]] → richiede → [[Finestra di rilascio]]
  ## Alias                       - [[Finestra di rilascio]]: «slot di rilascio», «finestra»
  ## Contraddizioni con il vault - testo libero, oppure «nessuna»

Controlli (exit 1 se ne trova): la fonte esiste in raw/; le cinque sezioni ci sono; le pagine da creare non esistono (e hanno un
tipo del catalogo, se il vault lo definisce) e quelle da aggiornare sì; nessun doppione né nome con ( ) / # | [ ]; le relazioni
stanno nel vocabolario, con tipi ammessi, e partono da una pagina del piano; gli alias sono di pagine del piano e non collidono
con nomi o alias esistenti. Solo lettura: non scrive nulla e non giudica se il piano è giusto, solo se è coerente col vault.

Uso:
  python .graph/piano.py lavorazioni/_ingest/manuale-rilascio-piano.md [--json]
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

import contratti
from build_graph import LINK, bersaglio, norm, parse_ontology, tipo_ammesso
from graph_db import GraphDatabaseError, connect_graph

SEZIONI = {"pagine da creare": "creare", "pagine da aggiornare": "aggiornare", "relazioni": "relazioni", "alias": "alias",
           "contraddizioni con il vault": "contraddizioni"}
FONTE = re.compile(r"raw/\S+?\.md")
RELAZIONE = re.compile(r"^\s*[-*]\s*\[\[([^\]]+)\]\]\s*(?:→|->)\s*([A-Za-z_]\w*)\s*(?:→|->)\s*\[\[([^\]]+)\]\]")
ALIAS = re.compile(r"«([^»]+)»")
TIPO = re.compile(r"\btipo:\s*([\w-]+)")
NOME_NON_VALIDO = re.compile(r"[()/\\#|\[\]]")
ELENCO = re.compile(r"^\s*[-*]\s+")


class PianoError(Exception):
    def __init__(self, codice, messaggio):
        super().__init__(f"{codice}: {messaggio}")
        self.codice = codice


def controlla(vault, percorso):
    """Problemi del piano: elenco di {codice, riga, messaggio} in ordine di riga, vuoto se è coerente col vault."""
    vault = Path(vault)
    try:
        testo = Path(percorso).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as errore:
        raise PianoError("piano_illeggibile", f"{percorso}: {errore}") from errore
    grafo = vault / ".graph/graph.sqlite"
    if not grafo.is_file():
        raise PianoError("grafo_assente", "grafo non trovato: eseguire python .graph/build_graph.py")
    try:
        db = connect_graph(grafo)
        try:
            pagine = {id_.lower(): id_ for (id_,) in db.execute("SELECT id FROM entities WHERE path LIKE 'wiki/%'")}
            tipi = dict(db.execute("SELECT id, tipo FROM entities WHERE path LIKE 'wiki/%'").fetchall())
            alias_esistenti = {norm(a): e for e, a in db.execute("SELECT entity_id, alias FROM aliases")}
        finally:
            db.close()
    except (sqlite3.Error, GraphDatabaseError) as errore:
        raise PianoError("grafo_non_leggibile", f"{errore}: rieseguire python .graph/build_graph.py") from errore
    schema = vault / "Wiki reference.md"
    ontologia = parse_ontology(schema.read_text(encoding="utf-8")) if schema.is_file() else None
    vocabolario = ontologia.vocabulary if ontologia else None
    catalogo = {t.name for t in ontologia.types} if ontologia is not None and ontologia.types is not None else None

    problemi = []

    def segnala(codice, riga, messaggio):
        problemi.append({"codice": codice, "riga": riga, "messaggio": messaggio})

    righe = [(n, r) for n, r, fuori in contratti.analizza(testo) if fuori]
    titolo = next(((n, r) for n, r in righe if r.startswith("# ")), None)
    fonte = FONTE.search(titolo[1]) if titolo else None
    if not fonte or ".." in fonte[0] or not (vault / fonte[0]).is_file():
        segnala("fonte_mancante", titolo[0] if titolo else 1,
                "il titolo deve indicare una fonte esistente in raw/, es. «# Piano di ingest — raw/manuale.md»")
    sezioni, corrente = {}, None
    for n, riga in righe:
        if riga.startswith("## "):
            corrente = SEZIONI.get(riga[3:].strip().lower())
            if corrente:
                sezioni.setdefault(corrente, [])
        elif corrente and ELENCO.match(riga):
            sezioni[corrente].append((n, riga))
    for nome, chiave in SEZIONI.items():
        if chiave not in sezioni:
            segnala("sezione_mancante", None, f"manca la sezione «## {nome.capitalize() if chiave != 'contraddizioni' else 'Contraddizioni con il vault'}»")

    def risolvi(grezzo):
        return pagine.get(bersaglio(grezzo).lower())

    nuove, aggiornate, tipo_nuove = {}, {}, {}
    for n, riga in sezioni.get("creare", []):
        collegamento = LINK.search(riga)
        if not collegamento:
            if "nessuna" not in riga.lower():
                segnala("riga_non_valida", n, "serve una pagina come [[Nome]]")
            continue
        nome = bersaglio(collegamento[1])
        if NOME_NON_VALIDO.search(collegamento[1]) or not nome:  # sul testo scritto: bersaglio() toglie già cartella e sezione
            segnala("nome_non_valido", n, f"«{collegamento[1]}»: i nomi di pagina non hanno ( ) / \\ # | [ ]")
        elif nome.lower() in nuove or nome.lower() in aggiornate:
            segnala("duplicato", n, f"[[{nome}]] compare più volte nel piano")
        elif nome.lower() in pagine:
            segnala("da_creare_esiste", n, f"[[{pagine[nome.lower()]}]] esiste già: spostarla in «Pagine da aggiornare»")
        else:
            nuove[nome.lower()] = nome
            tipo = TIPO.search(riga)
            if not tipo:
                segnala("da_creare_senza_tipo", n, f"[[{nome}]]: indicare il tipo, es. «— tipo: processo —»")
            else:
                tipo_nuove[nome.lower()] = tipo[1]
                if catalogo is not None and tipo[1] not in catalogo:
                    segnala("tipo_non_ammesso", n, f"[[{nome}]]: tipo «{tipo[1]}» non è nel catalogo dei tipi di Wiki reference.md")
    for n, riga in sezioni.get("aggiornare", []):
        collegamento = LINK.search(riga)
        if not collegamento:
            if "nessuna" not in riga.lower():
                segnala("riga_non_valida", n, "serve una pagina come [[Nome]]")
            continue
        nome = bersaglio(collegamento[1])
        if nome.lower() in aggiornate or nome.lower() in nuove:
            segnala("duplicato", n, f"[[{nome}]] compare più volte nel piano")
        elif risolvi(collegamento[1]) is None:
            segnala("da_aggiornare_inesistente", n, f"[[{nome}]] non esiste: spostarla in «Pagine da creare»")
        else:
            aggiornate[nome.lower()] = pagine[nome.lower()]

    def tipo_di(grezzo):
        nome = bersaglio(grezzo).lower()
        return tipo_nuove.get(nome) or tipi.get(pagine.get(nome))

    def nel_piano(grezzo):
        return bersaglio(grezzo).lower() in nuove or bersaglio(grezzo).lower() in aggiornate

    for n, riga in sezioni.get("relazioni", []):
        m = RELAZIONE.match(riga)
        if not m:
            if "nessuna" not in riga.lower():
                segnala("riga_non_valida", n, "usare [[Da]] → relazione → [[A]]")
            continue
        da, relazione, a = m[1], m[2], m[3]
        sconosciute = [x for x in (da, a) if risolvi(x) is None and bersaglio(x).lower() not in nuove]
        if sconosciute:
            segnala("pagina_ignota", n, f"[[{bersaglio(sconosciute[0])}]] non esiste e non è tra le pagine da creare")
            continue
        if not nel_piano(da):
            segnala("pagina_non_in_piano", n, f"[[{bersaglio(da)}]] porta la relazione nel frontmatter: aggiungerla a «Pagine da aggiornare»")
        if vocabolario is None:
            continue
        if relazione not in vocabolario:
            segnala("relazione_fuori_vocabolario", n, f"«{relazione}» non è nel vocabolario di Wiki reference.md")
            continue
        ammessi_da, ammessi_a = vocabolario[relazione]
        t_da, t_a = tipo_di(da), tipo_di(a)
        if not tipo_ammesso(ammessi_da, t_da, t_a) or not tipo_ammesso(ammessi_a, t_a, t_da):
            segnala("tipi_non_ammessi", n, f"[[{bersaglio(da)}]] ({t_da}) —{relazione}→ [[{bersaglio(a)}]] ({t_a}): tipi non ammessi")
    visti = {}
    for n, riga in sezioni.get("alias", []):
        collegamento = LINK.search(riga)
        if not collegamento:
            if "nessuna" not in riga.lower():
                segnala("riga_non_valida", n, "usare [[Pagina]]: «alias», «altro alias»")
            continue
        proprietario = pagine.get(bersaglio(collegamento[1]).lower()) or nuove.get(bersaglio(collegamento[1]).lower())
        if proprietario is None or not nel_piano(collegamento[1]):
            segnala("pagina_non_in_piano", n, f"[[{bersaglio(collegamento[1])}]] ha alias: serve tra le pagine da creare o da aggiornare")
            continue
        for alias in ALIAS.findall(riga):
            chiave = norm(alias)
            altro = alias_esistenti.get(chiave) or pagine.get(chiave) or visti.get(chiave)
            if altro and altro != proprietario and norm(altro) != norm(proprietario):
                segnala("alias_duplicato", n, f"«{alias}» è già un nome o un alias di [[{altro}]]")
            visti[chiave] = proprietario
    return sorted(problemi, key=lambda q: (q["riga"] or 0, q["codice"]))


def main(argv=None):
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("piano", type=Path)
    ap.add_argument("--vault", type=Path, default=qui.parent)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        problemi = controlla(args.vault, args.piano)
    except PianoError as errore:
        print(f"errore: {errore}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(problemi, ensure_ascii=False, indent=2))
    else:
        for q in problemi:
            print(f"{args.piano.name}:{q['riga'] or 1}: {q['codice']}: {q['messaggio']}")
        print(f"{args.piano.name}: " + (f"{len(problemi)} problemi" if problemi else "ok"))
    return 1 if problemi else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

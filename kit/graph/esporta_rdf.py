"""Export Turtle dello schema (doc/17, fase 5): tipi, categorie, relazioni, attributi, sinonimi e corrispondenze.

Dal grafo corrente (tabelle `onto_*` e `categorie`, costruite dal builder da Wiki reference.md) a un file Turtle, per
aprire lo schema in uno strumento di ontologie o confrontarlo con un vocabolario esterno. Solo lo schema, non le pagine.
Sola lettura, solo libreria standard, nessun rdflib.

    owl:Class + rdfs:subClassOf                     i tipi, col padre dei sottotipi
    skos:Concept + skos:broader                     le categorie, con la più ampia
    owl:ObjectProperty + rdfs:domain / rdfs:range   le relazioni, solo se il lato ammette un tipo solo
    owl:TransitiveProperty / owl:SymmetricProperty  le proprietà dichiarate in «Semantica delle relazioni»
    owl:DatatypeProperty                            gli attributi di pagina
    skos:altLabel "…"@it                            i sinonimi
    skos:exactMatch / skos:closeMatch               le corrispondenze con un vocabolario esterno
    prov:wasDerivedFrom                             la fonte di quel vocabolario

Mai `owl:inverseOf`: l'inversa dichiarata è un nome di lettura («è usato da»), non una relazione con un IRI. I CURIE delle
corrispondenze non hanno una mappa di prefissi nel vault: escono come `urn:curie:<curie>`. Gli IRI dei termini sono
`<base>tipo/<nome>`, `categoria/`, `relazione/`, `attributo/` e `fonte/`, con i nomi codificati in percentuale.

L'ordine è totale e il file non contiene date: ogni tripla è una riga `soggetto predicato oggetto .`, ordinata per soggetto,
predicato, oggetto; due esecuzioni sullo stesso grafo producono byte identici, con fine riga LF. Le tabelle che una
generazione più vecchia non ha si saltano.

Uso: python .graph/esporta_rdf.py [--db .graph/graph.sqlite] [--base https://example.org/teseo/] [--out schema.ttl]
Esce con 0, o con 2 se la base non è valida o il grafo manca.
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

from graph_db import connect_graph, resolve_graph

BASE_DEFAULT = "https://example.org/teseo/"
BASE = re.compile(r"https?://[^\s<>\"{}|\\^`]+[/#]")
PREFISSI = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "prov": "http://www.w3.org/ns/prov#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
TIPO_XSD = {"data": "xsd:date", "numero": "xsd:decimal", "sì/no": "xsd:boolean", "testo": "xsd:string",
            "codice": "xsd:string", "importo": "xsd:string"}  # categoria:X → skos:Concept
GENERICI = {"qualsiasi", "stesso tipo"}  # i jolly dei vincoli: nessun dominio né codominio
FUGHE = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def controlla_base(base):
    if not isinstance(base, str) or not BASE.fullmatch(base):
        raise ValueError(f"base IRI non valida: {base!r} (attesa http(s)://… che finisca per / o #)")
    return base


def iri(base, genere, nome):
    """L'IRI di un termine dello schema: `<base>genere/nome`, il nome codificato in percentuale."""
    return f"<{base}{genere}/{quote(nome, safe='')}>"


def iri_esterno(valore):
    """L'IRI di una corrispondenza: assoluto com'è (`scheme://…`, `urn:…`), un CURIE come `urn:curie:<curie>`."""
    pulito = re.sub(r"[\x00-\x20<>\"{}|\\^`]", lambda m: "%%%02X" % ord(m[0]), valore)
    if re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", pulito) or pulito.startswith("urn:"):
        return f"<{pulito}>"
    return f"<urn:curie:{pulito}>"


def letterale(testo, lingua=None):
    """Una stringa Turtle con le fughe di `\\`, `"`, a capo, ritorno e tabulazione, e `\\uXXXX` per gli altri controlli."""
    corpo = "".join(FUGHE.get(c) or (f"\\u{ord(c):04X}" if ord(c) < 32 or ord(c) == 127 else c) for c in testo)
    return f'"{corpo}"' + (f"@{lingua}" if lingua else "")


def leggi(db, interrogazione, *alternative):
    """Le righe di una query; la prima che la generazione sa eseguire (le colonne di una versione più vecchia mancano)."""
    for testo in (interrogazione, *alternative):
        try:
            return db.execute(testo).fetchall()
        except sqlite3.OperationalError:
            continue
    return []


def esporta(db, base=BASE_DEFAULT):
    """Il Turtle dello schema del grafo `db` (una connessione sqlite3) come testo, con righe terminate da LF."""
    base = controlla_base(base)
    triple = {(f"<{base}>", "rdf:type", "owl:Ontology")}

    def aggiungi(soggetto, predicato, oggetto):
        triple.add((soggetto, predicato, oggetto))

    tipi = leggi(db, "SELECT nome, descrizione, padre FROM onto_tipi")
    for nome, descrizione, padre in tipi:
        soggetto = iri(base, "tipo", nome)
        aggiungi(soggetto, "rdf:type", "owl:Class")
        aggiungi(soggetto, "rdfs:label", letterale(nome))
        if descrizione:
            aggiungi(soggetto, "rdfs:comment", letterale(descrizione, "it"))
        if padre:
            aggiungi(soggetto, "rdfs:subClassOf", iri(base, "tipo", padre))

    categorie = leggi(db, "SELECT nome, padre, descrizione FROM categorie")
    for nome, padre, descrizione in categorie:
        soggetto = iri(base, "categoria", nome)
        aggiungi(soggetto, "rdf:type", "skos:Concept")
        aggiungi(soggetto, "skos:prefLabel", letterale(nome, "it"))
        if descrizione:
            aggiungi(soggetto, "skos:definition", letterale(descrizione, "it"))
        if padre:
            aggiungi(soggetto, "skos:broader", iri(base, "categoria", padre))

    lati = {}
    for relazione, lato, tipo in leggi(db, "SELECT relazione, lato, tipo FROM onto_vincoli"):
        lati.setdefault((relazione, lato), []).append(tipo)
    relazioni = leggi(db, "SELECT nome, significato, transitiva, simmetrica FROM onto_relazioni",
                      "SELECT nome, significato, 0, 0 FROM onto_relazioni")
    for nome, significato, transitiva, simmetrica in relazioni:
        soggetto = iri(base, "relazione", nome)
        aggiungi(soggetto, "rdf:type", "owl:ObjectProperty")
        aggiungi(soggetto, "rdfs:label", letterale(nome))
        if significato:
            aggiungi(soggetto, "rdfs:comment", letterale(significato, "it"))
        for predicato, lato in (("rdfs:domain", "da"), ("rdfs:range", "a")):
            ammessi = lati.get((nome, lato), [])
            if len(ammessi) == 1 and ammessi[0] not in GENERICI:  # univoco: altrimenti nessuna affermazione
                aggiungi(soggetto, predicato, iri(base, "tipo", ammessi[0]))
        if transitiva:
            aggiungi(soggetto, "rdf:type", "owl:TransitiveProperty")
        if simmetrica:
            aggiungi(soggetto, "rdf:type", "owl:SymmetricProperty")

    per_attributo = {}
    for nome, tipo, valore, descrizione in leggi(db, "SELECT nome, tipo, valore, descrizione FROM onto_attributi"):
        per_attributo.setdefault(nome, []).append((tipo, valore, descrizione))
    for nome, righe in per_attributo.items():
        soggetto = iri(base, "attributo", nome)
        aggiungi(soggetto, "rdf:type", "owl:DatatypeProperty")
        aggiungi(soggetto, "rdfs:label", letterale(nome))
        for descrizione in {d for _, _, d in righe if d}:
            aggiungi(soggetto, "rdfs:comment", letterale(descrizione, "it"))
        domini = {tipo for tipo, _, _ in righe}
        if len(domini) == 1:
            aggiungi(soggetto, "rdfs:domain", iri(base, "tipo", next(iter(domini))))
        codominii = {"skos:Concept" if valore.startswith("categoria:") else TIPO_XSD.get(valore, "xsd:string")
                     for _, valore, _ in righe}
        if len(codominii) == 1:
            aggiungi(soggetto, "rdfs:range", next(iter(codominii)))

    genere = {nome: "tipo" for nome, _, _ in tipi}
    genere.update({nome: "categoria" for nome, _, _ in categorie})
    for nome, sinonimo in leggi(db, "SELECT nome, sinonimo FROM onto_sinonimi"):
        if nome in genere:
            aggiungi(iri(base, genere[nome], nome), "skos:altLabel", letterale(sinonimo, "it"))
    for nome, corrispondenza, vocabolario, esattezza in leggi(
            db, "SELECT nome, iri, vocabolario, esattezza FROM onto_corrispondenze"):
        if nome in genere:
            soggetto = iri(base, genere[nome], nome)
            aggiungi(soggetto, "skos:exactMatch" if esattezza == "esatta" else "skos:closeMatch",
                     iri_esterno(corrispondenza))
            aggiungi(soggetto, "prov:wasDerivedFrom", iri(base, "fonte", vocabolario))

    intestazione = [f"@prefix {nome}: <{PREFISSI[nome]}> ." for nome in sorted(PREFISSI)]
    corpo = [f"{s} {p} {o} ." for s, p, o in sorted(triple)]
    return "\n".join([*intestazione, "", *corpo]) + "\n"


def main(argv=None):
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=qui / "graph.sqlite")
    ap.add_argument("--base", default=BASE_DEFAULT, help="IRI di base dei termini (http(s)://… che finisce per / o #)")
    ap.add_argument("--out", type=Path, help="scrive il Turtle in questo file invece che su stdout")
    args = ap.parse_args(argv)
    try:
        controlla_base(args.base)
    except ValueError as errore:
        print(f"errore: {errore}", file=sys.stderr)
        return 2
    if not resolve_graph(args.db).exists():
        print(f"errore: {args.db} non esiste: lanciare prima .graph/build_graph.py", file=sys.stderr)
        return 2
    db = connect_graph(args.db)
    try:
        testo = esporta(db, args.base)
    finally:
        db.close()
    if args.out:
        args.out.write_bytes(testo.encode("utf-8"))  # LF su ogni piattaforma
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write(testo)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Costruisce il grafo dal vault. Deterministico: nessun LLM.

Con manifest progetto compatibile pubblica generazioni in .teseo/local/graphs/;
nei vault legacy mantiene .graph/graph.sqlite. Nessuna adozione implicita.

Nodi: ogni pagina di wiki/ (id = nome del file) e ogni chiave citata in `fonti`.
Archi:
  - proprietà del frontmatter con valori "[[link]]"  → relazione tipizzata (tipo = nome proprietà)
  - [[link]] nel corpo della pagina                  → `menziona`
  - chiavi in `fonti`                                → `documentato_in`
Alias: proprietà `aliases` del frontmatter.
Testo: tabella FTS5 `testo` (id pagina, titolo, corpo senza frontmatter) per il ripiego di recall.per_testo, quando
il grafo non riconosce nessuna pagina. Il corpo è intero, blocchi di codice compresi (nomi di tabelle e comandi stanno
spesso in backtick: sono ciò che si cerca). Ci sono anche le pagine `entropia`: sono riassunti, ma escluderle qui
renderebbe la scelta irreversibile senza ricostruire; le esclude il recall (il tag è in entities.tags).
Tokenizer `unicode61 remove_diacritics 2`: senza accenti e maiuscole, `_` `-` `.` separano le parole.
Le colonne `radici_titolo` e `radici_corpo` hanno lo stesso testo già ridotto a radici (ridotto: norm + stemmer.stem
parola per parola): FTS5 non può usare uno stemmer Python come tokenizer, quindi lo si applica prima, all'indicizzazione
e (in recall.py) alla query. «rilasciare» e «rilascio» hanno la stessa radice e si trovano; titolo e corpo restano
interi per gli identificatori (FattureRicevute) e le frasi esatte.
Varianti grafiche dei nomi (tabella `varianti`, generata): per ogni nome di pagina e alias la forma spezzata
(ServiceDesk → «Service Desk», Web2Print → «Web 2 Print») e, per i nomi a più parole, quella attaccata («Modulo fatture» →
«ModuloFatture»), così «service desk» trova ServiceDesk. Una variante che coincide con un nome, un alias o una variante
di un'altra pagina si scarta (varianti_nomi).
Vocabolario delle relazioni: tabella "## Relazioni tipizzate" in Wiki reference.md (se presente).

Uso:
  python .graph/build_graph.py            ricostruisce graph.sqlite
  python .graph/build_graph.py --check    valida e ricostruisce solo se valido (exit 1 per problemi)
Anche senza --check un grafo invalido non sostituisce quello precedente.
Una pagina con frontmatter YAML non valido non si salta: il build si ferma con un errore che ne dice il nome
(ValueError da leggi; da riga di comando «errore: ...», exit 1).
"""
import argparse
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

try:
    from .stemmer import stem
except ImportError:
    from stemmer import stem

# Nomi che sono anche parole comuni: valgono solo scritti con la maiuscola (stessa lista di recall.PAROLE_COMUNI,
# che non si può importare da qui: recall importa build_graph)
PAROLE_COMUNI_NOMI = {"portale"}  # da adattare
NON_RELAZIONI = {"tipo", "tags", "fonti", "aggiornato", "aliases"}
PAGINE_SCHEMA = {"index", "log", "wiki reference"}  # link ammessi, ma non sono nodi del grafo

LINK = re.compile(r"!?\[\[([^\]]+?)\]\]")
CODICE = re.compile(r"^(```|~~~).*?^\1|`[^`\n]*`", re.M | re.S)
RIGA_FONTE = re.compile(r"^\|\s*`([a-z][\w.-]*)`\s*\|\s*([^|]*)\|", re.M)
RIGA_INDICE = re.compile(r"^\|\s*\[\[([^\]]+?)\]\]\s*\|\s*(.+?)\s*\|\s*$", re.M)
RIGA_RELAZIONE = re.compile(r"^\|\s*`(\w+)`\s*\|([^|]*)\|([^|]*)\|", re.M)


@lru_cache(maxsize=8192)  # recall.py normalizza a ogni domanda tutti i nomi e gli alias: sempre gli stessi
def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def ridotto(testo):
    """Il testo normalizzato (norm) con ogni parola ridotta alla radice (stemmer.stem): «rilasciare il rilascio» →
    «rilasc il rilasc». È la forma che sta nelle colonne `radici_*` di `testo` e con cui recall.py cerca le parole."""
    return " ".join(stem(w) for w in norm(testo).split())


# DBMonitor → DB|Monitor (sigla seguita da parola), ServiceDesk → Service|Desk, Web2Print → Web|2|Print, ACME0 → ACME|0
SPEZZA = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")
MAX_PAROLE_ATTACCATE = 3  # «Modulo fatture» → modulofatture sì; un titolo di 6 parole attaccate non lo scrive nessuno
MIN_VARIANTE = 4          # caratteri (norm): «y 0» o «ai 7» come variante sarebbero rumore


def varianti_nomi(nomi):
    """[(id pagina, variante)] dai nomi di pagina e dagli alias `nomi` = [(id, nome)]: forma spezzata e attaccata.

    Spezzata: ogni parola scritta CamelCase o con cifre e lettere attaccate si divide ai confini («DBMonitor» →
    «db monitor», «HelpU4» → «help u 4»): chi scrive «DB Monitor» con lo spazio la trova. Attaccata: i nomi di 2-3
    parole senza maiuscole interne si fondono («modulo fatture» → «modulofatture»). Entrambe sono confrontate dopo
    norm, quindi le maiuscole non contano. Si scartano: le varianti uguali (dopo norm) a un nome, a un alias o a
    una variante di un'altra pagina (resterebbe ambigua: nessuna delle due), quelle già implicite nel nome
    (stessa forma dopo norm), quelle sotto MIN_VARIANTE caratteri, e le parole comuni (PAROLE_COMUNI nel recall
    valgono solo con la maiuscola: una variante non ha modo di dirlo)."""
    proprietari = {}  # norm → insieme di pagine che hanno quel nome, alias o variante
    for id_, nome in nomi:
        proprietari.setdefault(norm(nome), set()).add(id_)
    candidate = {}  # norm → (variante, pagina)
    for id_, nome in nomi:
        forme = set()
        pezzi = re.split(r"[^A-Za-z0-9]+", nome)
        spezzata = " ".join(p for w in pezzi for p in SPEZZA.split(w) if p)
        forme.add(spezzata)
        if 1 < len(norm(nome).split()) <= MAX_PAROLE_ATTACCATE:
            forme.add("".join(norm(nome).split()))
        for forma in forme:
            n = norm(forma)
            if len(n) < MIN_VARIANTE or n in PAROLE_COMUNI_NOMI or n == norm(nome):
                continue
            if proprietari.get(n, {id_}) - {id_}:  # appartiene (anche) a un'altra pagina
                continue
            candidate.setdefault(n, (forma, set()))[1].add(id_)
    return sorted((id_, forma) for n, (forma, ids) in candidate.items() if len(ids) == 1
                  and n not in proprietari for id_ in ids)


def bersaglio(raw):
    # [[cartella/Pagina#sezione\|testo]] → Pagina (la pipe è escapata dentro le tabelle)
    t = raw.replace("\\|", "|").split("|", 1)[0].split("#", 1)[0]
    return t.rsplit("/", 1)[-1].strip()


def valori(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [x for i in v for x in valori(i)]
    return [str(v)]


def leggi(path):
    testo = path.read_text(encoding="utf-8").lstrip("﻿")
    if testo.startswith("---"):
        fine = testo.find("\n---", 3)
        if fine != -1:
            try:
                fm = yaml.safe_load(testo[3:fine])
                if fm is None:
                    fm = {}
                if not isinstance(fm, dict):
                    raise ValueError(f"{path.name}: frontmatter deve essere una mappa YAML")
                return fm, testo[fine + 4:]
            except yaml.YAMLError as e:  # senza il nome della pagina l'errore di yaml non dice dove cercare
                raise ValueError(f"{path.name}: frontmatter non valido ({str(e).strip().splitlines()[0]})") from e
        raise ValueError(f"{path.name}: frontmatter senza delimitatore di chiusura")
    return {}, testo


def leggi_vocabolario(ref):
    m = re.search(r"^## Relazioni tipizzate\s*$(.*?)(?=^## |\Z)", ref, re.M | re.S)
    if not m:
        return None
    lista = lambda s: {x.strip() for x in s.split(",") if x.strip()}
    return {nome: (lista(da), lista(a)) for nome, da, a in RIGA_RELAZIONE.findall(m.group(1))}


def tipo_ammesso(ammessi, tipo, tipo_altro):
    return "qualsiasi" in ammessi or tipo in ammessi or ("stesso tipo" in ammessi and tipo == tipo_altro)


def parse_snapshot(vault):
    """Legge i sorgenti in memoria senza scrivere il DB.

    Il chiamante futuro deve fornire uno snapshot stabile: questa lettura legacy
    non offre ancora isolamento dagli editor o coordinamento degli scrittori.
    """
    if not (vault / "wiki").is_dir():
        raise ValueError("vault non valido: directory wiki/ assente")
    ref_path = vault / "Wiki reference.md"
    ref = ref_path.read_text(encoding="utf-8") if ref_path.exists() else ""
    indice = vault / "index.md"
    descrizioni = {}
    if indice.exists():
        for link, riga in RIGA_INDICE.findall(indice.read_text(encoding="utf-8")):
            descrizioni[bersaglio(link)] = riga
    fonti_censite = {k: f.strip().strip("`").strip() for k, f in RIGA_FONTE.findall(ref)}
    vocabolario = leggi_vocabolario(ref)

    files = sorted((vault / "wiki").glob("*.md"))
    if len({p.stem.casefold() for p in files}) != len(files):
        raise ValueError("wiki/: nomi pagina con collisione di maiuscole/minuscole")
    pagine = {p.stem: leggi(p) for p in files}
    nomi = {p.lower(): p for p in pagine}
    problemi = []
    entita, relazioni, alias = [], set(), []

    def risolvi(pagina, raw, dove):
        t = bersaglio(raw)
        if t.lower() in nomi:
            return nomi[t.lower()]
        if t.lower() not in PAGINE_SCHEMA:
            problemi.append(f"{pagina}: link non risolto [[{t}]] ({dove})")
        return None

    fonti_usate = set()
    for nome, (fm, corpo) in pagine.items():
        entita.append((nome, fm.get("tipo"), descrizioni.get(nome), f"wiki/{nome}.md",
                       ", ".join(valori(fm.get("tags"))), str(fm.get("aggiornato") or "")))
        for a in valori(fm.get("aliases")):
            alias.append((nome, a))
        for chiave in valori(fm.get("fonti")):
            fonti_usate.add(chiave)
            relazioni.add((nome, chiave, "documentato_in"))
        for prop, v in fm.items():
            if prop in NON_RELAZIONI:
                continue
            links = [l for s in valori(v) for l in LINK.findall(s)]
            if not links:
                problemi.append(f"{nome}: proprietà '{prop}' senza link (nel frontmatter i link vanno tra virgolette)")
            for l in links:
                t = risolvi(nome, l, f"proprietà {prop}")
                if t and t != nome:
                    relazioni.add((nome, t, prop))
        for l in LINK.findall(CODICE.sub("", corpo)):
            t = risolvi(nome, l, "testo")
            if t and t != nome:
                relazioni.add((nome, t, "menziona"))

    for chiave in sorted(fonti_usate):
        if chiave in nomi:
            raise ValueError(f"la fonte '{chiave}' ha lo stesso nome di una pagina")
        if chiave not in fonti_censite:
            problemi.append(f"fonte '{chiave}' usata ma non censita in Wiki reference")
        entita.append((chiave, "fonte", fonti_censite.get(chiave), None, "", ""))

    # Controlli su relazioni tipizzate e alias
    tipi = {e[0]: e[1] for e in entita}
    tipizzate = [r for r in relazioni if r[2] not in ("menziona", "documentato_in")]
    for s, t, rel in sorted(tipizzate):
        if vocabolario is None:
            continue
        if rel not in vocabolario:
            problemi.append(f"{s}: relazione '{rel}' fuori vocabolario")
            continue
        da, a = vocabolario[rel]
        if not tipo_ammesso(da, tipi[s], tipi[t]) or not tipo_ammesso(a, tipi[t], tipi[s]):
            problemi.append(f"{s} ({tipi[s]}) —{rel}→ {t} ({tipi[t]}): tipi non ammessi dal vocabolario")
    visti = {norm(p): p for p in pagine}
    for nome, a in alias:
        altro = visti.setdefault(norm(a), nome)
        if altro != nome:
            problemi.append(f"alias '{a}' di {nome} coincide con {altro}")

    return {"pagine": pagine, "entita": entita, "relazioni": relazioni,
            "alias": alias, "problemi": tuple(problemi), "fonti_usate": fonti_usate,
            "tipizzate": tipizzate, "vocabolario": vocabolario}


class GraphValidationError(ValueError):
    def __init__(self, problemi):
        self.problemi = tuple(problemi)
        super().__init__("; ".join(self.problemi))


def validate_snapshot(snapshot):
    """Diagnostica deterministica dei dati già letti, senza pubblicazione."""
    return snapshot["problemi"]


def build_candidate(snapshot, out):
    """Candidato unico nello stesso filesystem, connessione chiusa prima del return."""
    problemi = validate_snapshot(snapshot)
    if problemi:
        raise GraphValidationError(problemi)
    fd, name = tempfile.mkstemp(prefix=f".{out.name}-", suffix=".tmp", dir=out.parent)
    os.close(fd)
    tmp = Path(name)
    db = None
    try:
        db = sqlite3.connect(tmp)
        db.executescript("""
        CREATE TABLE entities (id TEXT PRIMARY KEY, tipo TEXT, descrizione TEXT, path TEXT, tags TEXT, aggiornato TEXT);
        CREATE TABLE relations (source_id TEXT, target_id TEXT, type TEXT, UNIQUE (source_id, target_id, type));
        CREATE TABLE aliases (entity_id TEXT, alias TEXT);
        CREATE INDEX relations_source ON relations (source_id);
        CREATE INDEX relations_target ON relations (target_id);
        CREATE TABLE varianti (entity_id TEXT, variante TEXT);
        CREATE VIRTUAL TABLE testo USING fts5(id UNINDEXED, titolo, corpo, radici_titolo, radici_corpo,
                                              tokenize = 'unicode61 remove_diacritics 2');
        """)
        pagine, alias = snapshot["pagine"], snapshot["alias"]
        db.executemany("INSERT INTO entities VALUES (?,?,?,?,?,?)", snapshot["entita"])
        db.executemany("INSERT INTO relations VALUES (?,?,?)", sorted(snapshot["relazioni"]))
        db.executemany("INSERT INTO aliases VALUES (?,?)", alias)
        db.executemany("INSERT INTO varianti VALUES (?,?)",
                       varianti_nomi([(nome, nome) for nome in pagine] + alias))
        db.executemany("INSERT INTO testo VALUES (?,?,?,?,?)",
                       [(nome, nome, corpo, ridotto(nome), ridotto(corpo)) for nome, (_, corpo) in pagine.items()])
        db.commit()
    except BaseException:
        if db is not None:
            db.close()
            db = None
        tmp.unlink(missing_ok=True)
        raise
    finally:
        if db is not None:
            db.close()
    return tmp


def publish_generation(candidate, out):
    """Compatibilità graph.sqlite: valida SQLite e sostituisce solo a DB chiuso.

    Non implementa ancora le generazioni immutabili. Se un lettore Windows nega
    il replace, l'errore risale al chiamante e il vecchio grafo resta corrente.
    """
    db = sqlite3.connect(candidate.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("candidato SQLite non integro")
    finally:
        db.close()
    os.replace(candidate, out)


def costruisci(vault, out):
    managed = (vault / ".teseo/project.json").exists() or (vault / ".teseo/local/graph-current.json").exists()
    if out.resolve() == (vault / ".graph/graph.sqlite").resolve() and managed:
        try:
            from ..dashboard.graph_service import rebuild
        except ImportError:
            from dashboard.graph_service import rebuild
        reference = rebuild(vault)
        print(f"→ {reference.path} · revisione {reference.content_revision}")
        return []
    snapshot = parse_snapshot(vault)
    candidate = build_candidate(snapshot, out)
    try:
        publish_generation(candidate, out)
    finally:
        candidate.unlink(missing_ok=True)

    pagine, relazioni = snapshot["pagine"], snapshot["relazioni"]
    fonti_usate, tipizzate = snapshot["fonti_usate"], snapshot["tipizzate"]
    alias, vocabolario = snapshot["alias"], snapshot["vocabolario"]
    conta = lambda tipo: sum(1 for r in relazioni if r[2] == tipo)
    print(f"{len(pagine)} pagine, {len(fonti_usate)} fonti · {conta('menziona')} menziona, "
          f"{conta('documentato_in')} documentato_in, {len(tipizzate)} tipizzate, {len(alias)} alias"
          f"{'' if vocabolario is not None else ' · vocabolario non definito in Wiki reference'}")
    print(f"→ {out}")
    return []


def main():
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vault", type=Path, default=qui.parent)
    ap.add_argument("--out", type=Path, default=qui / "graph.sqlite")
    ap.add_argument("--check", action="store_true", help="valida e pubblica solo se valido; exit 1 per problemi")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    try:
        problemi = costruisci(args.vault, args.out)
    except GraphValidationError as e:
        for problema in e.problemi:
            print(f"  ⚠️ {problema}")
        print(f"{len(e.problemi)} problemi · grafo precedente conservato")
        sys.exit(1)
    except (ValueError, OSError, sqlite3.Error) as e:
        sys.exit(f"errore: {e}")
    if args.check:
        for p in problemi:
            print(f"  ⚠️ {p}")
        print(f"{len(problemi)} problemi" if problemi else "nessun problema")
        sys.exit(1 if problemi else 0)


if __name__ == "__main__":
    main()

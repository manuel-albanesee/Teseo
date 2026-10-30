"""Validatore dei contratti ICM: sezioni, file citati negli Input, riferimenti in avanti, segnaposto, lunghezza.

Un contratto (SKILL.md o CONTEXT.md di una fase) ha la forma canonica, nell'ordine:
  ## Input (obbligatoria)    tabella Livello | File | Sezione | Perché: livello 3 = regole stabili, 4 = materiale dell'esecuzione
  ## Processo (obbligatoria)
  ## Checkpoint              facoltativa; se c'è sta fra Processo e Verifica
  ## Verifica (obbligatoria)
  ## Output (obbligatoria)
Altre sezioni (note operative, descrizioni) sono ammesse in qualsiasi posizione.

Controlli (errori, exit 1): sezione_mancante, sezioni_fuori_ordine, file_illeggibile, input_senza_tabella, input_colonne,
input_file_mancante (solo livello 3: il livello 4 nasce a runtime), input_sezione_mancante (titolo «…» assente nel file
citato), riferimento_in_avanti (una fase NN-* cita una fase con numero maggiore), segnaposto ({{NOME}} non compilato
fuori dai blocchi di codice). Avviso (exit invariato): troppo_lungo. Solo lettura, nessun LLM.

Nella colonna File conta il primo testo fra apici inversi; si ignorano le celle senza apici, i comandi (python, git…),
i testi con virgolette o <>|*? e i percorsi con {segnaposto} di esecuzione. I percorsi si risolvono rispetto al
contratto e a --radice (di norma la radice del vault).

Uso:
  python .graph/contratti.py kit/skills/obsidian-wiki-query/SKILL.md --radice kit/vault
  python .graph/contratti.py lavorazioni/report/fasi/*/CONTEXT.md --radice . --json
  python .graph/contratti.py kit/skills/obsidian-wiki-query/SKILL.md --radice kit/vault --peso     quanto contesto carica
"""
import argparse
import json
import re
import sys
from pathlib import Path

SEZIONI = ("input", "processo", "checkpoint", "verifica", "output")
OBBLIGATORIE = ("input", "processo", "verifica", "output")
MAX_RIGHE = 80                                   # un contratto è routing, non contenuto (ICM, pattern 6)
TITOLO = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SEGNAPOSTO = re.compile(r"\{\{[A-Z_][A-Z0-9_]*\}\}")
CODICE_IN_RIGA = re.compile(r"`[^`]*`")
COMANDO = re.compile(r"(python3?|py|git|sh|bash|node|npm)\s")
FASE = re.compile(r"^(\d{2})-")


def analizza(testo):
    """Righe (numero 1-based, testo, fuori_da_codice) senza il frontmatter; le righe dei blocchi recintati sono marcate."""
    righe = testo.splitlines()
    inizio = 0
    if righe and righe[0].strip() == "---":
        chiusura = next((i for i in range(1, len(righe)) if righe[i].strip() == "---"), None)
        inizio = 0 if chiusura is None else chiusura + 1
    risultato, recinto = [], None
    for n in range(inizio, len(righe)):
        riga, marcatore = righe[n], righe[n].lstrip()[:3]
        if recinto is None and marcatore in ("```", "~~~"):
            recinto = marcatore
            risultato.append((n + 1, riga, False))
        elif recinto is not None and marcatore == recinto:
            recinto = None
            risultato.append((n + 1, riga, False))
        else:
            risultato.append((n + 1, riga, recinto is None))
    return risultato


def titoli(righe):
    """Titoli (numero di riga, livello, testo) fuori dai blocchi di codice."""
    return [(n, len(m[1]), m[2].strip()) for n, riga, fuori in righe if fuori and (m := TITOLO.match(riga))]


def celle(riga):
    """Celle di una riga di tabella Markdown; il | dentro gli apici inversi o preceduto da \\ non separa."""
    risultato, corrente, in_codice, prec = [], "", False, ""
    for c in riga.strip():
        if c == "`":
            in_codice = not in_codice
        if c == "|" and not in_codice and prec != "\\":
            risultato.append(corrente.strip())
            corrente = ""
        else:
            corrente += c
        prec = c
    risultato.append(corrente.strip())
    return risultato[1:-1] if riga.strip().endswith("|") else risultato[1:]


def problema(codice, riga, messaggio):
    return {"codice": codice, "riga": riga, "messaggio": messaggio}


def _intestazioni(percorso, cache):
    if percorso not in cache:
        try:
            cache[percorso] = [t.lower() for _, _, t in titoli(analizza(percorso.read_text(encoding="utf-8", errors="replace")))]
        except OSError:
            cache[percorso] = []
    return cache[percorso]


def _tabella_input(righe, titoli_trovati):
    """Righe `|` della sezione Input (numero, testo)."""
    inizio = next((n for n, livello, t in titoli_trovati if livello == 2 and t.lower() == "input"), None)
    if inizio is None:
        return []
    fine = next((n for n, livello, _ in titoli_trovati if n > inizio and livello <= 2), None)
    return [(n, riga) for n, riga, fuori in righe
            if fuori and n > inizio and (fine is None or n < fine) and riga.lstrip().startswith("|")]


def _colonne(intestazione):
    """Indici delle colonne file, sezione e livello della tabella Input (None se mancano)."""
    celle_minuscole = [c.lower() for c in intestazione]
    return {nome: next((i for i, c in enumerate(celle_minuscole) if chiave in c), None)
            for nome, chiave in (("file", "file"), ("sezione", "sezion"), ("livello", "livell"))}


def _voce(valori, colonna):
    """(file citato, livello come cifra o None, titoli di sezione richiesti) di una riga di Input; None se non cita un file."""
    if len(valori) <= colonna["file"]:
        return None
    apici = re.search(r"`([^`]+)`", valori[colonna["file"]])
    if not apici:
        return None
    cita = apici[1].strip()
    if COMANDO.match(cita) or any(c in cita for c in "\"'<>|*?"):
        return None
    livello = re.search(r"\d", valori[colonna["livello"]]) if colonna["livello"] is not None and colonna["livello"] < len(valori) else None
    cella_sezione = valori[colonna["sezione"]] if colonna["sezione"] is not None and colonna["sezione"] < len(valori) else ""
    return cita, (livello[0] if livello else None), [a or b for a, b in re.findall(r"«([^»]+)»|\"([^\"]+)\"", cella_sezione)]


def _trova(percorso, radice, cita):
    return next((c for c in (percorso.parent / cita, radice / cita if radice else None) if c and c.exists()), None)


def _controlla_input(percorso, radice, righe, titoli_trovati, errori):
    tabella = _tabella_input(righe, titoli_trovati)
    if not tabella:
        if any(t.lower() == "input" and livello == 2 for _, livello, t in titoli_trovati):
            errori.append(problema("input_senza_tabella", None, "La sezione Input non contiene una tabella"))
        return
    colonna = _colonne(celle(tabella[0][1]))
    if colonna["file"] is None:
        errori.append(problema("input_colonne", tabella[0][0], "La tabella Input non ha la colonna «File»"))
        return
    numero_fase = FASE.match(percorso.parent.name) if percorso.name == "CONTEXT.md" else None
    cache = {}
    for n, riga in tabella[1:]:
        valori = celle(riga)
        if re.fullmatch(r"[\s:|-]+", riga):
            continue
        voce = _voce(valori, colonna)
        if voce is None:
            continue
        cita, livello, richieste = voce
        if numero_fase:
            for parte in cita.split("/"):
                altra = FASE.match(parte)
                if altra and int(altra[1]) > int(numero_fase[1]):
                    errori.append(problema("riferimento_in_avanti", n, f"Input cita la fase «{parte}», successiva a questa"))
        if "{" in cita:
            continue
        trovato = _trova(percorso, radice, cita)
        if trovato is None:
            if livello is None or livello == "3":
                errori.append(problema("input_file_mancante", n, f"Input: «{cita}» non trovato"))
            continue
        if richieste and trovato.is_file():
            presenti = _intestazioni(trovato, cache)
            for titolo in richieste:
                t = titolo.strip().lower()
                if not any(h == t or h.startswith(t + " (") for h in presenti):
                    errori.append(problema("input_sezione_mancante", n, f"Input: «{cita}» non ha la sezione «{titolo}»"))


def testo_sezione(testo, titolo):
    """Testo di una sezione (titolo e sottosezioni incluse) fino al titolo successivo di pari o maggior livello; None se manca."""
    trovati = titoli(analizza(testo))
    cercato = titolo.strip().lower()
    for i, (n, livello, nome) in enumerate(trovati):
        if nome.lower() == cercato or nome.lower().startswith(cercato + " ("):
            fine = next((m for m, altro, _ in trovati[i + 1:] if altro <= livello), None)
            righe = testo.splitlines()
            return "\n".join(righe[n - 1:(fine - 1) if fine else len(righe)])
    return None


def peso(percorso, radice=None):
    """Contesto che il contratto fa caricare: {file, righe:[{file, livello, sezione, token}], livello3, livello4}.

    Token = caratteri/4, solo per i file che esistono; con sezioni «…» si contano solo quelle. I percorsi con {segnaposto}
    (nati a runtime) non sono contati. Serve a tenere i riferimenti sotto il tetto di ICM (500–2.000 token per fase)."""
    percorso, radice = Path(percorso), (Path(radice) if radice else None)
    righe = analizza(percorso.read_text(encoding="utf-8"))
    risultato = {"file": str(percorso), "righe": [], "livello3": 0, "livello4": 0}
    tabella = _tabella_input(righe, titoli(righe))
    colonna = _colonne(celle(tabella[0][1])) if tabella else None
    if not colonna or colonna["file"] is None:
        return risultato
    for _, riga in tabella[1:]:
        voce = None if re.fullmatch(r"[\s:|-]+", riga) else _voce(celle(riga), colonna)
        if voce is None or "{" in voce[0]:
            continue
        cita, livello, richieste = voce
        trovato = _trova(percorso, radice, cita)
        token = None
        if trovato is not None and trovato.is_file():
            contenuto = trovato.read_text(encoding="utf-8", errors="replace")
            token = (sum(len(testo_sezione(contenuto, s) or "") for s in richieste) if richieste else len(contenuto)) // 4
            risultato["livello4" if livello == "4" else "livello3"] += token
        risultato["righe"].append({"file": cita, "livello": int(livello) if livello else 3, "sezione": richieste or None, "token": token})
    return risultato


def valida(percorso, radice=None, max_righe=MAX_RIGHE):
    """Controlla un contratto: {file, errori, avvisi}, ogni problema {codice, riga, messaggio}."""
    percorso = Path(percorso)
    radice = Path(radice) if radice else None
    nome = str(percorso)
    if radice:
        try:
            nome = percorso.resolve().relative_to(radice.resolve()).as_posix()
        except ValueError:
            pass
    errori, avvisi = [], []
    try:
        testo = percorso.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as errore:
        return {"file": nome, "errori": [problema("file_illeggibile", None, f"Impossibile leggere il file: {errore}")], "avvisi": []}
    righe = analizza(testo)
    trovati = titoli(righe)
    for n, riga, fuori in righe:
        if fuori and SEGNAPOSTO.search(CODICE_IN_RIGA.sub("", riga)):
            errori.append(problema("segnaposto", n, f"Segnaposto non compilato: {SEGNAPOSTO.search(riga)[0]}"))
    visti = [(t.lower(), n) for n, livello, t in trovati if livello == 2 and t.lower() in SEZIONI]
    for nome_sezione in OBBLIGATORIE:
        if not any(s == nome_sezione for s, _ in visti):
            errori.append(problema("sezione_mancante", None, f"Manca la sezione «## {nome_sezione.capitalize()}»"))
    indici = [SEZIONI.index(s) for s, _ in visti]
    if indici != sorted(indici):
        errori.append(problema("sezioni_fuori_ordine", visti[0][1], "Ordine atteso: Input, Processo, Checkpoint, Verifica, Output"))
    _controlla_input(percorso, radice, righe, trovati, errori)
    if len(testo.splitlines()) > max_righe:
        avvisi.append(problema("troppo_lungo", None, f"{len(testo.splitlines())} righe (consigliate al più {max_righe}): "
                                                    "le regole stabili vanno in un file di riferimento"))
    return {"file": nome, "errori": sorted(errori, key=lambda p: p["riga"] or 0), "avvisi": avvisi}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="+", help="contratti da controllare")
    ap.add_argument("--radice", help="radice da cui risolvere i percorsi degli Input (di norma il vault)")
    ap.add_argument("--max-righe", type=int, default=MAX_RIGHE, help=f"oltre questa lunghezza: avviso (predefinito {MAX_RIGHE})")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--peso", action="store_true", help="mostra anche quanto contesto caricano gli Input (caratteri/4)")
    args = ap.parse_args(argv)
    esiti = [valida(f, args.radice, args.max_righe) for f in args.file]
    if args.peso:
        for esito, file in zip(esiti, args.file):
            if not esito["errori"] or all(e["codice"] != "file_illeggibile" for e in esito["errori"]):
                esito["peso"] = peso(file, args.radice)
    if args.json:
        print(json.dumps(esiti, ensure_ascii=False, indent=2))
    else:
        for esito in esiti:
            for genere, elenco in (("errore", esito["errori"]), ("avviso", esito["avvisi"])):
                for p in elenco:
                    dove = f":{p['riga']}" if p["riga"] else ""
                    print(f"{esito['file']}{dove}: {genere} {p['codice']}: {p['messaggio']}")
            print(f"{esito['file']}: " + (f"{len(esito['errori'])} errori" if esito["errori"] else "ok"))
            for voce in esito.get("peso", {}).get("righe", []):
                dove = ", ".join(f"«{s}»" for s in voce["sezione"]) if voce["sezione"] else "tutto"
                print(f"  livello {voce['livello']} · {voce['file']} · {dove}: " + (f"~{voce['token']} token" if voce["token"] is not None else "non trovato"))
            if "peso" in esito:
                print(f"  contesto caricato: livello 3 ~{esito['peso']['livello3']} token · livello 4 ~{esito['peso']['livello4']} token")
    return 1 if any(e["errori"] for e in esiti) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

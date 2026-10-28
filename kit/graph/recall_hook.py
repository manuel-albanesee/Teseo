"""Hook UserPromptSubmit: mette nel contesto i fatti del grafo legati al prompt, prima che il modello parta.

Se una pagina di wiki/, index.md o Wiki reference.md è più recente di graph.sqlite, ricostruisce prima il grafo.
Nei vault con manifest compatibile usa invece snapshot/digest e generazioni immutabili con lock comune.
Tutto lavora sul solo testo scritto dall'utente (recall.scritto): i blocchi <pasted_content> incollati non danno
punti di partenza, non cercano nella memoria, non restano in sospeso e non fanno uscire domande aperte.
Fatti: tutte le relazioni tipizzate e al più 10 link generici (limiti per tipo in recall.py); se qualcosa resta fuori,
l'ultima riga dei fatti lo dice («N link generici omessi»).
Alle pagine nominate nel prompt aggiunge quelle lette in passato per domande simili (memoria.py).
Se né il grafo né la memoria danno punti di partenza, ripiego sul testo delle pagine (recall.per_testo_a_cascata, FTS5):
fino a 3 pagine che contengono le parole o le date del prompt, e se non ce ne sono un secondo giro più largo con al più
2 pagine; solo se è una domanda sul contenuto (memoria.e_domanda:
non per comandi, conferme, richieste di modifica o domande sul sistema), aggiunte come punti di partenza e dichiarate nel
contesto «trovate nel testo, non per nome» (aggancio debole: il modello le verifica), nel systemMessage con
«N pagine dal testo». La condizione sta in ripiego_testo, usata anche da misura.py. Non vale con la memoria: le pagine lette in passato per domande simili sono un segnale più
forte di una ricerca per parole, e non si mescolano. Il routing non cambia (modello_hook usa solo i semi per nome):
con soli semi dal testo risponde Opus.
Prompt che il grafo non riconosce → se è una domanda sul contenuto (non un comando, una richiesta di modifica,
una domanda sul sistema o una conferma: memoria.e_domanda) resta in sospeso in memoria.sqlite, in attesa delle pagine lette (learn_hook.py);
senza nemmeno pagine dalla memoria, la riga "nessuna pagina riconosciuta" per l'utente e, per il modello,
AVVISO_NESSUNA_PAGINA (cercare in wiki/, non rispondere dalla conoscenza generale): non tutti i vault hanno un CLAUDE.md
che lo dica. Non è un guasto, quindi non porta MARCA_GUASTO; modello_hook.py manda comunque a Opus.
Se la ricostruzione fallisce (per esempio frontmatter YAML non valido in una pagina) e graph.sqlite esiste, usa il
grafo precedente e lo dichiara: nel systemMessage e in testa all'additionalContext (AVVISO_GRAFO_VECCHIO). Un errore
nelle domande aperte ne fa perdere solo le domande (nota nel systemMessage). Qualsiasi altro errore, o graph.sqlite
assente e non ricostruibile, stampa comunque un JSON con systemMessage e AVVISO_SENZA_GRAFO per il modello: lo stdout
è sempre e solo quel JSON. Le righe di guasto iniziano con MARCA_GUASTO, che modello_hook.py usa per non dare mai
a Haiku un prompt senza recall affidabile.
Con GRAFO_SENZA_MEMORIA=1 (lo imposta misura.py) la memoria non si legge né si scrive.
Log dei turni (tabella `turni` di memoria.sqlite, memoria.py --turni): a OGNI prompt, anche senza semi, una riga con il
testo scritto, i semi con l'origine (nome, titolo, memoria, testo), le pagine iniettate nei fatti e il routing (NULL: lo
decide modello_hook dopo); learn_hook.py le collega le pagine che il modello poi legge. L'origine nome/titolo si ricava
da punti_di_partenza (presi per nome + per_titolo) senza toccare recall.py. Un errore nel log non fa fallire il recall:
si perde solo la riga, e lo stdout resta il solo JSON.
In coda ai fatti, al più 3 domande aperte del vault sulle stesse pagine (domande.py), mai due volte
la stessa nella sessione; con GRAFO_SENZA_DOMANDE=1 (lo imposta misura.py) nessuna domanda.

Lo chiama modello_hook.py, registrato in .claude/settings.json, che con Opus può far rispondere Haiku;
si prova a mano con:
  echo '{"prompt": "il file delle fatture non arriva, a chi scrivo?"}' | python .graph/recall_hook.py
"""
import contextlib
import io
import json
import os
import sqlite3
from graph_db import connect_graph, resolve_graph, graph_reference
import sys
import time
from pathlib import Path

from build_graph import costruisci
import domande
from build_graph import norm
from memoria import apri, e_domanda, registra_turno, ricorda, sospendi
from recall import formatta, nodi, per_testo_a_cascata, per_titolo, punti_di_partenza, richiama, scritto

AVVISO = "Fatti calcolati da frontmatter e wikilink: verificarli sulle pagine di wiki/ prima di citarli."
MAX_ERRORE = 200  # caratteri di un errore nei messaggi
# Le righe per il modello nei casi di guasto iniziano con MARCA_GUASTO: modello_hook.instradamento le riconosce
# e in quei casi risponde sempre Opus, mai Haiku.
MARCA_GUASTO = "ATTENZIONE (recall del grafo):"
AVVISO_SENZA_GRAFO = (f"{MARCA_GUASTO} il contesto dal grafo non è disponibile per questo prompt. Prima di rispondere "
                      "cerca le pagine in wiki/ con Grep e Glob e leggile con Read; se la risposta non è nelle "
                      "pagine, dillo all'utente.")
# Nessun seme: non è un guasto (niente MARCA_GUASTO). modello_hook.instradamento lo riconosce per uguaglianza.
AVVISO_NESSUNA_PAGINA = ("Il grafo della wiki non ha riconosciuto pagine nel prompt. Se la domanda riguarda il vault, "
                         "cerca in wiki/ (Grep sul corpo, Glob sui nomi, index.md per le descrizioni) e leggi le "
                         "pagine con Read prima di rispondere; se la risposta non è nelle pagine, dillo all'utente "
                         "invece di rispondere dalla conoscenza generale. Se il prompt non riguarda il vault "
                         "(comandi, sistema, conversazione) ignora questo avviso.")
AVVISO_DAL_TESTO = ("Pagine trovate nel testo delle pagine, non per nome (aggancio debole, la domanda potrebbe non "
                    "riguardarle: leggile e verifica prima di citarle):")
AVVISO_GRAFO_VECCHIO = (f"{MARCA_GUASTO} il grafo NON è stato ricostruito ({{errore}}): questi fatti vengono dalla "
                        "versione precedente e possono non rispecchiare le ultime modifiche alle pagine. "
                        "Verificali sulle pagine di wiki/ e dì all'utente che il grafo è da correggere.")


def ripiego_testo(db, testo, dal_grafo, ricordate=()):
    """Le pagine del ripiego sul testo, o [] se non scatta. Una sola condizione per l'hook e per misura.py: ripiego solo
    senza grafo e senza memoria, e solo per le domande sul contenuto (comandi, conferme e domande sul sistema darebbero
    pagine fuori tema; le date esplicite passano e_domanda, non sono comandi). Grafo e memoria li calcola il chiamante:
    misura.py non ha la memoria e passa `ricordate` vuoto. Il ripiego è a due giri (recall.per_testo_a_cascata)."""
    return per_testo_a_cascata(db, testo) if not dal_grafo and not ricordate and e_domanda(testo) else []


def origine_semi(db, testo, dal_grafo, ricordate, dal_testo, semi):
    """[(pagina, origine)] dei semi: nome o titolo (punti_di_partenza = presi per nome + per_titolo(presi)), memoria, testo.
    I presi per nome non si conoscono da fuori: sono i primi k di dal_grafo con per_titolo(dal_grafo[:k]) == dal_grafo[k:].
    Una pagina a più parole nominata per intero tornerebbe anche da per_titolo, quindi k parte da quante pagine hanno il
    proprio nome o un alias nel testo (stessa ricerca di punti_di_partenza, senza la precedenza del più lungo) e si
    prende il primo k coerente: «Portale clienti nuovo» resta nome, «caricamento fallito» → titolo."""
    q = f" {norm(testo)} "
    alias = {}
    # le varianti grafiche (ServiceDesk → «service desk», build_graph.varianti_nomi) sono nomi a tutti gli effetti
    for id_, a in db.execute("SELECT entity_id, alias FROM aliases UNION SELECT entity_id, variante FROM varianti"):
        alias.setdefault(id_, []).append(a)
    k = max((i + 1 for i, p in enumerate(dal_grafo) if any(f" {norm(n)} " in q for n in [p, *alias.get(p, [])])),
            default=0)
    while k < len(dal_grafo) and per_titolo(db, testo, dal_grafo[:k]) != dal_grafo[k:]:
        k += 1
    origine = {p: "nome" for p in dal_grafo[:k]}
    origine.update({p: "titolo" for p in dal_grafo[k:]})
    origine.update({p: "memoria" for p, _ in ricordate})
    origine.update({p: "testo" for p in dal_testo})
    return [(s[0], origine.get(s[0], "memoria")) for s in semi]


def aggiorna(vault, db):
    if (vault / ".teseo/project.json").exists() or (vault / ".teseo/local/graph-current.json").exists():
        from dashboard.graph_service import rebuild
        previous = graph_reference(db).generation
        return rebuild(vault).generation != previous
    sorgenti = [vault / "wiki", vault / "index.md", vault / "Wiki reference.md", *(vault / "wiki").glob("*.md")]
    ultima = max(p.stat().st_mtime for p in sorgenti if p.exists())
    if db.exists() and db.stat().st_mtime >= ultima:
        return False
    with contextlib.redirect_stdout(io.StringIO()):  # lo stdout dell'hook è riservato al JSON
        costruisci(vault, db)
    return True


def breve(e):
    """Errore su una riga, al più MAX_ERRORE caratteri."""
    t = " ".join(str(e).split()) or type(e).__name__
    return t if len(t) <= MAX_ERRORE else t[:MAX_ERRORE] + "…"


def recall():
    qui = Path(__file__).resolve().parent
    db_path = qui / "graph.sqlite"
    evento = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    prompt = evento.get("prompt", "")
    testo = scritto(prompt)  # semi, memoria e domande aperte lavorano su ciò che l'utente ha scritto, non sul testo incollato

    inizio = time.perf_counter()
    ricostruito, errore_build = False, None
    try:
        ricostruito = aggiorna(qui.parent, db_path)
    except (Exception, SystemExit) as e:  # SystemExit: build_graph esce con sys.exit su alcuni errori
        if not resolve_graph(db_path).exists():
            raise RuntimeError(f"grafo non ricostruito ({breve(e)}) e graph.sqlite assente") from e
        errore_build = breve(e)  # si va avanti col grafo precedente, dichiarandolo
    db = connect_graph(db_path)
    mem = None if os.environ.get("GRAFO_SENZA_MEMORIA") == "1" else apri(qui / "memoria.sqlite")
    errore_domande = None
    turno = ([], [])  # (semi con origine, pagine iniettate) per il log; vuoti se il recall fallisce prima
    try:
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute("SELECT id, tipo, descrizione FROM entities")}
        dal_grafo = punti_di_partenza(db, testo)
        ricordate = [(p, d) for p, d in ricorda(mem, testo, info) if p not in dal_grafo] if mem else []
        dal_testo = ripiego_testo(db, testo, dal_grafo, ricordate)
        semi, fatti, omessi = richiama(db, testo, extra=[p for p, _ in ricordate] + dal_testo)
        if mem:
            try:  # il log dei turni è un di più: mai un errore dell'hook
                turno = (origine_semi(db, testo, dal_grafo, ricordate, dal_testo, semi),
                         list(dict.fromkeys([s[0] for s in semi] + [n for f in fatti for n in nodi(f)])))
            except Exception:
                turno = ([], [])
        in_sospeso = bool(mem) and not dal_grafo and sospendi(mem, evento.get("session_id", ""), testo)
        poste = []
        # domande aperte solo sulle pagine agganciate per nome o dalla memoria: un aggancio dal testo è debole,
        # e una domanda posta fuori tema si consuma per tutta la sessione
        forti = [s[0] for s in semi if s[0] not in dal_testo]
        if forti and os.environ.get("GRAFO_SENZA_DOMANDE") != "1":
            try:  # le domande aperte sono un di più: se falliscono si perdono solo loro
                archivio = domande.apri(qui / "domande.sqlite")
                try:
                    poste = domande.per_pagine(db, qui.parent, forti, evento.get("session_id", ""), archivio)
                finally:
                    archivio.close()
            except Exception as e:
                errore_domande = breve(e)
    finally:
        db.close()
        if mem:
            try:  # a ogni prompt, anche senza semi o con il recall fallito
                registra_turno(mem, evento.get("session_id", ""), testo, *turno)
            except Exception:
                pass
            mem.close()
    ms = round((time.perf_counter() - inizio) * 1000)

    nota = " (grafo ricostruito)" if ricostruito else ""
    if db.graph_generation:
        nota += f" · generazione {db.graph_generation[:12]}"
    nota += f" · {len(dal_testo)} pagine dal testo" if dal_testo else ""
    nota += f" · {len(ricordate)} pagine dalla memoria" if ricordate else ""
    nota += " · domanda in attesa delle pagine lette" if in_sospeso else ""
    if errore_build:
        nota += f" · grafo NON ricostruito: {errore_build}, uso la versione precedente"
    if errore_domande:
        nota += f" · domande aperte non disponibili: {errore_domande}"
    # il grafo vecchio può non rispecchiare le ultime modifiche: il modello lo deve sapere, anche senza fatti
    avvisi = [AVVISO_GRAFO_VECCHIO.format(errore=errore_build)] if errore_build else []
    if db.content_revision:
        avvisi.append(f"Revisione del grafo: {db.content_revision}; generazione: {db.graph_generation}.")
    if not semi:
        uscita = {"systemMessage": f"grafo: nessuna pagina riconosciuta · {ms} ms{nota}"}
        uscita["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit",
                                        "additionalContext": "\n".join([*avvisi, AVVISO_NESSUNA_PAGINA])}
        return uscita
    pagine = ", ".join(s[0] for s in semi)
    contesto = formatta(semi, fatti, info, omessi)
    if ricordate:
        contesto += "\nPagine lette in passato per domande simili:\n" + "\n".join(
            f"- {p}  (per «{d}»)" for p, d in ricordate)
    if dal_testo:
        contesto += f"\n{AVVISO_DAL_TESTO}\n" + "\n".join(f"- {p}" for p in dal_testo)
    if poste:
        contesto += "\n" + domande.formatta(poste)
        nota += f" · {len(poste)} domande aperte"
    return {
        "systemMessage": f"grafo: {len(fatti)} fatti da {pagine} · {ms} ms{nota}",
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join([*avvisi, contesto, AVVISO]),
        },
    }


def main():
    try:
        uscita = recall()
    except (Exception, SystemExit) as e:  # l'hook non deve mai finire in traceback: stdout è solo questo JSON
        uscita = {
            "systemMessage": f"recall del grafo non riuscito: {breve(e)}",
            "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": AVVISO_SENZA_GRAFO},
        }
    print(json.dumps(uscita))


if __name__ == "__main__":
    main()

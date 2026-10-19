"""Misura il grafo su domande reali fatte al vault: il recall porta le pagine giuste, e con quanto contesto?

Senza opzioni misura solo recall.py: deterministico, in meno di un secondo, da rilanciare dopo ogni modifica.
Con --modello lancia `claude -p` due volte per domanda nel vault, a parità di modello e senza thinking:
  ricerca  il modello cerca da sé con Read/Grep/Glob (Bash e skill disattivati, quindi niente recall.py)
  grafo    stesse regole, più l'hook recall_hook.py che inietta i fatti prima del turno
Con --hook, in più, ogni domanda passa dal percorso di modello_hook.py: contesto come recall_hook.py, pagine
pre-caricate, REGOLE_HAIKU, stessi argomenti e stesso input di chiedi_a_haiku, con il modello di --modello
(sola condizione «hook»). Con --hook-da <cartella> si usano invece REGOLE_HAIKU di quella copia di modello_hook.py
(es. un backup di .graph_backup) e niente pagine pre-caricate: la versione precedente, per il confronto.
Sempre, dopo la tabella del recall, i casi negativi (NEGATIVI): per ognuno i semi che non devono comparire
(testo incollato, parole comuni che sono nomi di pagina, titoli con parole sparse); exit 1 se ce n'è qualcuno
o se manca un seme atteso: un seme spurio inietta fatti e domande aperte fuori tema.
Poi il ripiego sul testo delle pagine (TESTO), misurato come lo usa recall_hook.py (recall_hook.ripiego_testo: niente
semi dal grafo, memoria.e_domanda, poi recall.per_testo; la memoria qui non c'è): prompt che il grafo non riconosce per
nome ma le cui parole, identificatori o date sono nel corpo delle pagine, con le pagine attese tra quelle trovate; e
prompt di conversazione, di lavoro, sul sistema o generici che devono dare 0 pagine. Controlla anche che le DOMANDE abbiano semi per nome (il ripiego non scatta); exit 1 se un caso fallisce.
Infine la memoria (MEMORIA, memoria.sospendi su un db in memoria): le domande sul contenuto restano in sospeso, i
comandi, le richieste di modifica e la conversazione no; exit 1 se un caso è sbagliato.
Alla fine ATTESI_FALLITI: difetti noti del recall (morfologia derivativa, sinonimi, varianti grafiche, parola rara
isolata) trasformati in casi che oggi falliscono. Si stampano «atteso KO» e non fanno uscire con 1; quando un caso
comincia a passare compare «ORA OK» (va spostato nella lista normale: DOMANDE, TESTO o NEGATIVI), così chi migliora
il recall vede il miglioramento senza rompere la CI. L'exit resta 0 finché i casi normali passano.
Poi il banco (BANCO, .graph/banco.json: le domande le scrive chi lo usa, banco.py --semi dà il materiale e
banco.py --verifica lo controlla): domande con le pagine che il vault deve portare, scritte senza le parole dei titoli.
Si misurano con lo stesso calcolo di misura_recall; senza semi per nome, con il ripiego sul testo, segnalato «T».
Una riga per domanda e il riepilogo: pagine attese portate, domande complete, token medi, domande senza semi.
È informativo: non fa uscire con 1. Senza banco.json la sezione non si stampa.
--banco-salva FILE scrive i risultati per domanda; --banco-confronta FILE li confronta con quel salvataggio: per
domanda MIGLIORATA o PEGGIORATA (pagine attese, e rumore, cioè pagine portate ma non attese), con la variazione dei
token, poi il saldo; --solo-banco stampa solo il banco.
Con --routing non si chiama nessun modello: per ogni domanda di DOMANDE (destinazione in ATTESE) e di ROUTING
si confronta la destinazione attesa con quella di modello_hook.instradamento, con una sessione Opus simulata.
La correttezza automatica è solo un'approssimazione (regex sulla risposta): le risposte, salvate in --out, vanno rilette.

Uso:
  python .graph/misura.py
  python .graph/misura.py --modello claude-haiku-4-5-20251001 --out <cartella> --giri 3
  python .graph/misura.py --hook --modello haiku --out <cartella> --domande 2,5 [--hook-da .graph_backup/<data>]
  python .graph/misura.py --solo-banco --banco-salva <file>
  python .graph/misura.py --solo-banco --banco-confronta <file>
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import memoria
import modello_hook
from recall import formatta, nodi, punti_di_partenza, richiama
from recall_hook import AVVISO, AVVISO_NESSUNA_PAGINA, ripiego_testo

# (domanda come è stata fatta, pagine che il recall deve portare, regex che una risposta corretta contiene)
# Valgono per il vault d'esempio del kit: si sostituiscono con domande reali del proprio vault (10 o più, almeno 3-4 a catena)
DOMANDE = [
    ("il file delle fatture non arriva, a chi scrivo?",
     ["Modulo fatture", "Anna Rossi"], [r"Rossi"]),
    # Catena a 3 passi: la pagina di partenza non nomina il referente
    ("devo fare un rilascio in produzione: cosa mi serve e chi me lo dà?",
     ["Rilascio in produzione", "Console di rilascio", "Incident settimanale", "Anna Rossi"],
     [r"incident", r"Rossi"]),
    ("quale acronimo metto nel ticket?",
     ["Acronimo del progetto"], [r"ACME0"]),
    ("dove apro l'incident settimanale?",
     ["Incident settimanale", "ServiceDesk"], [r"ServiceDesk|Service Desk"]),
    # Domanda «ampia»: la risposta sta nella pagina del sistema e nelle sue parti
    ("cosa fa il Gestionale e come è fatto?",
     ["Gestionale", "Modulo fatture", "Console di rilascio"], [r"fatture", r"rilascio"]),
]

# Destinazione attesa (haiku/opus) delle DOMANDE, per numero da 1: le domande ampie vanno a Opus, tutte le altre
# chiedono un fatto, un referente o una procedura precisa e restano a Haiku (anche quelle a più passi)
ATTESE = {i: "haiku" for i in range(1, len(DOMANDE) + 1)}
ATTESE.update({5: "opus"})

# Casi aggiuntivi per il routing: (domanda, destinazione attesa[, contesto]); senza contesto se ne simula uno. Veri positivi e trappole lessicali.
ROUTING = [
    ("chi è il referente del Modulo fatture?", "haiku"),
    ("quando si fa il rilascio in produzione?", "haiku"),
    ("perché il file delle fatture non arriva?", "haiku"),
    ("come funziona la Console di rilascio?", "opus"),
    ("spiegami il rilascio in produzione", "opus"),
    ("differenza tra Gestionale e Modulo fatture", "opus"),
    ("cosa fa Anna Rossi?", "opus"),
    ("riassumi la call di ieri", "opus"),  # nessuna pagina riconosciuta
    # Un nome nudo resta puntuale se la pagina non è un hub: Gestionale ha 2 pagine parte_di, meno di SOGLIA_HUB
    ("Gestionale?", "haiku"),
    # Domande di elenco (plurale: elenca, lista, tutti i, quali, quanti, ci sono, dammi i): Haiku perde pezzi, va a Opus
    ("elenca le parti del Gestionale", "opus"),
    ("quali sono i passi del rilascio in produzione?", "opus"),
    ("quanti moduli ci sono nel Gestionale?", "opus"),
    ("dammi i referenti del Gestionale", "opus"),
    # Caso limite: «quali» è plurale ma qui forse basta un fatto; nel dubbio Opus
    ("quali permessi servono per la Console di rilascio?", "opus"),
    # Singolare e «tutto» non sono elenchi: restano a Haiku
    ("è tutto a posto con il Modulo fatture?", "haiku"),
    # Il testo incollato non conta: «come funziona» compare solo lì
    ("il file delle fatture non arriva, a chi scrivo? <pasted_content>come funziona il Gestionale</pasted_content>", "haiku"),
    # Ma la domanda ampia scritta fuori dal blocco incollato va a Opus
    ("cosa fa il Modulo fatture? <pasted_content>chi è il referente</pasted_content>", "opus"),
    # Testo incollato con nomi di pagina e domanda scritta senza pagine: nessun seme, risponde Opus
    ("valuta questa risposta <pasted_content>il file delle fatture non arriva, chi è Anna Rossi?</pasted_content>", "opus"),
    # Scrittura e prefisso: restano di Opus
    ("aggiorna la pagina del Modulo fatture", "opus"),
    ("@opus chi è Anna Rossi?", "opus"),
    # Nessuna pagina riconosciuta: il contesto è il solo avviso, e deve restare a Opus (anche la memoria lo richiede)
    ("ciao come va", "opus", AVVISO_NESSUNA_PAGINA),
    ("chi è il referente del Modulo fatture?", "opus", AVVISO_NESSUNA_PAGINA),
]

# Testo incollato che nomina pagine senza che la domanda le riguardi
INCOLLATO_REALE = ("Il file delle fatture non arriva: Anna Rossi apre l'incident settimanale sulla console, "
                   "poi il Gestionale riparte.")

# (prompt, pagine che NON devono essere semi[, pagine che devono esserlo]); i semi sono quelli di recall_hook
NEGATIVI = [
    (f'valuta questa risposta <pasted_content id="x">{INCOLLATO_REALE}</pasted_content id="x">',
     ["Modulo fatture", "Anna Rossi", "Incident settimanale", "Console di rilascio", "Gestionale"]),
    # Il testo incollato nomina pagine, ma la domanda scritta no
    ("<pasted_content>il file delle fatture non arriva: scrivere ad Anna Rossi</pasted_content> puoi riassumere?",
     ["Modulo fatture", "Anna Rossi"]),
    # Il testo incollato non toglie i semi della domanda scritta
    ("il file delle fatture non arriva? <pasted_content>Gestionale, console</pasted_content>",
     ["Gestionale", "Console di rilascio"], ["Modulo fatture"]),
    # Il rapporto di un sub agent arriva all'hook come prompt: non è una domanda dell'utente
    ('Another Claude session sent a message:\n<agent-message from="a1">\nModificato recall.py; il file delle fatture '
     'non arriva più.\n</agent-message>\n\nThat "other Claude session" is an agent.', ["Modulo fatture"]),
    # Parole di un titolo lontane fra loro in una frase normale
    ("Il rilascio della nuova grafica è piaciuto a tutti, mentre la stampante dell'ufficio ha fermato la produzione "
     "dei volantini", ["Rilascio in produzione"]),
    # Varianti grafiche di un nome (tabella varianti di build_graph.py): con lo spazio, in minuscolo
    ("Service Desk", [], ["ServiceDesk"]),
    ("service desk", [], ["ServiceDesk"]),
    # Morfologia derivativa (stemmer.py): rilasciare/rilascio
    ("rilasciare in produzione", [], ["Rilascio in produzione"]),
]

# (prompt, pagine attese fra quelle del ripiego sul testo); senza pagine attese il ripiego deve dare 0 pagine.
# Tutti senza semi per nome: sono i casi in cui il grafo da solo non riconosce nulla.
TESTO = [
    ("dove trovo ACME0?", ["Acronimo del progetto"]),  # identificatore presente solo nel corpo
    ("riassumi la call del 10 settembre", ["Rilascio in produzione"]),
    ("cosa è successo il 10/09?", ["Rilascio in produzione"]),  # data numerica, senza anno
    ("dimmi della call-2026-09-10", ["Rilascio in produzione"]),  # chiave fonte scritta per esteso
    ("cosa è successo il 25 dicembre?", []),  # nessuna fonte con quel giorno
    ("ciao come va", []),
    ("grazie mille", []),
    ("fammi un commit", []),
    ("scrivi una funzione python che ordina una lista", []),
    ("che ore sono?", []),
    ("il collega mi ha chiesto il report settimanale", []),
    ("come organizzo la riunione di lunedì con il team?", []),
    # lavoro e domande sul sistema o generiche, che non devono agganciare pagine
    ("si implementalo con lo stesso schema e dimmi anche se ha senso rivedere le query di ricerca sul grafo", []),
    ("come gestisco un errore di timeout sul server?", []),
    ("ok procedi", []),
    ("come funziona il recall del grafo?", []),
    ("mi serve una mano a scrivere una mail al fornitore", []),
    ("come imposto un cron su linux?", []),
    ("puoi spiegarmi come funziona git rebase?", []),
]

# Difetti noti del recall: casi che OGGI FALLISCONO. (sezione, prompt, argomenti..., motivo)
#   "domanda"   prompt, pagine che il recall (richiama: semi e nodi dei fatti) deve portare, come DOMANDE
#   "testo"     prompt, pagine attese dal ripiego sul testo (senza semi per nome), come TESTO
#   "semi"      prompt, semi vietati, semi attesi, come NEGATIVI (qui serve per le varianti grafiche di un nome)
# misura_attesi_falliti stampa «atteso KO» finché falliscono e «ORA OK» quando passano: allora si spostano nella lista
# normale. Non fanno mai uscire con 1.
ATTESI_FALLITI = [
    # abbreviazioni e sinonimi: nel vault si dice «rilascio in produzione», non «prod» né «deploy»
    ("domanda", "rilasciare in prod", ["Rilascio in produzione"], "prod/produzione (abbreviazione)"),
    ("domanda", "deploy in produzione", ["Rilascio in produzione"], "deploy = rilascio (anglicismo)"),
]

# Casi futuri, NON misurabili oggi: richiedono il contesto della sessione (il recall vede un prompt alla volta).
# Anafora: «e chi lo approva?», «e dove si trova?» dopo una domanda su una pagina: i semi sono quelli del turno prima.
#   Da misurare con una sequenza di turni (tabella turni di memoria.sqlite, memoria.py --turni) quando il recall userà la sessione.
# Deissi temporale: «ieri», «la settimana scorsa», «a fine agosto»: servono la data del turno e le fonti `call-AAAA-MM-GG*`
#   (pagine_per_data le sa mappare solo se la data è scritta per esteso: «31 agosto»).

ISTRUZIONE = "Rispondi alla domanda usando le note del vault Obsidian nella cartella corrente. Rispondi in italiano, in breve."


def misura_recall(db):
    info = {id_: (tipo, descr) for id_, tipo, descr in db.execute("SELECT id, tipo, descrizione FROM entities")}
    print(f"{'domanda':<55} {'semi':>4} {'pagine attese':>13} {'token':>6} {'ms':>4}")
    trovate_tot = attese_tot = 0
    for domanda, attese, _ in DOMANDE:
        inizio = time.perf_counter()
        semi, fatti, omessi = richiama(db, domanda)
        ms = (time.perf_counter() - inizio) * 1000
        portate = {s[0] for s in semi} | {n for f in fatti for n in nodi(f)}
        mancanti = [p for p in attese if p not in portate]
        testo = formatta(semi, fatti, info, omessi) if semi else ""
        trovate_tot += len(attese) - len(mancanti)
        attese_tot += len(attese)
        print(f"{domanda[:54]:<55} {len(semi):>4} {len(attese) - len(mancanti):>7}/{len(attese):<5} "
              f"{len(testo) // 4:>6} {ms:>4.0f}" + (f"   mancano: {', '.join(mancanti)}" if mancanti else ""))
    print(f"pagine attese portate dal recall: {trovate_tot}/{attese_tot} · token ≈ caratteri/4")


def misura_negativi(db):
    """Semi spuri dei casi di NEGATIVI (e semi attesi mancanti); restituisce quanti casi hanno un difetto."""
    print()
    print(f"{'caso negativo':<55} {'semi':<40} esito")
    difetti = spuri = 0
    for prompt, vietate, *attese in NEGATIVI:
        semi = punti_di_partenza(db, prompt)
        spurie = [p for p in vietate if p in semi]
        mancanti = [p for p in attese[0] if p not in semi] if attese else []
        spuri += len(spurie)
        difetti += bool(spurie or mancanti)
        esito = "OK" if not (spurie or mancanti) else (f"SPURI: {', '.join(spurie)}" if spurie else "") + (
            f" MANCANO: {', '.join(mancanti)}" if mancanti else "")
        print(f"{prompt.replace(chr(10), ' ')[:54]:<55} {', '.join(semi)[:39]:<40} {esito}")
    print(f"semi spuri: {spuri}/{len(NEGATIVI)} casi" + (f" · {difetti} casi con un difetto" if difetti != spuri else ""))
    return difetti


def misura_testo(db):
    """Il ripiego sul testo: pagine attese trovate, 0 pagine sui prompt di conversazione, e DOMANDE con semi per nome.
    Restituisce quanti casi hanno un difetto."""
    print()
    print(f"{'ripiego sul testo':<55} {'pagine trovate':<50} esito")
    difetti = 0
    for prompt, attese in TESTO:
        semi = punti_di_partenza(db, prompt)
        trovate = ripiego_testo(db, prompt, semi)  # la stessa condizione dell'hook, senza memoria
        mancanti = [p for p in attese if p not in trovate]
        ko = bool(semi or mancanti or (not attese and trovate))
        difetti += ko
        esito = "OK" if not ko else ("HA SEMI PER NOME " if semi else "") + (
            f"MANCANO: {', '.join(mancanti)}" if mancanti else "" if attese else "DOVEVA ESSERE VUOTO")
        print(f"{prompt[:54]:<55} {', '.join(trovate)[:49]:<50} {esito}")
    senza = [d for d, _, _ in DOMANDE if not punti_di_partenza(db, d)]
    difetti += len(senza)
    print(f"ripiego sul testo: {len(TESTO) - difetti + len(senza)}/{len(TESTO)} casi OK · "
          f"domande senza semi per nome (il ripiego scatterebbe): {len(senza)}" + (f" ({'; '.join(senza)})" if senza else ""))
    return difetti


def misura_attesi_falliti(db):
    """Stato di ATTESI_FALLITI: «atteso KO» finché il caso fallisce, «ORA OK» quando passa. Non incide sull'exit."""
    print()
    print(f"{'atteso fallito (non fa uscire con 1)':<55} {'esito':<8} difetto")
    ora_ok = 0
    for sezione, prompt, *resto, motivo in ATTESI_FALLITI:
        if sezione == "domanda":
            semi, fatti, _ = richiama(db, prompt)
            portate = {s[0] for s in semi} | {n for f in fatti for n in nodi(f)}
            ok = all(p in portate for p in resto[0])
        elif sezione == "testo":
            semi = punti_di_partenza(db, prompt)
            trovate = ripiego_testo(db, prompt, semi)
            ok = not semi and all(p in trovate for p in resto[0])
        else:  # "semi"
            semi = punti_di_partenza(db, prompt)
            ok = not any(p in semi for p in resto[0]) and all(p in semi for p in resto[1])
        ora_ok += ok
        print(f"{prompt[:54]:<55} {'ORA OK' if ok else 'atteso KO':<9} {motivo}")
    print(f"attesi falliti: {len(ATTESI_FALLITI) - ora_ok} ancora KO · {ora_ok} ORA OK"
          + (" (spostarli nelle liste normali)" if ora_ok else ""))


def esito_banco(db, info, domanda):
    """Le pagine che il recall porta per una domanda del banco, come misura_recall. Senza semi per nome, il ripiego
    sul testo come recall_hook: le pagine trovate diventano semi (richiama con extra) e l'esito è segnato «T»."""
    inizio = time.perf_counter()
    semi, fatti, omessi = richiama(db, domanda)
    per_nome = len(semi)
    dal_testo = [] if semi else ripiego_testo(db, domanda, [])
    if dal_testo:
        semi, fatti, omessi = richiama(db, domanda, extra=dal_testo)
    ms = (time.perf_counter() - inizio) * 1000
    portate = {s[0] for s in semi} | {n for f in fatti for n in nodi(f)}
    testo = formatta(semi, fatti, info, omessi) if semi else ""
    return {"domanda": domanda, "semi_grafo": per_nome, "semi": [s[0] for s in semi], "testo": bool(dal_testo),
            "portate": sorted(portate), "token": len(testo) // 4, "ms": round(ms)}


def carica_banco(percorso):
    """Le voci di banco.json. None se il file non c'è (la sezione non si stampa) o non è un banco valido."""
    if not percorso.exists():
        return None
    try:
        voci = json.loads(percorso.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"banco non leggibile ({percorso.name}): {e}")
        return None
    valida = isinstance(voci, list) and all(
        isinstance(v, dict) and isinstance(v.get("domanda"), str) and isinstance(v.get("attese", []), list)
        and all(isinstance(p, str) for p in v.get("attese", []))
        for v in voci)
    if not valida:
        print(f"banco non valido ({percorso.name}): serve una lista di oggetti con «domanda» e «attese»")
        return None
    return voci


def misura_banco(db, percorso):
    """Il banco: per domanda le pagine attese che il recall porta, token e tempo, poi il riepilogo. Informativo: non
    incide sull'exit. Restituisce i risultati per domanda (per --banco-salva e --banco-confronta), o None se il banco
    non c'è o non è valido."""
    voci = carica_banco(percorso)
    if voci is None:
        return None
    info = {id_: (tipo, descr) for id_, tipo, descr in db.execute("SELECT id, tipo, descrizione FROM entities")}
    print()
    print(f"banco ({percorso.name}): informativo, non incide sull'exit")
    print(f"{'domanda':<55} {'semi':>4} {'attese':>7} {'rumore':>6} {'token':>6} {'ms':>4} T")
    esiti = []
    for voce in voci:
        attese = voce.get("attese", [])
        esito = esito_banco(db, info, voce["domanda"])
        esito["attese"] = attese
        esito["mancanti"] = [p for p in attese if p not in esito["portate"]]
        esito["rumore"] = len(set(esito["portate"]) - set(attese))
        esiti.append(esito)
        colonna = f"{len(attese) - len(esito['mancanti'])}/{len(attese)}" if attese else "-"
        mancano = f"   mancano: {', '.join(esito['mancanti'])}" if esito["mancanti"] else ""
        print(f"{esito['domanda'][:54]:<55} {esito['semi_grafo']:>4} {colonna:>7} {esito['rumore']:>6} {esito['token']:>6} "
              f"{esito['ms']:>4} {'T' if esito['testo'] else ''}{mancano}")
    attese_tot = sum(len(e["attese"]) for e in esiti)
    portate_tot = sum(len(e["attese"]) - len(e["mancanti"]) for e in esiti)
    complete = sum(1 for e in esiti if not e["mancanti"] and (e["attese"] or not e["portate"]))
    # il ripiego porta pagine giuste insieme a molte fuori tema: il grafo da solo si legge a parte
    dal_grafo = sum(len(e["attese"]) - len(e["mancanti"]) for e in esiti if not e["testo"])
    rumore_medio = sum(e["rumore"] for e in esiti) / len(esiti) if esiti else 0
    senza_semi = sum(1 for e in esiti if not e["semi_grafo"])
    dal_testo = sum(1 for e in esiti if e["testo"])
    token_medio = round(sum(e["token"] for e in esiti) / len(esiti)) if esiti else 0
    pct = 100 * portate_tot / attese_tot if attese_tot else 0
    print(f"banco: pagine attese portate {portate_tot}/{attese_tot} ({pct:.0f}%), dal solo grafo {dal_grafo}"
          f" · domande complete {complete}/{len(esiti)} · rumore medio {rumore_medio:.1f} pagine · token medio {token_medio}"
          f" · domande con 0 semi dal grafo: {senza_semi} (di cui {dal_testo} con il ripiego T)")
    return esiti


def carica_salvataggio(percorso):
    """I risultati di un --banco-salva. None se il file non si legge o non è un salvataggio del banco."""
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    campi = {"domanda", "attese", "mancanti", "portate", "token"}
    return dati if isinstance(dati, list) and all(isinstance(v, dict) and campi.issubset(v) for v in dati) else None


def confronta_banco(esiti, prima):
    """Per domanda rispetto a un salvataggio di --banco-salva. MIGLIORATA: più pagine attese portate, o a parità meno
    rumore (pagine portate ma non attese). PEGGIORATA: meno pagine attese, o a parità più rumore. Poi il saldo."""
    vecchie = {v["domanda"]: v for v in prima}
    conta = {"MIGLIORATA": 0, "PEGGIORATA": 0, "invariata": 0, "NUOVA": 0, "RIMOSSA": 0}
    tot = {"attese": 0, "rumore": 0, "token": 0}
    confrontate = 0
    print()
    print(f"confronto con il salvataggio ({len(prima)} domande)")
    print(f"{'domanda':<55} {'esito':<11} {'attese':>6} {'rumore':>6} {'token':>6}")
    for e in esiti:
        v = vecchie.pop(e["domanda"], None)
        if v is None:
            conta["NUOVA"] += 1
            print(f"{e['domanda'][:54]:<55} NUOVA")
            continue
        confrontate += 1
        d_attese = len(set(e["attese"]) - set(e["mancanti"])) - len(set(v["attese"]) - set(v["mancanti"]))
        d_rumore = len(set(e["portate"]) - set(e["attese"])) - len(set(v["portate"]) - set(v["attese"]))
        d_token = e["token"] - v["token"]
        if d_attese > 0 or (d_attese == 0 and d_rumore < 0):
            esito = "MIGLIORATA"
        elif d_attese < 0 or d_rumore > 0:
            esito = "PEGGIORATA"
        else:
            esito = "invariata"
        conta[esito] += 1
        tot["attese"] += d_attese
        tot["rumore"] += d_rumore
        tot["token"] += d_token
        print(f"{e['domanda'][:54]:<55} {esito:<11} {d_attese:>+6} {d_rumore:>+6} {d_token:>+6}")
    for domanda in vecchie:
        conta["RIMOSSA"] += 1
        print(f"{domanda[:54]:<55} RIMOSSA")
    media = f" (media {tot['token'] / confrontate:+.0f} per domanda)" if confrontate else ""
    print(f"saldo: {conta['MIGLIORATA']} migliorate · {conta['PEGGIORATA']} peggiorate · {conta['invariata']} invariate · "
          f"{conta['NUOVA']} nuove · {conta['RIMOSSA']} rimosse · pagine attese {tot['attese']:+d} · "
          f"rumore {tot['rumore']:+d} · token {tot['token']:+d}{media}")


def salva_banco(esiti, percorso):
    percorso.write_text(json.dumps(esiti, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"banco salvato in {percorso}: {len(esiti)} domande")


def usa_banco(db, args, prima):
    """La sezione del banco con le sue opzioni. Il confronto precede il salvataggio, così può essere lo stesso file."""
    esiti = misura_banco(db, args.banco)
    if esiti is None:
        if args.solo_banco or args.banco_salva or args.banco_confronta:
            print(f"banco non disponibile: {args.banco}", file=sys.stderr)
        return
    if prima is not None:
        confronta_banco(esiti, prima)
    if args.banco_salva:
        salva_banco(esiti, args.banco_salva)


# Prompt e se la memoria deve metterli in sospeso (memoria.sospendi): solo le domande sul contenuto; comandi,
# richieste di modifica e conversazione no, perché le pagine che fanno leggere non sono la risposta alla domanda
MEMORIA = [
    ("come si rilancia un caricamento fallito?", True),
    ("dove trovo i log del job notturno?", True),
    ("chi mi dà il codice per lanciarlo?", True),
    ("perché la mail non parte?", True),
    ("si può rilanciare il job notturno?", True),
    ("sì, aggiungi l'alias Fatture", False),
    ("esegui ingest della cartella raw", False),
    ("ok procedi", False),
    ("grazie", False),
    ("/lint", False),
    ("aggiorna la pagina del Gestionale", False),
    ("lintare il vault", False),
    ("come funziona l'hook di recall?", False),
    # verbo di modifica dentro una domanda sul contenuto: si impara; la richiesta cortese e l'imperativo no
    ("come si aggiorna la configurazione del job notturno?", True),
    ("come si crea un nuovo canale di trasferimento file?", True),
    ("dove si registra un nuovo flusso?", True),
    ("come si cancella un record sbagliato in produzione?", True),
    ("come faccio il fix di un caricamento rotto?", True),
    ("chi devo aggiungere in copia alla mail?", True),
    ("ok, ma dove trovo i log del job notturno?", True),
    ("puoi aggiornare la pagina del Gestionale?", False),
    ("potresti aggiungere l'alias Fatture?", False),
    ("crea una pagina per il job notturno?", False),
    ("aggiorna la pagina con questa info", False),
    ("ok, aggiorna l'indice", False),
    ("che ne dici, aggiungi l'alias?", False),  # «che» apre, ma la seconda frase è un imperativo
    ("quale tabella aggiorna il caricamento?", True),  # il verbo descrive il sistema, non è un comando
    ("sì, salvala", False),
]


def misura_memoria():
    """Quali prompt la memoria mette in sospeso, su un db in memoria (mai memoria.sqlite); restituisce i casi errati."""
    mem = memoria.apri(":memory:")
    print()
    ko = 0
    for prompt, atteso in MEMORIA:
        ottenuto = memoria.sospendi(mem, "prova", prompt)
        ko += ottenuto != atteso
        if ottenuto != atteso:
            print(f"memoria: «{prompt}» sospeso={ottenuto}, atteso {atteso}  KO")
    print(f"memoria, prompt in sospeso: {len(MEMORIA) - ko}/{len(MEMORIA)} casi OK")
    return ko


def esegui(claude, vault, modello, condizione, domanda, hook):
    cmd = [claude, "-p", domanda, "--model", modello, "--output-format", "stream-json", "--verbose",
           "--setting-sources", "user", "--strict-mcp-config", "--no-session-persistence",
           "--disable-slash-commands", "--append-system-prompt", ISTRUZIONE,
           "--allowedTools", "Read", "Grep", "Glob", "--disallowedTools", "Bash", "Skill", "Write", "Edit", "Agent"]
    if condizione == "grafo":
        cmd += ["--settings", json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": hook, "timeout": 10}]}]}})]
    # Senza memoria: la misura confronta il grafo così com'è, e le sue domande non devono finire in memoria.sqlite
    env = {**os.environ, "MAX_THINKING_TOKENS": "0", "GRAFO_SENZA_MEMORIA": "1", "GRAFO_SENZA_DOMANDE": "1"}
    inizio = time.time()
    p = subprocess.run(cmd, cwd=vault, env=env, capture_output=True, timeout=600)
    righe = [json.loads(r) for r in p.stdout.decode("utf-8").splitlines() if r.startswith("{")]
    strumenti = [b["name"] for r in righe if r.get("type") == "assistant"
                 for b in r["message"].get("content", []) if b.get("type") == "tool_use"]
    fine = next((r for r in righe if r.get("type") == "result"), {})
    uso = fine.get("usage", {})
    return {"condizione": condizione, "domanda": domanda, "risposta": fine.get("result", ""),
            "strumenti": strumenti, "secondi": round(time.time() - inizio, 1),
            "costo_usd": fine.get("total_cost_usd"),
            "token_input": sum(uso.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
            "errore": p.stderr.decode("utf-8", "replace")[-2000:] if p.returncode else "", "righe": righe}


def misura_modello(vault, modello, out, paralleli, giri, scelte):
    claude = shutil.which("claude") or sys.exit("claude non è nel PATH")
    hook = f"python {(Path(__file__).resolve().parent / 'recall_hook.py').as_posix()}"
    out.mkdir(parents=True, exist_ok=True)
    lavori = [(c, i, g) for g in range(giri) for i in scelte for c in ("ricerca", "grafo")]
    with ThreadPoolExecutor(paralleli) as ex:
        esiti = list(ex.map(lambda l: esegui(claude, vault, modello, l[0], DOMANDE[l[1]][0], hook), lavori))

    # Per domanda e condizione: corrette su giri, poi medie per giro di strumenti, secondi, token e costo
    somme = {}
    for (condizione, i, g), e in zip(lavori, esiti):
        e["corretta"] = all(re.search(r, e["risposta"], re.I) for r in DOMANDE[i][2])
        (out / f"{i + 1:02d}-{condizione}-{g + 1}.json").write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")
        for chiave in ((condizione, i), (condizione, "totale")):
            t = somme.setdefault(chiave, [0, 0, 0.0, 0, 0.0, 0])
            for k, v in enumerate((e["corretta"], len(e["strumenti"]), e["secondi"], e["token_input"],
                                   e["costo_usd"] or 0, bool(e["errore"]))):
                t[k] += v

    print(f"modello {modello} · {giri} giri per condizione · medie per giro")
    print(f"{'domanda':<45} {'condizione':<8} {'ok':>5} {'strumenti':>9} {'s':>5} {'token in':>9} {'$':>7}")
    for i, domanda in [(i, DOMANDE[i][0]) for i in scelte] + [("totale", "TOTALE")]:
        for condizione in ("ricerca", "grafo"):
            ok, n_str, sec, tok, costo, errori = somme[(condizione, i)]
            n = giri if i != "totale" else giri * len(scelte)
            print(f"{domanda[:44]:<45} {condizione:<8} {f'{ok}/{n}':>5} {n_str / giri:>9.1f} {sec / giri:>5.0f} "
                  f"{tok / giri:>9.0f} {costo / giri:>7.4f}" + (f"  {errori} ERRORI" if errori else ""))
    print(f"→ {out}")


def misura_routing():
    """Tabella del routing senza chiamare modelli; esce con 1 se qualche caso è KO."""
    casi = [(d, ATTESE[i]) for i, (d, _, _) in enumerate(DOMANDE, 1)] + ROUTING
    ko = 0
    print(f"{'domanda':<58} {'atteso':<6} {'ottenuto':<8} {'esito':<5} motivo")
    for domanda, atteso, *contesto in casi:
        ottenuto, motivo = modello_hook.instradamento(domanda, "opus", *contesto or ["contesto simulato"])
        ko += ottenuto != atteso
        print(f"{domanda.replace(chr(10), ' ')[:57]:<58} {atteso:<6} {ottenuto:<8} {'OK' if ottenuto == atteso else 'KO':<5} {motivo}")
    print(f"{len(casi) - ko}/{len(casi)} OK")
    return ko


def carica_regole(cartella):
    """REGOLE_HAIKU di un modello_hook.py in un'altra cartella (un backup), senza eseguirne l'hook."""
    spec = importlib.util.spec_from_file_location("modello_hook_precedente", Path(cartella) / "modello_hook.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.REGOLE_HAIKU


def esegui_hook(claude, vault, db_path, modello, domanda, regole, precarica):
    """Una domanda come la gestisce modello_hook.py: contesto del grafo, pagine pre-caricate, Haiku (o altro modello)."""
    db = sqlite3.connect(db_path)
    try:
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute("SELECT id, tipo, descrizione FROM entities")}
        semi, fatti, omessi = richiama(db, domanda)
    finally:
        db.close()
    contesto = f"{formatta(semi, fatti, info, omessi)}\n{AVVISO}" if semi else ""
    pagine = modello_hook.pagine_precaricate(domanda, vault) if precarica else ""
    cmd = modello_hook.argomenti_haiku(claude, modello, regole)
    cmd[cmd.index("json")] = "stream-json"  # per ricavare le pagine lette
    cmd.append("--verbose")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID")}
    env.update({"GRAFO_HAIKU": "1", "MAX_THINKING_TOKENS": "0"})
    inizio = time.time()
    p = subprocess.run(cmd, input=modello_hook.input_haiku(domanda, contesto, [], pagine).encode("utf-8"),
                       cwd=vault, env=env, capture_output=True, timeout=600)
    righe = [json.loads(r) for r in p.stdout.decode("utf-8").splitlines() if r.startswith("{")]
    usi = [b for r in righe if r.get("type") == "assistant" for b in r["message"].get("content", [])
           if b.get("type") == "tool_use"]
    letti = [b["input"].get("file_path", "") for b in usi if b["name"] == "Read"]
    fine = next((r for r in righe if r.get("type") == "result"), {})
    return {"condizione": "hook", "domanda": domanda, "risposta": fine.get("result", ""),
            "strumenti": [b["name"] for b in usi], "pagine_lette": [Path(f).stem for f in letti],
            "pagine_precaricate": len(pagine), "secondi": round(time.time() - inizio, 1),
            "costo_usd": fine.get("total_cost_usd"),
            "errore": p.stderr.decode("utf-8", "replace")[-2000:] if p.returncode else "", "righe": righe}


def misura_hook(vault, db_path, modello, out, paralleli, giri, scelte, hook_da):
    claude = shutil.which("claude") or sys.exit("claude non è nel PATH")
    regole = carica_regole(hook_da) if hook_da else modello_hook.REGOLE_HAIKU
    out.mkdir(parents=True, exist_ok=True)
    lavori = [(i, g) for g in range(giri) for i in scelte]
    with ThreadPoolExecutor(paralleli) as ex:
        esiti = list(ex.map(lambda l: esegui_hook(claude, vault, db_path, modello, DOMANDE[l[0]][0], regole,
                                                  not hook_da), lavori))
    print(f"hook · modello {modello} · {'regole di ' + str(hook_da) + ', senza pagine pre-caricate' if hook_da else 'versione corrente'}"
          f" · {giri} giri")
    print(f"{'domanda':<40} {'giro':>4} {'regex':>6} {'s':>5} {'$':>7} pagine lette (Read)")
    for (i, g), e in zip(lavori, esiti):
        trovate = [bool(re.search(r, e["risposta"], re.I)) for r in DOMANDE[i][2]]
        e["regex"] = trovate
        (out / f"{i + 1:02d}-hook-{g + 1}.json").write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"{i + 1:02d}-hook-{g + 1}.md").write_text(e["risposta"], encoding="utf-8")
        print(f"{DOMANDE[i][0][:39]:<40} {g + 1:>4} {sum(trovate):>3}/{len(trovate):<2} {e['secondi']:>5.0f} "
              f"{e['costo_usd'] or 0:>7.4f} {', '.join(e['pagine_lette']) or '-'}"
              + (f"  ERRORE {e['errore'][:100]}" if e["errore"] else ""))
    print(f"→ {out}")


def main():
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=qui / "graph.sqlite")
    ap.add_argument("--modello", help="lancia anche il confronto ricerca/grafo con questo modello")
    ap.add_argument("--out", type=Path, help="cartella per le risposte del confronto (obbligatoria con --modello)")
    ap.add_argument("--paralleli", type=int, default=4)
    ap.add_argument("--giri", type=int, default=1, help="esecuzioni per domanda e condizione (le risposte variano)")
    ap.add_argument("--routing", action="store_true", help="solo la tabella del routing (nessun modello chiamato)")
    ap.add_argument("--hook", action="store_true",
                    help="con --modello: passa dal percorso di modello_hook.py (contesto, pagine pre-caricate, regole di Haiku)")
    ap.add_argument("--hook-da", type=Path, help="con --hook: cartella con un modello_hook.py precedente (regole vecchie, niente pagine)")
    ap.add_argument("--domande", help="solo queste domande del confronto, numerate da 1: es. 5,12")
    ap.add_argument("--banco", type=Path, default=qui / "banco.json",
                    help="il banco delle domande (.graph/banco.json); senza file la sezione non si stampa")
    ap.add_argument("--banco-salva", type=Path, metavar="FILE", help="scrive in JSON i risultati del banco, per domanda")
    ap.add_argument("--banco-confronta", type=Path, metavar="FILE", help="confronta il banco con un salvataggio precedente")
    ap.add_argument("--solo-banco", action="store_true", help="stampa solo il banco, poi exit 0")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.solo_banco and (args.modello or args.routing):
        ap.error("--solo-banco non si usa con --modello o --routing")
    prima = None
    if args.banco_confronta:
        prima = carica_salvataggio(args.banco_confronta)
        if prima is None:
            ap.error(f"{args.banco_confronta} non è un salvataggio di --banco-salva")
    if args.routing:
        sys.exit(1 if misura_routing() else 0)
    db = sqlite3.connect(args.db)
    if args.solo_banco:
        usa_banco(db, args, prima)
        sys.exit(0)
    misura_recall(db)
    difetti = misura_negativi(db) + misura_testo(db) + misura_memoria()
    misura_attesi_falliti(db)  # informativo: mai nell'exit
    usa_banco(db, args, prima)  # informativo: mai nell'exit
    if args.modello:
        if not args.out:
            ap.error("--modello richiede --out")
        print()
        scelte = [int(n) - 1 for n in args.domande.split(",")] if args.domande else range(len(DOMANDE))
        if args.hook:
            misura_hook(qui.parent, args.db, args.modello, args.out, args.paralleli, args.giri, list(scelte), args.hook_da)
        else:
            misura_modello(qui.parent, args.modello, args.out, args.paralleli, args.giri, list(scelte))
    sys.exit(1 if difetti else 0)


if __name__ == "__main__":
    main()

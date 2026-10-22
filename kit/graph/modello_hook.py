"""Hook SessionStart e UserPromptSubmit: graph research con Opus, e risposta di Haiku quando il grafo dà il contesto.

Modello attivo: agli hook Claude Code non lo passa, quindi si ricostruisce. Vince il segnale più recente fra
  - SessionStart: campo `model` dell'evento se c'è, altrimenti `--model` nella riga di comando di claude (CLAUDE_PID),
    altrimenti ANTHROPIC_MODEL, altrimenti `model` in .claude/settings.local.json, .claude/settings.json, ~/.claude/settings.json;
    dopo /clear e /compact il modello resta quello del processo, già annotato;
  - transcript: `/model` («Set model to `Opus 5.5`», scritto appena dato il comando), il modello dei turni passati.
Se non è di classe Opus (opusplan non conta: usa Opus solo in plan mode) avvisa una volta per sessione e modello;
se lo è, a ogni SessionStart (anche dopo /clear e /compact) ricorda il prefisso @opus (AVVISO_OPUS).

Con Opus, a ogni prompt chiama recall_hook.py (che quindi non va registrato a parte; se non risponde in
TIMEOUT_RECALL secondi o fallisce, lo dichiara con un systemMessage e un avviso al modello: guasto_recall)
e, se il grafo riconosce delle pagine, passa domanda, contesto e conversazione recente all'ultimo Haiku
(alias `haiku`) in un `claude -p` che può solo leggere il vault; la risposta si mostra bloccando il prompt, così Opus non viene chiamato.
Prima di chiamare Haiku l'hook gli pre-carica nel prompt il testo delle pagine seme (punti_di_partenza) e, per ogni
seme, delle sue pagine di sintesi (tag `sintesi` e parte_di verso il seme: «Funzionamento del Gestionale» per
Gestionale), perché un hub da solo non dice «come funziona». Tetto di MAX_PAGINE_PRECARICATE caratteri in tutto,
prima i semi poi le sintesi; la pagina che sfora si tronca con «[…]». Le pagine `entropia` non nominate non si caricano.
Risponde comunque Opus, con il contesto di recall_hook.py, se:
  - il recall è fallito (tempo scaduto, errore, output non valido) o il grafo non è stato ricostruito: il contesto
    porta MARCA_GUASTO, l'utente vede il motivo nel messaggio e il modello riceve l'avviso a cercare nelle pagine;
  - il grafo non riconosce nessuna pagina (serve la ricerca nei file, e la memoria deve registrare le pagine lette);
    il contesto è allora il solo AVVISO_NESSUNA_PAGINA di recall_hook.py, che Opus riceve (anche con @opus o dopo
    risposte di Haiku da consegnare) e che lo manda a cercare in wiki/, oppure i fatti delle pagine trovate nel
    testo (recall.per_testo): aggancio debole, quindi Opus anche lì;
    il routing guarda solo il testo scritto dall'utente, non i blocchi <pasted_content> incollati;
  - la richiesta modifica il vault (ingerisci, lint, salva, aggiorna...) o è un comando /...;
  - la domanda riguarda il sistema e non il vault (haiku, opus, claude, hook, prompt, routing);
  - il prompt inizia con @opus;
  - la domanda è ampia (cosa fa, come funziona, spiega, confronta...: regex AMPIA), è di elenco (elenca, lista,
    tutti i, quali, quanti, ci sono, dammi i...: regex ELENCO; «quale» singolare e «tutto» restano puntuali), oppure
    nomina soltanto un hub (una pagina con almeno SOGLIA_HUB pagine parte_di, come il sistema principale del vault): Haiku sulle
    domande ampie e di elenco perde pezzi delle pagine, e il motivo compare nel messaggio all'utente. Si guarda solo il testo scritto dall'utente;
  - Haiku va in errore, supera TIMEOUT_HAIKU secondi o risponde PASSA_A_OPUS (domanda fuori dal vault
    o risposta non trovata nelle pagine).
Le risposte di Haiku non entrano nella cronologia: si passano a Opus nel contesto del primo turno successivo.
Stato per sessione in modello.json. Il `claude -p` di Haiku non carica gli hook del vault (--setting-sources user)
e ha GRAFO_HAIKU=1, con cui questo hook non fa nulla.

Registrato in .claude/settings.json; si prova a mano con:
  echo '{"hook_event_name": "UserPromptSubmit", "session_id": "prova", "prompt": "il file delle fatture non arriva, a chi scrivo?"}' | python .graph/modello_hook.py
"""
import json
import os
import re
import shutil
import subprocess
import sqlite3
from graph_db import connect_graph
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from build_graph import norm
from domande import TAG_ENTROPIA
from recall import (IMPERATIVI, INFINITI, INGLESE, META, SCRITTURA,  # noqa: F401 (nomi riesportati)
                    STOPWORD, punti_di_partenza, scritto)
from recall_hook import AVVISO_NESSUNA_PAGINA, AVVISO_SENZA_GRAFO, MARCA_GUASTO, MAX_ERRORE

QUI = Path(__file__).resolve().parent
VAULT = QUI.parent
STATO = QUI / "modello.json"
HAIKU = "haiku"            # alias: l'ultimo Haiku disponibile
TIMEOUT_RECALL = 30        # secondi per recall_hook.py
TIMEOUT_HAIKU = 150        # secondi; l'hook in settings.json ne ha 180
GIORNI_STATO = 7           # sessioni più vecchie si tolgono da modello.json
RISPOSTE_TENUTE = 5        # risposte di Haiku conservate per sessione
SCAMBI_RECENTI = 3         # scambi della conversazione passati a Haiku
MAX_TESTO = 1500           # caratteri per messaggio passato a Haiku o a Opus
MAX_PAGINE_PRECARICATE = 40000  # caratteri di pagine della wiki pre-caricate nel prompt di Haiku, in tutto
MIN_PAGINA_TRONCATA = 2000      # sotto questo spazio residuo una pagina non si tronca ma si salta
TAG_SINTESI = "sintesi"    # pagina «come funziona» di un hub, collegata con parte_di
PREFISSO_OPUS = "@opus"
SOGLIA_HUB = 5             # pagine parte_di verso una pagina da cui è un hub

AVVISO_MODELLO = ("per la graph research è preferibile un modello di classe Opus: usa /model opus "
                  "(modello attuale: {modello})")
AVVISO_OPUS = "@opus per usare Opus per tutte le domande"  # a ogni avvio con Opus: il prefisso salta Haiku
AVVISO_IGNOTO = ("modello attivo non riconosciuto: le domande vanno al modello della sessione, non a Haiku. "
                 "Per la graph research è preferibile un modello di classe Opus: usa /model opus")

# SCRITTURA, META (e le liste IMPERATIVI, INFINITI, INGLESE) sono in recall.py, importate sopra: restano
# disponibili come modello_hook.SCRITTURA ecc.
# Domande ampie: la risposta sta in più pagine, non in un fatto solo. Dopo norm() gli apostrofi e gli accenti
# diventano spazi: «cos'è» → «cos e», «com'è fatto» → «com e fatto». «perché, chi, dove, quando, quale» sono puntuali.
AMPIA = re.compile(r"\b(?:cosa fa(?:nno)?|(?:che )?cos e|cosa e|come funziona\w*|(?:come|com) e fatt[oaie]|"
                   r"spieg\w+|descri\w+|panoramica|riassu\w+|in generale|tutto su|parlami di|confront\w+|differenz\w+)\b")
# Domande di elenco: la risposta è una lista presa da più punti delle pagine e Haiku ne perde dei pezzi. Si guarda il
# plurale («quali», «quanti», «tutti i», «ci sono»): «quale», «tutto» e «dammi il» restano puntuali. «quali» da solo
# basta: è plurale e chiede più cose, e nel dubbio sbaglia verso Opus (anche «quali permessi servono?» va a Opus).
ELENCO = re.compile(r"\b(?:elenc\w+|list[ae]|listami|tutt[ie]|quali|quant[ie]|ci sono|"
                    r"(?:dammi|mostrami|fammi vedere) (?:i|gli|le)|mostrami tutt\w+)\b")
PASSA = "PASSA_A_OPUS"

REGOLE_HAIKU = f"""Rispondi a una domanda sul vault Obsidian nella cartella corrente (pattern "LLM Wiki"):
le pagine sono in wiki/<Nome pagina>.md, l'indice è index.md.
- Ti viene dato il contesto calcolato da un grafo (frontmatter e wikilink): è un punto di partenza, non una fonte.
  Prima di citare un fatto che non è in una pagina già letta aprila con Read in wiki/; se serve, cerca con Grep e Glob.
- Le pagine sotto «Pagine della wiki già lette per te» sono già lette: non riaprirle con Read (salvo quelle troncate
  da «[…]»), ma citale come le altre.
- Se una pagina è un hub (ha una «Mappa delle pagine» o molte pagine che la puntano con parte_di), prima di
  rispondere apri con Read le pagine figlie pertinenti alla domanda che non ti sono già state date.
- Riporta le avvertenze ⚠️ (contraddizioni, divergenze tra documentazione e codice, punti non verificati) delle pagine
  lette, se pertinenti alla domanda.
- Non ridurre a una riga ciò che una pagina espone come tabella o elenco di regole: riporta le voci, con i valori
  (una tabella di codici di uscita, soglie o stati si riporta intera, anche in forma di tabella).
- Se la domanda chiede cosa fa o come funziona qualcosa, non fermarti alla sezione «Cosa fa» dell'hub: ripercorri
  anche le pagine di sintesi e di dettaglio già lette e riporta ogni aspetto che espongono (scopo, flusso passo per
  passo, regole e soglie, stati ed esiti, codici di uscita, configurazione, esercizio, avvertenze).
- Cita le pagine come [[Nome pagina]] accanto a ogni fatto. Non inventare nulla che non sia scritto nelle pagine.
- Rispondi esattamente {PASSA}, senza altro testo, se la domanda non riguarda il contenuto del vault
  (per esempio chiede di Claude, dei modelli, degli hook, del grafo o di come viene mostrata una risposta)
  oppure se dopo aver letto le pagine la risposta non c'è.
- Puoi solo leggere: non proporre di salvare o modificare pagine.
- Rispondi in italiano, in markdown: una risposta completa, che copra ciò che le pagine dicono sulla domanda,
  ma senza ridondanze né giri di parole."""


def adesso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def carica_stato():
    try:
        stato = json.loads(STATO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stato = {}
    stato.setdefault("sessioni", {})
    stato.setdefault("processi", {})
    limite = (datetime.now(timezone.utc) - timedelta(days=GIORNI_STATO)).isoformat()
    for chiave in ("sessioni", "processi"):
        stato[chiave] = {k: v for k, v in stato[chiave].items() if v.get("visto", "") >= limite}
    return stato


def salva_stato(stato):
    tmp = STATO.with_suffix(".tmp")
    tmp.write_text(json.dumps(stato, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATO)


def classe(modello):
    """'opus', 'altro' o None se non si sa (nessun modello, o 'default' che dipende dall'account)."""
    m = (modello or "").lower()
    if not m or m == "default":
        return None
    if "plan" in m:  # opusplan: Opus solo in plan mode
        return "altro"
    return "opus" if "opus" in m or m == "best" else "altro"


# --- modello attivo ---------------------------------------------------------------------------------------

def da_riga_di_comando():
    pid = os.environ.get("CLAUDE_PID", "")
    if not pid.isdigit():
        return None
    try:
        if os.name == "nt":
            riga = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                capture_output=True, timeout=8).stdout.decode("utf-8", "replace")
        else:
            riga = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    trovato = re.search(r"--model[= ]+\"?([\w.\-\[\]]+)", riga)
    return trovato.group(1) if trovato else None


def da_impostazioni():
    if os.environ.get("ANTHROPIC_MODEL"):
        return os.environ["ANTHROPIC_MODEL"]
    for f in (VAULT / ".claude" / "settings.local.json", VAULT / ".claude" / "settings.json",
              Path.home() / ".claude" / "settings.json"):
        try:
            modello = json.loads(f.read_text(encoding="utf-8")).get("model")
        except (OSError, ValueError):
            continue
        if modello:
            return modello
    return None


def leggi_transcript(path):
    righe = []
    try:
        with open(path, encoding="utf-8") as f:
            for riga in f:
                try:
                    righe.append(json.loads(riga))
                except ValueError:
                    pass
    except (OSError, TypeError):
        pass
    return righe


def testo(record):
    contenuto = (record.get("message") or {}).get("content")
    if isinstance(contenuto, str):
        return contenuto
    if isinstance(contenuto, list):
        return "\n".join(b.get("text", "") for b in contenuto if isinstance(b, dict) and b.get("type") == "text")
    return ""


def dal_transcript(righe):
    """(quando, modello) dell'ultimo segnale nel transcript, o None."""
    ultimo = None
    for r in righe:
        if r.get("isSidechain"):
            continue
        modello = None
        allegato = r.get("attachment") or {}
        if allegato.get("type") == "model":
            modello = (allegato.get("identity") or {}).get("modelId")
        elif r.get("type") == "assistant":
            modello = (r.get("message") or {}).get("model")
            modello = None if modello == "<synthetic>" else modello
        elif r.get("type") == "user":
            # «Set model to `Opus 5.5` and saved as your default…»; il nome può avere spazi (Opus Plan Mode)
            cambio = re.search(r"<local-command-stdout>(?:Set model to|Kept model as)\s*(?:`([^`]+)`|(.+?)(?:\s+and\s|\s*\(|\s*<|$))",
                               re.sub(r"\x1b\[[0-9;]*m", "", testo(r)))
            modello = (cambio.group(1) or cambio.group(2)).strip() if cambio else None
        if modello and r.get("timestamp"):
            ultimo = (r["timestamp"], modello)
    return ultimo


def modello_attivo(sessione, righe):
    candidati = [c for c in (dal_transcript(righe), tuple(sessione.get("inizio") or ()) or None) if c]
    return max(candidati)[1] if candidati else None


# --- conversazione ----------------------------------------------------------------------------------------

def taglia(t, n=MAX_TESTO):
    t = t.strip()
    return t if len(t) <= n else t[:n] + " […]"


def scambi_recenti(righe, risposte_haiku):
    """Ultimi scambi utente/assistente (Opus dal transcript, Haiku da modello.json), in ordine di tempo."""
    scambi, domanda = [], None
    for r in righe:
        if r.get("isSidechain") or r.get("isMeta"):
            continue
        t = testo(r)
        if r.get("type") == "user" and t and not t.lstrip().startswith("<"):
            domanda = (r.get("timestamp", ""), t)
        elif r.get("type") == "assistant" and t and domanda:
            if scambi and scambi[-1][1] == domanda[1]:
                scambi[-1] = (domanda[0], domanda[1], scambi[-1][2] + "\n" + t)
            else:
                scambi.append((domanda[0], domanda[1], t))
    scambi += [(h["quando"], h["domanda"], h["risposta"]) for h in risposte_haiku]
    return sorted(scambi)[-SCAMBI_RECENTI:]


# --- recall e Haiku ---------------------------------------------------------------------------------------

def guasto_recall(motivo, stderr=b""):
    """Output al posto di quello di recall_hook.py quando non si riesce a ottenerlo: avvisa utente e modello.

    L'avviso al modello è AVVISO_SENZA_GRAFO di recall_hook.py (importato, non duplicato: se cambia
    il testo o la marca cambiano insieme, e instradamento li riconosce dalla marca).
    """
    righe = stderr.decode("utf-8", "replace").strip().splitlines()
    if righe:
        motivo += f": {taglia(righe[-1], MAX_ERRORE)}"
    return {"systemMessage": f"recall del grafo non riuscito ({motivo})",
            "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": AVVISO_SENZA_GRAFO}}


def richiama(evento):
    """Output JSON di recall_hook.py per lo stesso evento.

    Se il recall non riesce (tempo scaduto, processo non avviabile, exit ≠ 0 senza output, JSON non valido)
    restituisce guasto_recall(), non {}: il guasto si vede e il contesto porta la marca che manda a Opus.
    """
    try:
        uscita = subprocess.run([sys.executable, str(QUI / "recall_hook.py")],
                                input=json.dumps(evento).encode("utf-8"), capture_output=True, timeout=TIMEOUT_RECALL)
    except subprocess.TimeoutExpired:
        return guasto_recall(f"tempo scaduto dopo {TIMEOUT_RECALL} s")
    except (OSError, subprocess.SubprocessError) as e:
        return guasto_recall(f"processo non avviato: {taglia(str(e), MAX_ERRORE)}")
    if not uscita.stdout.strip():
        return guasto_recall(f"nessun output, exit {uscita.returncode}", uscita.stderr)
    try:
        esito = json.loads(uscita.stdout.decode("utf-8"))
    except ValueError:
        return guasto_recall("output non valido", uscita.stderr)
    return esito if isinstance(esito, dict) else guasto_recall("output non valido", uscita.stderr)


def riconosciute(prompt):
    try:
        db = connect_graph(QUI / "graph.sqlite")
        try:
            return punti_di_partenza(db, prompt)
        finally:
            db.close()
    except sqlite3.Error:
        return []


def pagine_precaricate(domanda, vault=VAULT, budget=MAX_PAGINE_PRECARICATE):
    """Blocco di testo con le pagine seme e le loro sintesi, già lette, o "" se non ce ne sono.

    I semi si cercano solo nel testo scritto dall'utente, non nei blocchi incollati (recall.scritto); Haiku
    riceve comunque il prompt intero come domanda (input_haiku).
    Ordine di priorità: i semi (nell'ordine di punti_di_partenza), poi le sintesi dei semi. Una pagina `entropia`
    entra solo se è un seme. La pagina che non sta nel budget si tronca con «[…]» (Haiku può riaprirla con Read);
    se restano meno di MIN_PAGINA_TRONCATA caratteri la si salta, perché un frammento non serve.
    """
    try:
        db = connect_graph(QUI / "graph.sqlite")
        try:
            semi = punti_di_partenza(db, domanda)
            tags = {id_: (t or "").split(", ") for id_, t in db.execute("SELECT id, tags FROM entities")}
            sintesi = []
            for seme in semi:
                figlie = sorted(s for (s,) in db.execute(
                    "SELECT source_id FROM relations WHERE type = 'parte_di' AND target_id = ?", (seme,)))
                sintesi += [f for f in figlie if TAG_SINTESI in tags.get(f, []) and TAG_ENTROPIA not in tags.get(f, [])]
        finally:
            db.close()
    except sqlite3.Error:
        return ""
    blocchi, usati = [], 0
    for nome in dict.fromkeys(semi + sintesi):  # senza doppioni, semi per primi
        try:
            corpo = (vault / "wiki" / f"{nome}.md").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        intestazione = f"=== wiki/{nome}.md ===\n"
        libero = budget - usati - len(intestazione)
        if len(corpo) > libero:
            if libero < MIN_PAGINA_TRONCATA:
                continue
            corpo = corpo[:libero] + " […]"
        blocchi.append(intestazione + corpo)
        usati += len(intestazione) + len(corpo)
    return "\n\n".join(blocchi)


def input_haiku(prompt, contesto, scambi, pagine=""):
    """Il testo che si passa a Haiku su stdin; lo usa anche misura.py --hook."""
    parti = []
    if scambi:
        parti.append("Conversazione recente, per capire i riferimenti:\n" + "\n\n".join(
            f"Utente: {taglia(d)}\nRisposta: {taglia(r)}" for _, d, r in scambi))
    if pagine:
        parti.append(f"Pagine della wiki già lette per te:\n\n{pagine}")
    parti.append(f"Contesto dal grafo della wiki:\n{contesto}")
    parti.append(f"Domanda dell'utente:\n{prompt}")
    return "\n\n".join(parti)


def argomenti_haiku(claude, modello=HAIKU, regole=REGOLE_HAIKU):
    """Riga di comando del `claude -p` che risponde: sola lettura, senza hook del vault; la usa anche misura.py."""
    return [claude, "-p", "--model", modello, "--output-format", "json",
            "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob", "--permission-mode", "dontAsk",
            "--setting-sources", "user", "--strict-mcp-config", "--no-session-persistence",
            "--disable-slash-commands", "--system-prompt", regole]


def hub_fra(semi):
    """I semi con almeno SOGLIA_HUB pagine parte_di verso di sé."""
    if not semi:
        return []
    try:
        db = connect_graph(QUI / "graph.sqlite")
        try:
            return [s for s in semi if db.execute(
                "SELECT COUNT(*) FROM relations WHERE type = 'parte_di' AND target_id = ?", (s,)).fetchone()[0]
                >= SOGLIA_HUB]
        finally:
            db.close()
    except sqlite3.Error:
        return []


def solo_nomi(domanda, semi):
    """True se tolti i nomi (e gli alias) dei semi restano solo stopword: «Gestionale?», «Gestionale»."""
    testo = f" {norm(domanda)} "
    nomi = list(semi)
    try:
        db = connect_graph(QUI / "graph.sqlite")
        try:
            nomi += [a for (a,) in db.execute(
                f"SELECT alias FROM aliases WHERE entity_id IN ({','.join('?' * len(semi))})", semi)]
        finally:
            db.close()
    except sqlite3.Error:
        pass
    for nome in sorted(map(norm, nomi), key=len, reverse=True):
        testo = testo.replace(f" {nome} ", "  ")
    return not [w for w in testo.split() if w not in STOPWORD]


def instradamento(prompt, modello, contesto):
    """(destinazione, motivo): "haiku" o "opus" e perché; il motivo è in italiano e per Opus è breve.

    Le prime condizioni sono quelle storiche (modello, contesto, guasto del recall, prefisso, scrittura, meta,
    nessun seme);
    le ultime tre guardano la domanda scritta dall'utente: ampia (AMPIA), di elenco (ELENCO) o solo il nome di un hub.
    """
    domanda = scritto(prompt)  # il routing guarda solo quello che l'utente ha scritto
    if classe(modello) != "opus":
        return "opus", "modello della sessione non Opus"
    if not contesto or contesto.strip() == AVVISO_NESSUNA_PAGINA:  # il solo avviso «nessuna pagina» non è contesto
        return "opus", "nessun contesto dal grafo"
    if MARCA_GUASTO in contesto:  # recall fallito o grafo non ricostruito: niente Haiku, che non verificherebbe
        return "opus", "recall del grafo non riuscito o grafo non aggiornato"
    if prompt.lstrip().startswith(("/", PREFISSO_OPUS)):
        return "opus", "comando o prefisso @opus"
    if SCRITTURA.search(norm(domanda)):
        return "opus", "richiesta di modifica del vault"
    if META.search(norm(domanda)):
        return "opus", "domanda sul sistema"
    semi = riconosciute(domanda)
    if not semi:
        return "opus", "nessuna pagina riconosciuta"
    if AMPIA.search(norm(domanda)):
        return "opus", "domanda ampia: risponde Opus"
    if ELENCO.search(norm(domanda)):
        return "opus", "domanda di elenco: risponde Opus"
    hub = hub_fra(semi)
    if hub and solo_nomi(domanda, semi):
        return "opus", f"domanda generica su un hub ({hub[0]}): risponde Opus"
    return "haiku", "domanda puntuale"


def chiedi_a_haiku(prompt, contesto, scambi):
    claude = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    if not claude:
        raise RuntimeError("eseguibile claude non trovato")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE_CODE_MESSAGING") and k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID")}
    env["GRAFO_HAIKU"] = "1"
    uscita = subprocess.run(
        argomenti_haiku(claude),
        input=input_haiku(prompt, contesto, scambi, pagine_precaricate(prompt)).encode("utf-8"),
        capture_output=True, cwd=VAULT, env=env, timeout=TIMEOUT_HAIKU)
    try:
        esito = json.loads(uscita.stdout.decode("utf-8"))
    except ValueError:
        raise RuntimeError(taglia(uscita.stderr.decode("utf-8", "replace") or f"exit {uscita.returncode}", 300))
    if esito.get("is_error") or not (esito.get("result") or "").strip():
        raise RuntimeError(taglia(str(esito.get("result") or esito.get("subtype") or "risposta vuota"), 300))
    if PASSA in esito["result"]:
        raise RuntimeError("domanda fuori dal vault o risposta non trovata nelle pagine")
    modelli = [m for m in esito.get("modelUsage") or {} if "haiku" in m] or [HAIKU]
    return esito["result"].strip(), modelli[0], esito.get("total_cost_usd") or 0


# --- eventi -----------------------------------------------------------------------------------------------

def avviso(sessione, modello):
    """Testo dell'avviso se il modello non è Opus e per questo modello non si è già avvisato."""
    if classe(modello) == "opus" or sessione.get("avvisato") == (modello or "?"):
        return None
    sessione["avvisato"] = modello or "?"
    return AVVISO_MODELLO.format(modello=modello) if modello else AVVISO_IGNOTO


def inizio_sessione(evento, stato, sessione, processo):
    origine = evento.get("source", "")
    if evento.get("model"):
        modello = evento["model"]
    elif origine in ("clear", "compact") and processo.get("modello"):
        modello = processo["modello"]
    else:
        modello = da_riga_di_comando() or da_impostazioni()
    sessione["inizio"] = [adesso(), modello] if modello else None
    processo["modello"] = modello
    testo_avviso = AVVISO_OPUS if classe(modello) == "opus" else avviso(sessione, modello)
    if testo_avviso:
        print(json.dumps({"systemMessage": testo_avviso}, ensure_ascii=False))


def prompt_utente(evento, stato, sessione, processo):
    prompt = evento.get("prompt", "")
    righe = leggi_transcript(evento.get("transcript_path"))
    modello = modello_attivo(sessione, righe)
    if modello:
        processo["modello"] = modello
    uscita = richiama(evento)
    messaggi = [m for m in (uscita.get("systemMessage"), avviso(sessione, modello)) if m]
    contesto = (uscita.get("hookSpecificOutput") or {}).get("additionalContext", "")
    risposte = sessione.setdefault("haiku", [])

    destinazione, motivo = instradamento(prompt, modello, contesto)
    if motivo.startswith(("domanda ampia", "domanda di elenco", "domanda generica")):
        messaggi.append(motivo)
    if destinazione == "haiku":
        inizio = time.perf_counter()
        try:
            risposta, modello_haiku, costo = chiedi_a_haiku(prompt, contesto, scambi_recenti(righe, risposte))
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            motivo = "tempo scaduto" if isinstance(e, subprocess.TimeoutExpired) else str(e)
            messaggi.append(f"Haiku non ha risposto ({motivo}): la domanda passa a {modello}")
        else:
            secondi = round(time.perf_counter() - inizio)
            risposte.append({"quando": adesso(), "domanda": prompt, "risposta": risposta, "consegnata": False})
            del risposte[:-RISPOSTE_TENUTE]
            intestazione = " · ".join([f"risposta di {modello_haiku} ({secondi} s, ${costo:.3f}), Opus non chiamato",
                                       *messaggi])
            print(json.dumps({"decision": "block", "reason": f"{intestazione}\n\n{risposta}"}, ensure_ascii=False))
            return

    da_consegnare = [h for h in risposte if not h["consegnata"]]
    if da_consegnare:
        contesto = "\n\n".join(filter(None, [
            "Risposte già date all'utente da Haiku, fuori dalla cronologia che vedi (l'hook ha bloccato quei prompt):\n"
            + "\n\n".join(f"Domanda: {taglia(h['domanda'])}\nRisposta di Haiku: {taglia(h['risposta'])}"
                          for h in da_consegnare), contesto]))
        for h in da_consegnare:
            h["consegnata"] = True
    if prompt.lstrip().startswith(PREFISSO_OPUS):
        contesto = f"Il prefisso {PREFISSO_OPUS} nel prompt serve solo a scegliere il modello: ignoralo.\n{contesto}"
    if not messaggi and not contesto:
        return
    risultato = {"systemMessage": " · ".join(messaggi)} if messaggi else {}
    if contesto:
        risultato["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit", "additionalContext": contesto}
    print(json.dumps(risultato, ensure_ascii=False))


def main():
    if os.environ.get("GRAFO_HAIKU") == "1":
        return
    sys.stdout.reconfigure(encoding="utf-8")
    evento = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    stato = carica_stato()
    sessione = stato["sessioni"].setdefault(evento.get("session_id", ""), {})
    processo = stato["processi"].setdefault(os.environ.get("CLAUDE_PID", "?"), {})
    sessione["visto"] = processo["visto"] = adesso()
    if evento.get("hook_event_name") == "SessionStart":
        inizio_sessione(evento, stato, sessione, processo)
    elif evento.get("hook_event_name") == "UserPromptSubmit":
        prompt_utente(evento, stato, sessione, processo)
    salva_stato(stato)


if __name__ == "__main__":
    main()

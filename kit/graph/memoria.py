"""Memoria delle domande che il grafo non riconosce, e delle pagine lette per rispondere.

Il grafo si ricostruisce da zero dalla wiki, quindi quello che si impara sta in un file a parte, memoria.sqlite.
Ciclo, legato al session_id che Claude Code passa a ogni hook:
  UserPromptSubmit  nessun punto di partenza nel grafo e il prompt è una domanda sul contenuto → resta in sospeso
                    (recall_hook.py). Non lo sono (e_domanda): comandi /..., richieste di modifica (SCRITTURA di recall.py:
                    ingerisci, lint, aggiorna...; ma «come si aggiorna X?» è una domanda), domande sul sistema (META), conferme e conversazione (CONFERME):
                    leggono pagine, ma per eseguire un lavoro, e insegnerebbero associazioni sbagliate
  PostToolUse Read  ogni pagina di wiki/ letta mentre una domanda è in sospeso le viene collegata (learn_hook.py)
  Stop              domanda e pagine lette passano nell'archivio; senza letture la domanda si scarta
Conta solo Read, non Grep: Grep restituisce decine di file, le pagine aperte sono quelle che servivano.
A una domanda simile a una già vista (almeno 2 radici in comune, Dice ≥ 0.5) le pagine collegate
diventano punti di partenza del recall. Nel grafo non entra nulla da sé: le domande ricorrenti si elencano
qui sotto e, se l'associazione è giusta, si promuovono a mano ad `aliases` della pagina.

Log locale dei turni (non insegna nulla al recall: serve a misurarlo sull'uso vero). A OGNI prompt recall_hook.py scrive
una riga in `turni` (anche senza semi, salvo GRAFO_SENZA_MEMORIA=1): il testo scritto (tagliato a MAX_TESTO), i semi con la
loro origine (nome: citata per nome o alias; titolo: parole del titolo vicine; memoria: letta per domande simili;
testo: ripiego FTS), le pagine iniettate nei fatti e il routing se disponibile (oggi NULL). learn_hook.py collega ogni
Read di una pagina di wiki/ all'ultimo turno della sessione (`letture_turno`), sempre, anche senza domanda in sospeso:
il confronto fra pagine iniettate e pagine lette dice quando il recall ha portato pagine inutili («iniettata non letta»)
o ne ha mancate («letta non iniettata»: il modello ha dovuto cercare da sé). I turni più vecchi di GIORNI_TURNI giorni
si cancellano a ogni apri(). Il log è un di più: un errore nel log non rompe mai gli hook.

Uso:
  python .graph/memoria.py              domande apprese, con le pagine lette e quante volte
  python .graph/memoria.py "domanda"    pagine che la memoria porterebbe a questa domanda
  python .graph/memoria.py --turni [N]  ultimi N turni (10 se omesso): semi con origine, pagine iniettate, pagine lette;
                                        marca «iniettata non letta» e «letta non iniettata»
  python .graph/memoria.py --dimentica "testo"   toglie una domanda appresa e le sue pagine (testo esatto o sottostringa unica)
"""
import argparse
import json
import re
import sqlite3
from graph_db import connect_graph
import sys
from datetime import datetime, timedelta
from pathlib import Path

from build_graph import norm
from recall import META, SCRITTURA, date_nel_testo, radici, scritto

SOGLIA = 0.5      # Dice minimo fra le radici della domanda e quelle di una domanda già vista
MAX_PAGINE = 3    # pagine portate al recall da domande simili
MAX_TESTO = 500   # caratteri della domanda conservati
GIORNI_TURNI = 90  # i turni del log più vecchi si cancellano
# Prima parola (norm) delle conferme e della conversazione breve: non sono domande sul contenuto, ma i turni di
# lavoro che le seguono leggono pagine (es. «sì, aggiungi l'alias» fa aprire la pagina da modificare).
# Elenco conservativo: solo parole che non aprono mai una domanda vera; «si» e «no» a parte (CONFERMA_SI_NO).
# «esegui» c'è perché è un comando («esegui ingest della cartella raw»). Non ci sono «dimmi», «dammi», «come»...
# che introducono domande: nel dubbio una domanda in più nell'archivio costa meno di un comando che insegna pagine a caso.
CONFERME = set("ok okay va vai procedi procediamo continua continuiamo grazie fallo falla facciamolo esegui eseguilo "
               "eseguila perfetto bene benissimo certo confermo conferma ottimo".split())
# «sì» con l'accento, o «si»/«no» seguiti da punteggiatura o soli: «si può rilanciare il job?» è una domanda
CONFERMA_SI_NO = re.compile(r"^(?:sì|(?:si|no)\s*(?:[,.!;:]|$))")
# Parole che aprono una domanda (norm: senza accenti), con eventuale preposizione: «a chi», «da dove», «in che modo»
INTERROGATIVE = re.compile(r"^(?:(?:a|da|di|in|per|con|su|tra|fra)\s+)?"
                           r"(?:come|dove|dov|chi|quando|perche|quale|quali|cosa|che|quanto|quanta|quanti|quante)\b")
# «si» impersonale o verbo di necessita'/possibilita' davanti al verbo di scrittura: parla del come, non chiede di farlo
# («come si crea», «chi devo aggiungere»). Una sola parola di mezzo («si puo aggiornare»).
IMPERSONALE = re.compile(r"\b(?:si|devo|dobbiamo|posso|possiamo|bisogna|serve)\s+(?:\w+\s+)?(?:" + SCRITTURA.pattern + ")")
# Richiesta cortese rivolta all'assistente: resta un comando anche se ha il «?» («puoi aggiornare la pagina?»)
RICHIESTA_CORTESE = re.compile(r"\b(?:puoi|potresti|riesci a|ti chiedo di|vorrei che(?: tu)?)\s+(?:\w+\s+){0,2}?(?:"
                               + SCRITTURA.pattern + ")")
# Dopo la parola di conferma, «ma», «e», «però» raccordano alla domanda vera: «ok, ma dove trovo...»
RACCORDO = re.compile(r"^(?:(?:ma|e|pero)\b\s*)+")


def apri(path):
    mem = sqlite3.connect(path, timeout=5)
    mem.executescript("""
        CREATE TABLE IF NOT EXISTS domande (id INTEGER PRIMARY KEY, testo TEXT UNIQUE,
                                            prima TEXT, ultima TEXT, volte INTEGER);
        CREATE TABLE IF NOT EXISTS pagine_lette (domanda_id INTEGER, pagina TEXT, volte INTEGER,
                                                 UNIQUE (domanda_id, pagina));
        CREATE TABLE IF NOT EXISTS sospese (sessione TEXT PRIMARY KEY, testo TEXT, quando TEXT);
        CREATE TABLE IF NOT EXISTS letture (sessione TEXT, pagina TEXT, UNIQUE (sessione, pagina));
        -- log dei turni: semi = [{"pagina":..., "origine": "nome"|"titolo"|"memoria"|"testo"}], iniettate = [pagina],
        -- routing = "haiku"/"opus" o NULL (modello_hook lo decide dopo l'hook di recall)
        CREATE TABLE IF NOT EXISTS turni (id INTEGER PRIMARY KEY, sessione TEXT, quando TEXT, testo TEXT,
                                          semi TEXT, iniettate TEXT, routing TEXT);
        CREATE TABLE IF NOT EXISTS letture_turno (turno_id INTEGER, pagina TEXT, UNIQUE (turno_id, pagina));
        CREATE INDEX IF NOT EXISTS turni_sessione ON turni (sessione, id);
    """)
    # `quando` è ISO senza fuso: il confronto fra stringhe è quello cronologico
    limite = (datetime.now() - timedelta(days=GIORNI_TURNI)).isoformat(timespec="seconds")
    mem.execute("DELETE FROM letture_turno WHERE turno_id IN (SELECT id FROM turni WHERE quando < ?)", (limite,))
    mem.execute("DELETE FROM turni WHERE quando < ?", (limite,))
    mem.commit()
    return mem


def adesso():
    return datetime.now().isoformat(timespec="seconds")


def e_domanda(testo):
    """True se il prompt sembra una domanda sul contenuto: non un comando /..., una domanda sul sistema (META),
    una conferma o conversazione breve, una richiesta di modifica, né troppo corto.
    Un verbo di SCRITTURA esclude il prompt solo se è un comando: «come si crea un canale?», «chi devo aggiungere
    in copia?» o un prompt che finisce con «?» sono domande sul contenuto (INTERROGATIVE, IMPERSONALE); restano
    comandi la richiesta cortese («puoi aggiornare...?», RICHIESTA_CORTESE) e il prompt che inizia con il verbo.
    Una conferma seguita da una domanda («ok, ma dove trovo i log?») si valuta sul resto; «ok procedi» no."""
    testo = testo.strip()
    n = norm(testo)
    # una data («il 10/09») vale come una parola: «cosa è successo il 10/09?» ha una sola radice ma è una domanda
    if testo.startswith("/") or len(radici(testo)) + len(date_nel_testo(testo)) < 2:
        return False
    if META.search(n):
        return False  # domande sul sistema: assolute, le gestisce Opus
    prima = n.split()[0]
    if prima in CONFERME or CONFERMA_SI_NO.match(testo.lower()):
        # conferma: conta solo se il resto e' una domanda («sì, aggiungi l'alias» e «ok procedi» sono lavoro)
        resto = RACCORDO.sub("", n.split(None, 1)[1] if len(n.split()) > 1 else "")
        return bool(INTERROGATIVE.match(resto)) and e_domanda_senza_conferma(resto, scritto(testo).strip())
    return e_domanda_senza_conferma(n, scritto(testo).strip())


def e_domanda_senza_conferma(n, scritto_strip):
    """Il vaglio di e_domanda su un testo normalizzato senza l'apertura di conferma."""
    if not SCRITTURA.search(n):
        return True
    # comando: una frase che inizia con il verbo («che ne dici, aggiungi l'alias?»), o la richiesta con garbo
    frasi = [norm(f) for f in re.split(r"[,;:.!?\n]", scritto_strip)] + [n]
    if any(SCRITTURA.match(f) for f in frasi if f) or RICHIESTA_CORTESE.search(n):
        return False
    return bool(INTERROGATIVE.match(n) or IMPERSONALE.search(n) or scritto_strip.endswith("?"))


def sospendi(mem, sessione, domanda):
    """Mette la domanda in attesa delle letture, se è una domanda (e_domanda); chiude prima quella rimasta aperta."""
    chiudi(mem, sessione)
    domanda = domanda.strip()
    if not e_domanda(domanda):
        return False  # comandi, modifiche, conversazione: le pagine che fanno leggere non dicono nulla sulla domanda
    mem.execute("INSERT INTO sospese VALUES (?,?,?)", (sessione, domanda[:MAX_TESTO], adesso()))
    mem.commit()
    return True


def annota(mem, sessione, pagina):
    if not mem.execute("SELECT 1 FROM sospese WHERE sessione = ?", (sessione,)).fetchone():
        return False
    mem.execute("INSERT OR IGNORE INTO letture VALUES (?,?)", (sessione, pagina))
    mem.commit()
    return True


def chiudi(mem, sessione):
    """Archivia la domanda in sospeso con le pagine lette; restituisce le pagine (vuoto = scartata)."""
    riga = mem.execute("SELECT testo FROM sospese WHERE sessione = ?", (sessione,)).fetchone()
    pagine = [p for (p,) in mem.execute("SELECT pagina FROM letture WHERE sessione = ? ORDER BY rowid", (sessione,))]
    if riga and pagine:
        ora = adesso()
        mem.execute("INSERT INTO domande (testo, prima, ultima, volte) VALUES (?,?,?,1) "
                    "ON CONFLICT (testo) DO UPDATE SET ultima = excluded.ultima, volte = volte + 1",
                    (riga[0], ora, ora))
        (id_,) = mem.execute("SELECT id FROM domande WHERE testo = ?", (riga[0],)).fetchone()
        mem.executemany("INSERT INTO pagine_lette VALUES (?,?,1) "
                        "ON CONFLICT (domanda_id, pagina) DO UPDATE SET volte = volte + 1",
                        [(id_, p) for p in pagine])
    mem.execute("DELETE FROM sospese WHERE sessione = ?", (sessione,))
    mem.execute("DELETE FROM letture WHERE sessione = ?", (sessione,))
    mem.commit()
    return pagine if riga else []


def registra_turno(mem, sessione, testo, semi, iniettate, routing=None):
    """Scrive una riga nel log dei turni; `semi` = [(pagina, origine)], `iniettate` = [pagina]. Restituisce l'id."""
    cur = mem.execute(
        "INSERT INTO turni (sessione, quando, testo, semi, iniettate, routing) VALUES (?,?,?,?,?,?)",
        (sessione, adesso(), testo.strip()[:MAX_TESTO],
         json.dumps([{"pagina": p, "origine": o} for p, o in semi], ensure_ascii=False),
         json.dumps(list(iniettate), ensure_ascii=False), routing))
    mem.commit()
    return cur.lastrowid


def leggi_turno(mem, sessione, pagina):
    """Collega la pagina letta all'ultimo turno della sessione (sempre: non serve una domanda in sospeso).
    False se la sessione non ha turni (Read in una sessione prima che il log esistesse)."""
    riga = mem.execute("SELECT MAX(id) FROM turni WHERE sessione = ?", (sessione,)).fetchone()
    if not riga[0]:
        return False
    mem.execute("INSERT OR IGNORE INTO letture_turno VALUES (?,?)", (riga[0], pagina))
    mem.commit()
    return True


def turni_recenti(mem, n):
    """Gli ultimi n turni, dal più vecchio: [(id, sessione, quando, testo, semi, iniettate, routing, lette)]."""
    righe = mem.execute("SELECT id, sessione, quando, testo, semi, iniettate, routing FROM turni "
                        "ORDER BY id DESC LIMIT ?", (n,)).fetchall()[::-1]
    return [(*r[:4], json.loads(r[4] or "[]"), json.loads(r[5] or "[]"), r[6],
             [p for (p,) in mem.execute("SELECT pagina FROM letture_turno WHERE turno_id = ? ORDER BY rowid", (r[0],))])
            for r in righe]


def ricorda(mem, domanda, esistenti):
    """Pagine lette per domande simili: [(pagina, domanda simile)], solo pagine ancora presenti nel grafo."""
    q = radici(domanda)
    simili = []
    for id_, testo in mem.execute("SELECT id, testo FROM domande"):
        r = radici(testo)
        comuni = len(q & r)
        dice = 2 * comuni / (len(q) + len(r)) if q and r else 0
        if comuni >= 2 and dice >= SOGLIA:
            simili.append((dice, id_, testo))
    pagine = {}
    for dice, id_, testo in sorted(simili, reverse=True):
        for pagina, volte in mem.execute("SELECT pagina, volte FROM pagine_lette WHERE domanda_id = ? "
                                         "ORDER BY volte DESC, rowid", (id_,)):
            if pagina in esistenti and pagina not in pagine:
                pagine[pagina] = (dice * volte, testo)
    ordine = sorted(pagine.items(), key=lambda kv: kv[1][0], reverse=True)[:MAX_PAGINE]
    return [(pagina, testo) for pagina, (_, testo) in ordine]


def dimentica(mem, testo):
    """Toglie dall'archivio una domanda e le sue pagine lette; corrispondenza esatta, o unica per sottostringa
    (senza maiuscole). Restituisce (testo rimosso, [altre candidate]): testo None se non trovata o ambigua."""
    righe = mem.execute("SELECT id, testo FROM domande").fetchall()
    esatte = [r for r in righe if r[1] == testo]
    trovate = esatte or [r for r in righe if testo.lower() in r[1].lower()]
    if len(trovate) != 1:
        return None, [t for _, t in trovate]
    id_, trovato = trovate[0]
    mem.execute("DELETE FROM pagine_lette WHERE domanda_id = ?", (id_,))
    mem.execute("DELETE FROM domande WHERE id = ?", (id_,))
    mem.commit()
    return trovato, []


def main():
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("domanda", nargs="?")
    ap.add_argument("--dimentica", metavar="TESTO",
                    help="toglie una domanda e le sue pagine lette (testo esatto, o una sottostringa unica)")
    ap.add_argument("--turni", nargs="?", type=int, const=10, metavar="N",
                    help="ultimi N turni del log (10 se omesso): semi, pagine iniettate e lette")
    ap.add_argument("--db", type=Path, default=qui / "memoria.sqlite")
    ap.add_argument("--grafo", type=Path, default=qui / "graph.sqlite")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    mem = apri(args.db)

    if args.turni is not None:
        for id_, sessione, quando, testo, semi, iniettate, routing, lette in turni_recenti(mem, args.turni):
            print(f"#{id_} {quando} [{sessione or '-'}]" + (f" → {routing}" if routing else "") + f" «{testo}»")
            print("   semi: " + (", ".join(f"{s['pagina']} ({s['origine']})" for s in semi) or "-"))
            print("   iniettate: " + (", ".join(iniettate) or "-"))
            print("   lette: " + (", ".join(lette) or "-"))
            inutili = [p for p in iniettate if p not in lette]
            mancate = [p for p in lette if p not in iniettate]
            if inutili:  # senza nessuna lettura sono tutte: il modello ha risposto dal solo contesto
                print("   iniettata non letta: " + ", ".join(inutili))
            if mancate:
                print("   letta non iniettata: " + ", ".join(mancate))
        return
    if args.dimentica:
        trovato, candidate = dimentica(mem, args.dimentica)
        if trovato:
            print(f"tolta «{trovato}»")
            return
        sys.exit(f"nessuna domanda corrisponde a «{args.dimentica}»" if not candidate else
                 f"«{args.dimentica}» è ambigua, corrisponde a: " + "; ".join(f"«{t}»" for t in candidate))
    if args.domanda:
        grafo = connect_graph(args.grafo)
        esistenti = {id_ for (id_,) in grafo.execute("SELECT id FROM entities")}
        grafo.close()
        for pagina, testo in ricorda(mem, args.domanda, esistenti):
            print(f"- {pagina}  (da «{testo}»)")
        return
    for id_, testo, volte, ultima in mem.execute(
            "SELECT id, testo, volte, ultima FROM domande ORDER BY volte DESC, ultima DESC"):
        lette = ", ".join(f"{p} ×{v}" for p, v in mem.execute(
            "SELECT pagina, volte FROM pagine_lette WHERE domanda_id = ? ORDER BY volte DESC, rowid", (id_,)))
        print(f"{volte}× «{testo}» (ultima {ultima})\n   → {lette}")


if __name__ == "__main__":
    main()

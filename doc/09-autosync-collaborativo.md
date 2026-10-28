# 9 — Autosync collaborativo (pull prima, commit e push dopo ogni skill)

Stato: implementato sul branch `codex/dashboard-foundations` (installer, `pre`/`post`, skill, rotte di consenso); il pulsante nel pannello della dashboard è un passo successivo, collaudo su un repository GitHub reale non ancora svolto. Piano: fasi 1–3 della roadmap di collaborazione. Questo documento è la decisione di progetto (ADR) che supera, **solo per i vault che lo attivano**, il principio "nessuna applicazione automatica" dei passi [6](06-pubblicazione-github.md) e [7](07-ricezione-automatica.md).

## Decisione

| # | Decisione |
| --- | --- |
| D1 | L'autosync è **opt-in per vault**. Il consenso si dà una volta, all'installazione (`installa.py --collabora`) o dalla dashboard, ed è registrato in `.teseo/local/sync.sqlite` (`automatic`, `automatic_consent_at`). Senza consenso nulla cambia rispetto al passo 6 |
| D2 | Un conflitto sulla **stessa nota** ferma l'autosync. Si risolve dalla dashboard (`sync/resolve`), con revisione umana. Nessuna unione semantica automatica |
| D3 | `log.md` e `index.md` si uniscono automaticamente con `git merge-file --union`, perché ogni skill vi aggiunge righe. Qualunque altro file in conflitto blocca |
| D4 | Le fonti binarie in `raw/` restano locali (`.git/info/exclude`) e vengono segnalate. Si condividono note, schema, indice, log, eventi e fonti testuali |
| D5 | `--collabora` è ammesso anche su un vault già in uso, previa conferma esplicita |
| D6 | Il repository remoto si crea solo con `--crea-remote` (richiede `gh` autenticato) e dopo conferma. Altrimenti si fornisce l'URL di un repository già esistente |

## Garanzie conservate

L'autosync usa gli stessi percorsi del publisher esplicito. Non introduce scorciatoie.

- Allowlist dei percorsi e scansione dei segreti (`git_sync._allowed`).
- Checkpoint con soli file attribuiti, verificati per hash prima e dopo il commit.
- Integrazione in un'area isolata; mai un merge nel vault vivo. L'adozione locale è solo fast-forward.
- Raw ed eventi condivisi immutabili.
- Git non interattivo: nessun prompt di credenziali, nessun hook, nessuna configurazione eseguibile.
- Audit della storia prima di ogni push, ora **incrementale** sui soli commit non ancora pubblicati (il tetto di 128 vale per i commit nuovi, non per la storia complessiva).

## Flusso

1. `python .graph/teseo_git.py pre --skill <ingest|lint|lacune> --agente <claude|codex|copilot>` all'inizio della skill.
   - Albero non pulito: si ferma e indica come pubblicare le modifiche a mano.
   - Fetch del branch condiviso; se il remoto è avanti, fast-forward, ricostruzione di grafo e proiezione.
   - Storie divergenti: si ferma e rimanda alla dashboard.
   - Rete o autenticazione assenti: prosegue offline e lo segnala.
   - Apre una **sessione** in `.teseo/local/autosync.sqlite`.
2. La skill lavora come oggi, fino a `build_graph.py --check` pulito e alla riga di log.
3. `python .graph/teseo_git.py post --skill … --agente …` alla fine.
   - Rilancia il controllo del grafo; calcola i file cambiati; crea il commit attribuito.
   - Il commit ha come autore la persona (identità Git locale) e i trailer `Teseo-Skill` e `Teseo-Agent`.
   - Integra con il remoto, valida, fa push, adotta in fast-forward.

Modifiche fatte a mano in Obsidian: `post --skill manuale`, senza `pre`.

## Codici di uscita

| Codice | Significato | Azione |
| --- | --- | --- |
| 0 | Eseguito, nulla da fare, oppure collaborazione non attiva | Proseguire |
| 2 | Bloccato: serve un'azione umana (conflitto, storie divergenti, albero sporco, grafo non valido) | Fermarsi e riportare il messaggio |
| 3 | In attesa di rete o autenticazione; il lavoro è conservato | Proseguire e riprendere con `teseo_git.py riprendi` |

Stati di una sessione: `open` → `published`, `noop`, `blocked`, `waiting`.

## Cosa non fa

- Non usa gli hook di Claude Code per Git: i timeout (10–15 s) sono inferiori a una singola operazione Git, e Codex e Copilot non hanno un evento di inizio/fine skill. Il punto di aggancio è la skill, che i tre client leggono dagli stessi file.
- Non pubblica in modalità PR: resta un percorso manuale dalla dashboard.
- Non riceve in background: il pull avviene solo in `pre`.
- Non stabilisce chi ha scritto cosa nel grafo; scrive i trailer che la fase successiva leggerà.
- Non garantisce l'esclusione di Obsidian durante `post`: hash e HEAD rilevano la scrittura concorrente e fermano la pubblicazione, senza impedirla.

## Regola di correlazione per `log.md` e `index.md`

La validazione dell'integrazione ([passo 6](06-pubblicazione-github.md), `sync_validation._scope`) considerava `log.md`, `index.md` e `Wiki reference.md` punti di contatto globali: qualunque pubblicazione concorrente in cui un lato li toccava richiedeva una decisione umana. Poiché ogni skill aggiunge una riga a `log.md`, due sessioni sovrapposte si sarebbero fermate sempre, e l'unione automatica (D3) non sarebbe servita.

La regola ora è: `log.md` e `index.md` non sono più globali **per un lato che aggiunge soltanto righe** (`log.md`: il contenuto base è un prefisso; `index.md`: nessuna riga della base è cancellata o riscritta). Se entrambi i lati sono additivi e toccano lo stesso file, l'unione non perde informazione e non c'è correlazione. Qualunque riscrittura o cancellazione, e ogni modifica a `Wiki reference.md`, restano soggette alla decisione umana. Il resto del gate (note nello stesso vicinato del grafo) è invariato: due persone che modificano note collegate, anche indirettamente, si fermano.

Quando una riscrittura fa fermare la pubblicazione, `merge-file --union` lascia nel candidato isolato sia la riga vecchia sia quella nuova (`# Log`, `- avvio riscritto`, `- avvio`, `- remoto`) e nulla va in remoto finché non c'è la decisione. La decisione pubblica il candidato così com'è: la riga vecchia resta nel remoto e va tolta con una modifica successiva. A proteggere dalle riscritture è `_scope`; il controllo in `_union_resolve` ferma solo le cancellazioni.

Limiti noti di `additive`, accettati perché la regola resta quella sopra:

- `log.md`: il confronto è un prefisso sui byte. Se la base non termina con un a capo e un lato accoda testo sulla stessa riga, il file risulta additivo pur essendo una riscrittura di quella riga. Le skill aggiungono sempre righe intere.
- `index.md`: il confronto conta le righe e ignora l'ordine, quindi un riordino puro risulta additivo.

## Comportamento verificato

- Sessione aperta e mai chiusa: un nuovo `pre` a vault pulito la marca `abandoned`; con modifiche non pubblicate si ferma (`autosync_unpublished`).
- Offline in `pre`: prosegue con un avviso. Offline in `post`: il commit resta locale (`waiting`, exit 3). Finché una pubblicazione attende la rete, `pre` e `post` successivi si fermano (exit 2) e la ripresa è `riprendi` a vault pulito: evita di lasciare note nuove sporche mentre il push precedente non è adottato.
- Il pull (`SyncService.sync_down`) è un fast-forward tramite candidato isolato; storie divergenti non vengono toccate.
- Le fonti binarie in `raw/` restano sul disco: il confronto fra i byte del vault e l'OID da pubblicare le ignora (`git_sync.is_local_only`).
- Il limite di 128 commit vale sui soli commit non ancora pubblicati.
- Prima verifica POSIX (Linux, Python 3.13): `tests/test_autosync.py` passa senza modifiche, con remoto bare locale. L'autosync non usa `ReplaceFileW` né l'apply manuale Windows; l'unica differenza di piattaforma è la riga di comando dei client (`shlex.join` fuori da Windows, `installa.py`, `codex_hook.py`).

## Limiti noti

- `capture_snapshot` legge in memoria tutto il perimetro dati, fonti binarie comprese, con tetto di 64 MiB (`snapshot_too_large`). Un vault con molte fonti pesanti in `raw/` blocca l'autosync finché il tetto non viene reso selettivo. Da affrontare prima di un uso con PDF di grandi dimensioni.
- Il controllo dell'integrazione è euristico e conservativo: il vicinato è l'intera componente connessa del grafo, quindi in una wiki molto collegata molte modifiche concorrenti richiedono una decisione.
- Nessuna esclusione di Obsidian durante `post`: hash e HEAD rilevano una scrittura concorrente e fermano la pubblicazione.
- Su POSIX resta non verificato il `cleanup_candidate` dei pack in sola lettura (descritto per Windows). L'apply manuale e la ricezione funzionano ora anche su POSIX ([documento 10](10-editor-grafo-e-autori.md)).
- `teseo_git.py avvisi` (un solo fetch, mai pull né scritture) è chiamato dagli hook `SessionStart` di Claude e Codex per segnalare «N aggiornamenti remoti».
- Le modifiche dalla dashboard (editor del grafo) pubblicano con `post --skill dashboard --agente umano` senza eseguire `.graph/build_graph.py` (`graph_check=False`): la sessione nasce con la pubblicazione, come per `manuale`.
- Collaudo con un repository GitHub reale, credenziali reali e client AI autenticati non svolto; i test usano un remoto bare locale.

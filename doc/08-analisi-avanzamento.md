# Analisi ECC e avanzamento

Branch di sviluppo: `codex/dashboard-foundations`, creato da `main` il 22 ottobre
2026. Nessun merge; i branch principali non vengono aggiornati. Ogni incremento
runtime verificato prevede commit e push separati su questo branch.
Destinazione autorizzata esplicitamente dall'utente:
`https://github.com/manuel-albanesee/Teseo.git`. Pubblicati con due push ordinari
distinti, in ordine: `01ba97e` (contratti) e `2e16787` (builder). Il branch locale
segue `origin/codex/dashboard-foundations`; nessun merge eseguito.

## Valutazione del piano

La sequenza dei sette passi separa correttamente kit e dati, autorità Markdown,
eventi condivisi e DB personali. I gate di recovery e gli editor non cooperanti
sono necessari: hash e watcher da soli non autorizzano apply automatici.

La prima consegna utile è il contratto puro, seguito dalla correzione del builder
esistente. Anticipiamo la sola protezione della pubblicazione del passo 1.3
rispetto al journal 1.2: corregge un difetto indipendente e verificabile, senza
introdurre nuove scritture delle note. Snapshot stabili, lock condiviso e lettori
a generazioni restano prerequisiti per attivare la dashboard e le automazioni.

| Passo | Valutazione / lavoro restante |
| --- | --- |
| 1 | Contratti, journal, lock, snapshot, generazioni e backup disponibili; apply protetto note e recovery multi-file ancora da realizzare |
| 2 | Bootstrap, API e UI di consultazione, distribuzione e rebuild coordinato disponibili; adozione legacy ed export diagnostica futuri |
| 3 | Parser/serializer (3.1), preview (3.2), form UI (3.3), apply manuale locale e recovery (3.4) disponibili; automatico disabilitato, mapping pagine/eventi al passo 5 |
| 4 | Probe e ricevuta da provare su ogni client; Stop non certifica il successo |
| 5 | Canonicalizzazione disponibile; schema eventi per tipo, DAG, proiezioni e migrazione ancora da sviluppare |
| 6 | Staging Git isolato e attribuzione precisa obbligatori prima del push dati |
| 7 | Apply automatico subordinato a recovery e gate Windows; rilevamento può precederlo |

## Incremento 1 — contratti puri

`kit/dashboard/contracts.py` definisce le versioni supportate v1 e la prima
versione del contratto kit `1.0.0`. Non è una dichiarazione di completamento della
dashboard. Manifest esplicito con UUID e allowlist selezionabile dei sei percorsi
condivisi previsti; campi opzionali sconosciuti conservati come dati inerti.
Le versioni kit accettano inizialmente solo `major.minor.patch` stabili.

`inspect_vault` restituisce `legacy_readonly`, `compatible` o `incompatible`
senza creare directory, migrare o autorizzare scritture. `compatible` indica solo
compatibilità dei formati, non validità semantica né capacità di apply.
La classificazione copre dati, grafo, DB personali, stato locale, script/config
client e percorsi sconosciuti; unknown non è condivisibile automaticamente.
Un raw contenente codice resta una fonte inerte, mai uno script da eseguire.

JSON canonico v1 con fixture byte: UTF-8, NFC, chiavi ordinate, LF finale,
interi sicuri, rifiuto di duplicati, BOM, float e surrogate. Il serializer non
sostituisce la validazione dello schema evento del passo 5. Percorsi portabili
e risoluzione dentro root includono collisioni case-insensitive e junction;
non costituiscono una protezione dalle race di scrittori esterni.

Distribuzione nel vault rinviata al packaging del passo 2: il modulo vive nel kit
e non viene copiato o attivato implicitamente dall'installatore corrente.

Verifica ECC `verification-loop`, adattata al progetto Python: unittest mirati,
suite esistente, `installa.py --prova`, compilazione Python e revisione diff.
Non esistono configurazioni di type checker, linter o coverage nel repository:
non attribuire risultati a strumenti non eseguiti.

Esito incremento 1: suite 44 test, 43 superati e 1 saltato (creazione symlink non
consentita su questo Windows); installazione `--prova` superata, compilazione e
controllo whitespace superati. I test filesystem sono stati ripetuti fuori dal
sandbox perché l'API Windows di risoluzione stretta dei percorsi viene negata
anche nelle cartelle scrivibili. Nessun controllo del runtime è stato indebolito.

## Incremento 2 — gate del builder legacy

`build_graph.py` separa `parse_snapshot`, `validate_snapshot`, `build_candidate`
e `publish_generation`. Parsing e controlli semantici precedono la creazione del
candidato. Temporanei unici per build, connessioni chiuse, controllo integrità
SQLite readonly e cleanup su errore. Sia CLI con/senza `--check` sia chiamata
dall'hook rifiutano il grafo invalido: il precedente resta disponibile; l'hook
usa il proprio fallback già esistente e dichiara il rebuild fallito.

Questo completa la protezione da pubblicazione invalida del passo 1.3, non il
passo 1 completo. `parse_snapshot` legge i dati in memoria, ma il chiamante deve
ancora fornire una copia stabile: non offre isolamento da editor concorrenti.
La pubblicazione conserva per compatibilità `.graph/graph.sqlite`: lettori Windows
possono impedire il replace, che fallisce conservando il DB precedente. Restano
da realizzare generazioni immutabili e migrazione dei lettori (1.4), journal,
lock, digest e verifica pre-apply (1.2). Il vecchio hook controlla ancora mtime.
Non vengono attivati dashboard, ingest/lint automatici o sincronizzazione dati.

Esito incremento 2: suite completa 55 test, 54 superati e lo stesso skip symlink;
dopo la revisione, suite mirata del builder rieseguita con tutti i 12 test
superati (incluso il nuovo caso wiki mancante e frontmatter senza chiusura).
`installa.py --prova`, compilazione Python, controllo whitespace e revisione diff
superati. Nessuna nuova dipendenza. Nessun risultato di coverage o type checking
è dichiarato. `main` resta sul commit iniziale `19e5288`; non esiste un branch
locale `master` e nessun branch principale è stato modificato.

## Incremento 3 — journal, lock e snapshot (passo 1.2)

`kit/dashboard/storage.py` introduce fondazioni non ancora attivate nel vault
dall'installatore. Richiede manifest compatibile: nessuna adozione implicita dei
vault legacy. Non aggiunge dipendenze. Scelta lock: standard library `msvcrt` su
Windows, `fcntl` su POSIX. Test reali eseguiti su Windows; POSIX non verificato
in questa sessione.

`VaultLock` usa un lock esclusivo del kernel con timeout, senza rimozione del file
in base al PID; il crash del processo libera il lock. Serializza i chiamanti che
adottano questa API. Timeout produce `vault_busy`; attesa e coda dei job saranno
integrate nel coordinator del passo 4. Hook e CLI legacy non usano ancora questo
lock: non si dichiara esclusione globale degli scrittori esistenti.

`capture_snapshot` legge due volte tutto il perimetro dati e confronta hash e
percorsi. Include manifest, schema, note, index/log, raw ed eventi; esclude DB
personali, script/client e stato locale. Censisce anche dati non selezionati per
export. Rifiuta file inattesi nel perimetro, collisioni, path traversal, symlink
e junction (anche se interni, scelta conservativa). Limite predefinito 64 MiB per
scansione; le copie sono in memoria, non adatte ancora a raw molto grandi.
Timestamp invariati non nascondono cambiamenti. `validate_raw_unchanged` permette
aggiunte ma blocca modifica, eliminazione e rinomina di fonti preesistenti.

`Journal` richiede il lock per ogni accesso. SQLite con `synchronous=FULL`
conserva UUID, vault, tipo, revisione Git base fornita dal chiamante (null senza
Git), digest contenuto/schema, letture, hash prima/dopo, stato, errore e checkpoint.
Chiave idempotente uguale e stesso payload restituiscono il record esistente;
payload diverso produce conflitto. Copie base/candidato sono scritte e fsyncate
prima di registrare il relativo checkpoint. `prepare` controlla base live e raw,
ricontrolla la base dopo la copia e lascia intatte le note. La validazione di
dominio (YAML, grafo, eventi) resta responsabilità della pipeline chiamante:
`prepared` qui certifica le sole precondizioni dello storage.

Lo stato è in `.teseo/local/`, protetto da `.gitignore` con sola regola `*`;
configurazioni che reincludono file richiedono correzione esplicita. Non vengono
rimossi eventuali file già tracked in installazioni precedenti. Snapshot e DB
personali non sono esportati da questo modulo. Nessuna retention automatica:
le copie richiedono spazio e rimangono disponibili per diagnosi.

Recovery iniziale conservativa: `require_recovery` marca le operazioni interrotte,
preserva hash e checkpoint e le ripropone ai riavvii successivi; `orphan_snapshots`
segnala copie senza record/checkpoint dopo guasti. Non ripristina e non cancella
file. Apply e transizioni `applying`/`succeeded` sono bloccati finché non sarà
implementata la protezione di scrittura. Non è una transazione globale tra SQLite
e filesystem, né una promessa di resistenza a ogni guasto elettrico.

Prossimo incremento: passo 1.4, generazioni immutabili, migrazione dei lettori e
backup SQLite consistenti; integrare questi strumenti nel percorso reale prima
di attivare il servizio. Watcher, scheduling, completamento automatico della
recovery e protezione da editor non cooperanti restano futuri. Le scansioni hash
rilevano modifiche, ma non eliminano la finestra tra ultimo controllo e apply.

Verifica ECC `verification-loop`: suite completa 79 test (78 superati, uno skip
symlink già noto), poi suite storage rieseguita con 24 test tutti superati dopo
l'aggiunta del controllo timeout finiti. Inclusi processi concorrenti, attesa e
kill del proprietario, crash con `os._exit`, scrittura esterna durante copia,
immutabilità raw, copia corrotta, fallimento di checkpoint e junction Windows.
`python installa.py --prova`, compilazione Python, controllo whitespace e revisione
diff superati. Nessuna dipendenza aggiunta; type checker, lint dedicato e coverage
non configurati e non dichiarati eseguiti.

## Incremento 4 — generazioni e backup consistenti (passo 1.4)

Il 23 ottobre 2026 `graph_service.py` introduce il rebuild derivato su vault con
manifest v1 compatibile. Non crea manifest e non adotta implicitamente i vault
legacy. Usa `VaultLock`, acquisisce uno snapshot e costruisce da una copia dei
byte acquisiti. Un confronto contenuti precede il cambio di generazione: una
modifica esterna rilevata conserva il manifest precedente. Non risolve la race
successiva all'ultimo hash con editor non cooperanti, né applica note o eventi.

Il DB è `.teseo/local/graphs/<generation>.sqlite`; l'identificatore deriva dal
digest contenuti e dalla versione del builder, inizialmente 1. Chi cambia il
formato o la semantica del builder deve incrementare `BUILDER_VERSION`. Il piccolo
manifest atomico `.teseo/local/graph-current.json` contiene revisione contenuti,
generazione e SHA-256 del DB. Il candidato è chiuso, validato e fsyncato prima
della promozione. I file già pubblicati non vengono sostituiti né cancellati.
Un no-op con hash DB valido non cambia manifest e non avvia un nuovo build.

Recovery del solo grafo: un arresto prima del cambio manifest lascia corrente
la vecchia generazione. Un DB orfano è ricostruito e confrontato byte per byte
prima di riutilizzarlo; una differenza blocca la promozione. Il fallimento del
replace del manifest conserva la vista precedente. Dopo il cambio, il manifest
identifica la vista completa. Non viene dichiarata recovery automatica delle
operazioni mutanti del journal, né riparazione silenziosa di manifest corrotti.
File orfani e vecchie generazioni restano conservati; pulizia e retention future.

`graph_db.py` risolve il manifest una volta per connessione, apre SQLite readonly
e associa `content_revision`, `graph_generation` e `graph_path`. I lettori già
aperti terminano sulla vecchia generazione, inclusi su Windows. Recall, domande,
memoria, sintesi, misura, banco, candidati e modello/recall hook usano questa
apertura comune. Recall JSON e contesto dell'hook dichiarano revisione e
generazione. Banco e misura passano ai sottoprocessi il percorso già fissato.
I report legacy che leggono anche note vive non sono snapshot globali della UI;
la futura API readonly dovrà servire dati della stessa revisione.

CLI builder e recall hook attivano il nuovo percorso solo dove esiste il manifest
del progetto (o una generazione già attiva, che non può tornare alle scritture
legacy se il manifest progetto scompare). Gli hook confrontano contenuti per i
vault compatibili, mentre il comportamento legacy basato su mtime resta
compatibile. Gli export `--out` diversi dal percorso standard restano espliciti
build legacy. Gli eventi condivisi bloccano il rebuild con errore strutturato
finché non sarà disponibile il validatore del passo 5.

L'installatore ora distribuisce i moduli in `.graph/dashboard/` e `graph_db.py`,
preservando le personalizzazioni e i backup con la policy esistente
`--aggiorna`. `--solo-integrazione` non aggiorna il runtime condiviso; per passare
alle nuove capacità occorre aggiornamento completo del kit. L'installazione non
crea manifest progetto e non cambia il formato dei DB personali.

`python .graph/backup_personal.py` su vault compatibile esegue l'online backup
SQLite dei DB personali esistenti, incluso WAL committato. Non copia i file
SQLite a mano, non crea sorgenti mancanti e non rimuove/modifica la storia
personale. Ogni destinazione UUID in `.teseo/local/backups/` ha un `backup.json`
solo dopo integrità e hash verificati; una directory senza marker è incompleta
e conservata per diagnosi. Timeout massimo configurabile via API, default 30 s
per DB. I due DB sono backup individualmente consistenti, non una transazione
congiunta fra memoria e domande. Nessun restore o export automatico.

Prossimo passo: bootstrap servizio e attach readonly (2.1), senza attivare
scritture delle note o sincronizzazione Git. Il requisito di apply protetto e la
recovery multi-file rimangono bloccanti per i passi mutanti successivi.

Verifica ECC `verification-loop`: suite completa 91 test (90 superati, uno skip
symlink già noto); dopo l'aggiunta del crash reale, suite generazioni di 12 test
tutti superati. Verificati lettore SQLite aperto su Windows, no-op, errori di
validazione/manifest, scrittura esterna, arresto `os._exit` e ripresa, lettori CLI
installati, hook, backup WAL e backup incompleto. Prova installatore, compilazione
Python e revisione diff superate. Nessuna nuova dipendenza. Non dichiarati
coverage, lint dedicato o type checking non configurati.

## Incremento 5 — bootstrap servizio e attach readonly (passo 2.1)

`server.py`, `readonly.py` e `bootstrap_ui.py` introducono un servizio locale
con pagina di collegamento e registro effimero dei vault. Scelta iniziale:
`http.server` della standard library, vincolato a `127.0.0.1`, porta dinamica
predefinita. Nessuna dipendenza server/UI aggiunta. Il servizio è per l'uso locale
di questo bootstrap; nessuna esposizione di rete o hosting pubblico.

Dal kit: `python -m kit.dashboard.server --vault "C:/Obsidian/MioVault"`.
Da un vault aggiornato: `python .graph/teseo_dashboard.py --vault "C:/Obsidian/MioVault"`.
`--vault` è ripetibile; senza argomento si sceglie la cartella nel form.
`--no-browser` stampa solo il link; `--port` consente una porta esplicita.
Il launcher è distribuito automaticamente dal percorso installer già esistente.
Un aggiornamento completo del kit conserva personalizzazioni e backup; nessuna
adozione implicita o scrittura del manifest progetto.

Il servizio genera un token casuale per processo e apre il browser con il token
nel frammento URL, che non è inviato nelle richieste HTTP. La pagina lo conserva
solo in memoria e rimuove subito il frammento dall'indirizzo. Niente cookie,
localStorage o sessionStorage; per ricaricare/riaprire la sessione si usa il link
completo del launcher. La chiusura del tab lascia il processo attivo; Ctrl+C lo
arresta e invalida la sessione. Token e header non sono salvati su disco o nei log
HTTP. Il link stampato dal launcher resta una credenziale per quel processo.

| Endpoint disponibile | Comportamento |
| --- | --- |
| `GET /` | Pagina statica, senza dati dei vault o token inseriti dal server |
| `POST /api/v1/session` | Token di sessione obbligatorio; restituisce il CSRF |
| `POST /api/v1/vaults/attach` | Sessione + Origin + CSRF; valida il solo campo `path` |
| `GET /api/v1/vaults` | Lista dei vault collegati nella sessione autenticata |
| `GET /api/v1/vaults/{uuid}/status` | Ricontrolla struttura, identità e compatibilità |

Tutte le API richiedono `X-Teseo-Session`; le POST richiedono Origin esatto,
JSON e `X-Teseo-CSRF` (escluso il bootstrap della sessione, protetto dal token).
Host esatto, CORS chiuso, CSP con nonce, cache disabilitata, errori senza
traceback, massimo 16 KiB per richiesta, 32 vault, 8 connessioni servite insieme,
timeout socket 5 s e limite globale 120 richieste/minuto. Nessun endpoint shell,
SQL, file arbitrari, rebuild o sync. HTML della pagina fisso; i dati dinamici
vengono inseriti solo con `textContent`. Il codice ricevuto nei vault non viene
importato o eseguito dal servizio.

Attach accetta cartelle locali assolute, rifiuta URL/UNC e segnala errori
strutturati per root errata o versioni incompatibili. `mode` è sempre `readonly`;
`compatibility` distingue `compatible` da `legacy_readonly`. Il vault compatibile
usa il proprio UUID; il legacy riceve un UUID derivato dal percorso canonico.
Due clone con lo stesso UUID non sono collegati contemporaneamente nello stesso
processo. `content_revision` e `graph_generation` sono null: l'attach non legge
il grafo e non promette ancora una revisione dei contenuti. Le capacità grafo,
rebuild, scrittura e sync sono esplicitamente disabilitate.

Decisione di scope: registro solo in memoria per evitare qualsiasi scrittura
nei vault, inclusi i legacy. Persistenza del registro rinviata al 2.4 e da
progettare senza trasformare l'attach in una migrazione implicita. Nessun DB
personale viene aperto, nessun file locale creato da attach o GET. La UI del 2.1
mostra solo collegamento e compatibilità; grafo/ontologia/diagnostica sono il
prossimo incremento 2.2, con revisione dichiarata e letture coerenti.

Verifiche ECC `verification-loop` e `security-review`: suite completa 107 test,
106 superati e uno skip symlink già noto. I 15 test del bootstrap includono HTTP
reale su loopback, sessioni, Host/Origin/CSRF, input/size limit, CORS, rate limit,
formato futuro, conflitto UUID tra clone, junction esterna, hash invariati dei
file e nessuna esecuzione di script, launcher installato e arresto KeyboardInterrupt.
Compilazione Python, revisione diff e `installa.py --prova` superati. Nessuna
dipendenza aggiunta; coverage/type checker/lint dedicato non configurati.

Smoke browser con Chrome DevTools ECC: pagina e sessione inizializzate, frammento
URL rimosso, errore leggibile per percorso assente e attach di vault legacy
riuscito. L'unico errore di rete osservato nello smoke corrisponde al 422 atteso
del percorso assente. Servizio di prova e schede creati per il test arrestati e
chiusi, fixture rimossa. Per rendere il listener raggiungibile dal browser è
stato necessario eseguire il processo fuori dal sandbox Windows, sempre su
loopback. Nessun vault reale è stato collegato o modificato per lo smoke.

## Incremento 6 — API di consultazione coerenti (passo 2.2)

`read_api.py` implementa GET status, graph, nodes, ontology e diagnostics sul
servizio autenticato esistente. Nessuna GET ricostruisce, avvia modelli/Git o
modifica note, raw, schema e DB personali. L'attach rimane una validazione leggera:
capacità effettiva del grafo e metadati sono restituiti da `/status`.

`BUILDER_VERSION` passa a 2. Ogni generazione incorpora `graph_documents` con
note top-level, Wiki reference, index e log dello stesso snapshot del grafo.
Raw, eventi e DB personali non sono copiati in questa tabella. I documenti
versionati eliminano la lettura di note/schema vivi da parte delle API: un
vault modificato dopo il build viene segnalato stale, ma testo e ontologia
restano quelli della revisione pubblicata. I lettori CLI precedenti restano
compatibili con le tabelle del grafo. Versione 1 e grafi legacy non forniscono
questo contratto: `graph_upgrade_required` / `graph_unavailable`, senza migrazione
implicita; per vault già compatibili, usare esplicitamente il builder aggiornato.

Il parser del builder ora offre `leggi_testo` e `parse_documents`, riutilizzati
dalla diagnostica in memoria senza temporanei né esecuzione di script del vault
collegato. I moduli del parser sono quelli del runtime fidato del servizio e
sono caricati solo quando necessari; bootstrap, help e attach legacy non
importano builder dal vault. Il codice di un percorso registrato non viene
aggiunto al percorso di import del servizio.

Le API risolvono la generazione una volta per connessione, verificano SHA-256
e metadati, poi usano SQLite readonly/immutable. Ogni risposta dati dichiara
`content_revision` e `graph_generation`. Le richieste successive possono
inviare `generation=<id>`; se la generazione corrente è cambiata ricevono
`409 revision_changed`. Non è un pin globale automatico per tutte le richieste
del processo: il client deve riportare l'ID della propria lettura. Una richiesta
già aperta può terminare sulla precedente generazione, dichiarandola.

| Endpoint | Risultato e limiti iniziali |
| --- | --- |
| `/status` | Capacità grafo, revisione pubblicata e live, stale, problemi; busy è null con busy_known=false finché non esiste il registry job |
| `/graph` | Nodi e archi ordinati; limit 1–200 per ciascuna lista, default 100; filtri type/relation e cursore |
| `/nodes/{node_id}` | ID esatto URL-encoded, proprietà normalizzate JSON, testo escaped, alias/fonti/archi con flag di troncamento oltre 200 |
| `/ontology` | Tipi, relazioni dirette con significato/esempio, testo e sezioni opache escaped; catalogo dichiarato distinto dai tipi osservati/vincoli |
| `/diagnostics` | Errori di parsing/semantica sulla generazione, problemi del grafo e stale; ogni problema include codice, severità, percorso e revisione |

Il filtro `type` seleziona i nodi e il sottografo indotto su entrambi gli estremi;
`relation` filtra gli archi, lasciando i nodi selezionati. Nodi e archi hanno
progressione indipendente nello stesso cursore, per conservare anche archi tra
nodi restituiti in pagine diverse. Cursori firmati HMAC per sessione, legati a
vault, generazione, filtri e page size: alterazioni e riuso incompatibile sono
rifiutati. Nessuna interpolazione di valori client nelle query SQL. Gli ID sono
opachi ed esatti, non percorsi filesystem; traversal e separatori sono rifiutati.

Risposte GET con ETag e supporto a If-None-Match esatto (304 senza corpo).
Rimane `Cache-Control: no-store`: i client possono fare richieste condizionali
esplicite, ma il servizio non abilita cache persistenti dei contenuti privati.
Le risposte di errore non promettono una revisione dati e riportano campi null.
Per un grafo indisponibile la diagnostica resta leggibile con revisione null.

Limiti: DB massimo 512 MiB e query SQL limitate a 5 s; documento singolo 2 MiB;
analisi semantica completa fino a 8 MiB / 2000 documenti, altrimenti avviso
`diagnostics_limited`; massimo 200 problemi con flag truncated. Lo stato live
usa lo scanner da 64 MiB e può dichiarare revisione live non disponibile. La
diagnostica non certifica note vive non pubblicate né assenza di contraddizioni
semantiche del dominio. I tipi inferiti dall'osservazione non diventano uno
schema canonico e nessun documento è riscritto. Testo in `escaped_markdown`:
nessun HTML ricevuto viene eseguito dal servizio.

Prossimo punto: UI home, filtri, dettaglio e gestione stale/errori (2.3).
Rebuild via API, registro persistente e coordinator mutanti rimangono futuri.

Verifiche ECC: suite completa 121 test, 120 superati e uno skip symlink già noto.
I 14 test delle query HTTP coprono stessa revisione sui cinque endpoint,
paginazione senza duplicati, filtri e SQL injection, cursor tamper, cambio
generazione/409, ETag/304, note e schema modificati senza rebuild, Unicode e
traversal, HTML escaped, ontologia e diagnostica parsing/semantica, hash DB
corrotto, grafo precedente/legacy e assenza di modifiche ai file o ai DB
personali. Superati anche gate del builder, regressioni bootstrap e launcher,
compilazione Python, revisione diff e `installa.py --prova`. Nessuna nuova
dipendenza; coverage, type checker e lint dedicato non configurati né dichiarati.


## Incremento 7 — UI di consultazione (passo 2.3)

Workbench statico servito dallo stesso processo: selezione/attach vault, revisioni,
grafo diretto con lista equivalente, filtri per tipo/relazione, ricerca nei soli
nodi caricati, dettaglio con proprietà/alias/fonti/testo, ontologia e diagnostica.
Asset suddivisi in bootstrap_ui.py, ui_style.py e ui_script.py, copiati dal meccanismo
esistente dell'installatore; nessuna nuova dipendenza o risorsa remota.

Pin generazione per ogni richiesta dati, epoch della vista e contatori richiesta
separati per grafo e dettaglio impediscono a risposte tardive di contaminare la
selezione corrente. Paginazione esplicita da 50 nodi/archi; ricerca e conteggi
etichettati come dati caricati. Disegno limitato a 12 nodi/80 archi tra questi,
con etichette complete e direzione nelle liste. Perdita connessione, assenza grafo,
risultati vuoti, dati parziali, stale e 409 hanno messaggi leggibili e retry esplicito.
Nessun rebuild automatico, scrittura nei vault o storage persistente nel browser.

Tutti i dati inseriti via textContent; il testo escaped delle API viene decodificato
una sola volta con tre entità fisse e mostrato in pre, senza interpretare HTML,
link o immagini. Il nonce CSP e la protezione della sessione/CSRF restano attivi.
Selezione nodo sposta focus al dettaglio; controlli etichettati, focus visibile,
lista equivalente e layout mobile impilato con grafo a scorrimento confinato.
Il token resta in memoria e il link launcher va riaperto dopo reload della scheda.

ECC verification-loop e frontend-design-direction: 121 test Python, 120 pass e
uno skip Windows già noto; installer --prova superato. Compilazione Python,
sintassi JS, controllo diff e scansione sink/storage client superati. Nessun
coverage/type checker/linter dedicato configurato. Dopo gli ultimi adeguamenti
UI rieseguite le 15 regressioni HTTP/packaging del bootstrap.

Smoke Chrome DevTools ECC: 20 controlli riproducibili nello script
`tests/dashboard_ui_smoke.js`, fixture sintetica da `tests/dashboard_ui_fixture.py`.
Coperti paginazione completa di 57 nodi senza duplicati, filtri, vuoti, HTML ostile,
fonti e direzioni, race dettaglio e refresh, offline simulato, caricamento sospeso,
grafo assente simulato, pin nelle richieste e assenza chiamate mutanti. Gli hash
di tutti i file fixture sono rimasti identici prima/dopo lo smoke. Verificati anche
stale reale dopo modifica nota, rebuild esplicito esterno e 409 reale mantenendo
50 nodi precedenti; refresh successivo legge il nuovo testo. Tastiera Enter/Tab,
focus e contenuti lunghi verificati su mobile; scheda separata senza sessione
mostra blocco e indicazione del link launcher. Nessun vault reale coinvolto.

[Contratto e report ECC](evidence/step-2-3/report.json), con screenshot a viewport
misurati 1440x900 e 390x844. Checker della skill superato; evidenze solo locali.
Non è una certificazione screen reader/cross-browser né una suite UI in CI.
L'unico errore console nell'ultima sessione browser è il 409 atteso della prova
reale di cambio generazione. Servizio e fixture di prova rimossi a fine verifica.

Prossimo incremento: distribuzione completa, arresto pulito e rebuild coordinato
via API/UI (2.4), prima di procedere all'editor ontologia del passo 3.

## Incremento 8 — Distribuzione e rebuild coordinato (passo 2.4)

Installer con opzione esplicita --dashboard su cartella vuota: manifest v1 con
UUID nuovo, generazioni immutabili, launcher Python disponibile. Un vault già
compatibile conserva il proprio manifest. Un legacy non vuoto è rifiutato prima
di modificare file, anche con --aggiorna; l'installazione ordinaria resta legacy.
Aggiornamento completo a servizio fermo con backup dei moduli in .graph_backup,
timestamp a microsecondi per non sovrascrivere backup ravvicinati. Note, raw,
manifest esistenti e DB personali preservati. Python minimo dichiarato 3.10,
coerente con le annotazioni già presenti nel runtime; CLI/launcher danno errore
leggibile prima dell'uso su versioni precedenti.

RebuildCoordinator usa il lock kernel comune e il journal esistente. POST rebuild
accetta idempotency_key ed expected_content_revision; 202 con operation_id,
GET operations readonly espone stato, errore e checkpoint. Stessa chiave/payload
recupera il risultato anche dopo riavvio, conflitto 409 per payload diverso.
Un job per vault, quattro vault attivi per processo, cache limitata a 256 record
che non espelle job attivi. Altre richieste ricevono busy/limite esplicito, senza
coda illimitata. Snapshot/digest controllati prima del build e prima della
pubblicazione. Errori parsing/semantica sono strutturati, dettagli limitati;
essun modello/Git/ingest o apply di note viene avviato.

Journal.complete_rebuild conclude soltanto job derivati corrispondenti alla
base; apply/succeeded delle note resta bloccato. Snapshot, hash e checkpoint
persistono in .teseo/local ignorato da Git. Record non gestiti dalla sessione
sono segnalati come da verificare, senza replay automatico; recovery sotto lock
alla successiva POST riguarda solo rebuild. Crash tra marker e checkpoint può
richiedere verifica di un grafo già valido; nessuna cancellazione o rollback
implicito. Snapshot e generazioni restano conservati; retention/GC futuri.

Builder accetta il lock già detenuto dal coordinator e verifica annullamento
tra le fasi e prima del marker; controlla metadati e link anche nel ramo no-op.
Il no-op non riscrive marker/generazione. UI con Ricostruisci grafo e polling
limitato al job visibile, vecchi dati leggibili, errori specifici e refresh
esplicito. Retry dopo perdita della risposta riusa la stessa chiave e dichiara
esito incerto; terminali mostrano risultato/istruzione successiva. Busy è noto
solo per i job di questo processo (busy_scope=service), non prova quiete di
editor o altri servizi. Nessuna promessa di esclusione atomica degli editor.

POST shutdown protetta da sessione/Origin/CSRF ferma listener e nuove submission;
close attende thread HTTP e worker non daemon. Ctrl+C usa lo stesso close;
un marker già in pubblicazione può completarsi. UI distingue richiesta di
arresto da uscita effettiva del processo. Le POST rifiutate consumano solo
body piccoli con lunghezza non ambigua, per evitare reset TCP Windows che
nascondevano il JSON d'errore; framing ambiguo/grande resta rifiutato.

Registro opzionale scelto con --registry, directory esistente; nessuna scrittura
implicita nell'attach. Atomic replace, limite 32 vault/64 KiB, lock kernel di
sessione, solo path/UUID e nessun token. Restore salta cartelle/identità non più
compatibili con avviso; formato malformato blocca senza overwrite. Un ricollegamento
esplicito dopo cambio identità sostituisce il binding precedente. Errori di
salvataggio ripristinano registro in memoria e file precedente. Scelta consigliata:
.teseo/local/dashboard-vaults.json di un vault host compatibile, ignorata da Git.

Verifiche ECC verification-loop, security-review e frontend-design-direction:
suite completa 136 test, 135 pass e uno skip symlink Windows noto. Dopo gli
ultimi controlli no-op/cache/HTTP, 93 regressioni dashboard: 92 pass e stesso
skip; sei test distribuzione/registro nuovamente superati dopo gestione del
cambio UUID. Compilazione Python, sintassi JS, revisione diff e controlli sink/
storage client superati. Coverage/type checker/linter dedicati non configurati.
Superati installa.py --prova e --prova --dashboard; nuovo runtime e upgrade con
backup provati in cartelle sacrificabili. Test job coprono CSRF/Origin, replay
persistente e conflitto, worker attivo/GET precedente, cache piena, POST shutdown
con build in corso, annullamento, nota modificata esternamente, parsing/semantica,
legacy, checkpoint interrotto senza replay, hash invariati e nessuna esecuzione
di script del vault collegato. Test no-op include metadati corrotti con hash
coerente e junction interna; fixture SQLite chiusa prima di rinominare su Windows.

Smoke Chrome DevTools ECC sul launcher effettivamente installato: 15 osservazioni
nel [registro browser](evidence/step-2-4/browser-checks.json). Grafo assente e rebuild
reale, risposta trattenuta, tastiera Enter, stale reale, parsing invalido con 10
nodi precedenti conservati, retry della stessa richiesta dopo perdita risposta,
legacy readonly, restore di due vault senza --vault e due arresti UI con exit 0.
Hash di note, raw, schema, manifest e DB personali identici alla baseline dopo
restore della sola nota sintetica modificata dalla prova. Screenshot misurati
1440x900 e 390x844 nel [report ECC](evidence/step-2-4/report.json); checker della
skill superato. Non è audit screen reader/cross-browser o suite browser in CI.
Solo fixture sintetiche, rimosse e servizi/schede di prova chiusi a fine lavoro.

Prossimo punto: 3.1, parser/serializer dell'ontologia con preservazione byte delle
sezioni non toccate, catalogo tipi e validazione; apply e migrazioni restano futuri.

## Incremento 9 — Parser e catalogo ontologia (passo 3.1)

`kit/graph/ontology.py` è condiviso da builder, API readonly e diagnostica,
distribuito anche nel runtime `.graph`. Modello immutabile con digest SHA-256,
span in byte UTF-8, catalogo tipi opzionale, relazioni orientate e intervalli
opachi. No-op identico ai byte originali, inclusi BOM, CRLF/LF/CR, Unicode e
assenza di newline finale. Le modifiche sostituiscono solo le tabelle interessate;
fonti, introduzioni, commenti e sezioni personalizzate restano intatti.

Grammatica conservativa documentata nel [passo 3](03-editor-ontologia.md): h2
canonici, tabella tipi a due colonne, relazioni legacy a tre o cinque colonne,
escape pipe/backslash, limiti 2 MiB/2048 righe. Documenti ambigui, titoli duplicati,
commenti nelle tabelle e formati non riconosciuti restano manuali; no-op permesso,
riscrittura bloccata. Fence, commenti, codice indentato e blocchi HTML riconosciuti
sono dati inerti. La scansione dei confini delle sezioni è lineare nei titoli.

`propose_type_catalog` produce soltanto una proposta deterministica con digest
base e conferma richiesta. Unisce convenzioni YAML univoche, tipi osservati e
vincoli, inserendo il catalogo prima della tabella relazioni senza alterare alcun
byte preesistente. Nessuna lettura/scrittura filesystem nel modulo; nessuna
adozione automatica, modifica del template o nuovo vocabolario nel manifest.
Preview HTTP, scelta dei cambiamenti e applicazione restano ai passi successivi.

Validazione di nomi NFC, duplicati case-insensitive, proprietà/archi riservati,
tipi conosciuti, vincoli e direzione. Il builder con catalogo esplicito rifiuta
anche pagine con tipo mancante/sconosciuto/non scalare e fonti derivate senza
tipo `fonte` dichiarato. Le tabelle schema non vengono confuse con il censimento
fonti. `qualsiasi` e `stesso tipo` conservano il significato; la nuova relazione
`approva` valida gli archi senza introdurre inferenze. La coerenza del significato
dei testi richiede revisione umana, senza eseguire schema, HTML o esempi.

Builder v3 distingue le generazioni dalla validazione precedente. Lettura v2
ancora disponibile con `graph_validation_upgrade`, senza scritture GET; il
rebuild esplicito applica i nuovi controlli. Errori lasciano intatto il marker
precedente. `/ontology` espone digest byte, span, modificabilità e problemi
limitati; legge sempre lo schema della generazione pubblicata.

Verifiche ECC verification-loop e security-review: 154 test totali, 153 pass,
uno skip symlink Windows noto. Le 18 nuove regressioni coprono parser, serializer,
proposte senza scritture, builder e HTTP; 14 regressioni query anche eseguite
separatamente. Installer `--prova` e `--prova --dashboard` superati, con parser
distribuito e CLI autonoma funzionante; fixture eliminate dagli strumenti di
prova. Compilazione Python e controllo diff superati. Nessuna nuova dipendenza,
nessun type checker/linter/coverage dedicato configurato; nessuna percentuale di
coverage dichiarata. Nessun cambiamento di layout UI: verifica HTTP, senza nuovo
smoke browser. [Evidenze e limiti](evidence/step-3-1/verification.md).

Prossimo punto: 3.2, preview API con analisi impatto e suggerimenti di migrazione,
con pagina, proprietà e motivo per ogni violazione. Apply e migrazioni restano
futuri; nessun merge o aggiornamento dei branch principali.

## Incremento 10 — Preview ontologia e impatto (passo 3.2)

POST `/api/v1/vaults/{id}/ontology/preview` protetta da sessione/Origin/CSRF,
su manifest compatibile e snapshot corrente, anche senza grafo. Patch dichiarativa
con adozione esplicita, aggiunta/modifica/rimozione/rinomina di tipi e relazioni;
campi allowlist e nessun codice o percorso ricevuto eseguito. Schema candidato
prodotto dal serializer conservativo, diff escaped, hash proposta legato alla base.
Note, schema, raw, manifest, marker e DB personali rimangono invariati.

Il builder espone `problem_details` insieme ai messaggi precedenti, con stessa
validazione e senza cambiare la versione delle generazioni. Preview riusa questi
dettagli per pagina/proprietà/motivo/target, anche per difetti preesistenti. Espone
conteggi tipi delle pagine e delle fonti derivate, proprietà, archi impattati,
alias/fonti e riferimenti frontmatter/corpo/index/log/schema. Una rimozione usata
o restrizione incompatibile resta visibile come violazione; nessun arco cancellato.

Suggerimenti di rinomina senza collisioni su chiavi YAML semplici; vincoli/link
incompatibili o YAML ambiguo richiedono intervento manuale. Nessuna riscrittura
delle pagine. Rinomine di tipo aggiornano solo vincoli nello schema candidato;
le note rimangono tra le migrazioni suggerite. Catene di rinomina e page rename
non supportati. Testo libero segnalato per occorrenze letterali e revisione umana,
senza interpretazione semantica o sostituzioni automatiche. File condivisi presenti
segnalati bloccanti finché non esiste il mapping del passo 5. Capacità esplicite:
nessuna nuova inferenza per nuove relazioni, nessun apply disponibile.

Digest verificato prima/dopo analisi e al replay; modifica esterna produce 409
senza cache di un risultato incompleto. Idempotenza concorrente in memoria per
sessione, non journal persistente: 16 record, TTL 900 secondi, conflitto su payload
diverso, nuovo ID dopo scadenza/riavvio. Due richieste ammesse, analisi serializzate,
limiti documentati per Markdown, numero risultati e byte risposta. Nessuna
troncatura dichiarata completa; casi troppo grandi danno 422. Nessun lock o
directory locale creati dalla preview. `/status` dichiara preview compatibile e
apply disabilitato. Contratto completo nel [passo 3](03-editor-ontologia.md).

Verifiche ECC api-design, security-review e verification-loop: 18 nuove prove
HTTP reali, suite completa e prove installer descritte nelle
[evidenze](evidence/step-3-2/verification.md). Compilazione Python e revisione diff;
nessuna nuova dipendenza, type checker/linter/coverage dedicati non configurati.
Nessuna UI modificata, nessuno smoke browser nuovo. Solo fixture sintetiche.

Prossimo punto: 3.3, form UI con verso visibile, diff e capacità semantiche;
apply transazionale e recovery restano al 3.4. Nessun merge dei branch principali.

## Incremento 11 — Form proposte ontologia (passo 3.3)

Vista Ontologia con form di tipi/relazioni, verso sorgente → destinazione,
significato/esempio e coda di modifiche con etichette italiane. Adozione catalogo
esplicita, update come definizione completa, rimozione/rinomina senza inversione
automatica. Genera preview invia solo la POST protetta già disponibile; schema
pubblicato separato dal candidato e dalla base corrente, anche senza grafo.
Modelli, schema e diff restano testo inerte. Apply e migrazioni non disponibili.

Diff e impatto con pagina/proprietà/motivo, suggerimenti da confermare, conteggi,
testo libero e file condivisi. Liste oltre 200 elementi marcate parziali senza
alterare il risultato completo del servizio. Avviso esplicito: nuove relazioni
non producono nuove inferenze o regole. Bozza/campi conservati in memoria per
vault su refresh/cambio selezione; niente storage browser. Risultati obsoleti e
scadenza segnalati, epoch/versione impediscono sostituzione da risposte tardive.
Retry dopo perdita risposta riusa la chiave, conflitti offrono aggiornamento
esplicito della base e nuova preview, preservando la patch.

ECC frontend-design-direction, frontend-a11y e verification-loop: suite Python
172 test, 171 pass e uno skip symlink Windows noto. Smoke ECC Chrome DevTools
con 18 controlli riproducibili, ripetuto sul launcher installato con --dashboard;
prove aggiuntive su cambio reale della nota sintetica, base aggiornata, vault
senza grafo, legacy readonly, bozza per vault e tastiera Enter/Tab. Tutti gli hash
delle tre fixture invariati dopo restore byte della sola nota di prova.
Servizi di prova arrestati con uscita 0, fixture sacrificate e rimosse.

Compilazione Python, node --check del client assemblato e smoke, controllo diff
e installer --prova superati. Asset finali installati e CLI build/launcher reali
funzionanti. Nessuna nuova dipendenza, nessun coverage/type checker/linter
dedicato configurato. Desktop 1440x900 con screenshot JPEG, mobile 390x844 con
evidenza DOM renderizzata: la cattura immagine mobile non terminava ed è stata
interrotta. Nessun overflow e controlli da almeno 44 px, nessuna animazione;
non certificazione screen reader/cross-browser. [Report ECC e limiti](evidence/step-3-3/report.json).

Prossimo punto: 3.4, apply transazionale con mapping rinomine e recovery,
subordinato ai gate di protezione degli editor esterni e ai formati condivisi.

## Incremento 12 — Apply manuale locale e recovery (passo 3.4)

Apply esplicito su volume Windows locale fisso, con editor/hook sospesi e due
conferme distinte nella UI. Richiede preview corrente, hash proposta, If-Match,
selezione delle migrazioni e chiave idempotente persistente. Schema e rinomine
di tipo/proprietà passano prima dalla validazione completa e dal build su copia
isolata; migrazioni delle note preservano corpo, commenti e newline. YAML ambiguo,
selezioni incomplete e record condivisi impediscono l'applicazione.

Journal, snapshot e backup univoci permettono completamento o rollback espliciti
dopo crash. ReplaceFileW conserva la versione realmente sostituita; una modifica
estranea tra controllo hash e replace rimane nel backup e blocca il recovery.
Nessuna atomicità nativa multi-file o esclusione degli editor promessa. Il gate
con processo esterno dimostra che VaultLock è soltanto cooperativo: automatico
ed external_writer_exclusion restano false. Mapping di pagine/eventi rinviato
al passo 5; nessuna pubblicazione automatica introdotta.

Lista operazioni readonly e comandi recovery disponibili nella UI, anche dopo
riavvio e schema temporaneamente assente per errore nativo. Polling prosegue
durante il worker di recovery, fino a succeeded o rolled_back. Altre scritture
del servizio restano bloccate finché un'operazione note è pendente.

Verifica ECC database-migrations, verification-loop e frontend: 189 test,
188 pass e uno skip symlink Windows noto (386.396 s), inclusi 17 nuovi test.
Quattro controlli mirati ripetuti sul codice finale dopo il gate del volume:
tutti pass. Crash reale di processo dopo prima nota, fault nativi, concorrenza,
race e preservazione dati estranei verificati su fixture sacrificabili.
Installer --prova --dashboard, compilazione Python, node --check e diff superati.
Browser ECC sul runtime installato: apply da tastiera fino a succeeded e
interruzione/ripristino fino a rolled_back, desktop 1440x900 e mobile 390x844.
[Evidenze, report e limiti](evidence/step-3-4/verification.md).

Prossimo punto: 4.1, registry job/ricevute e adapter finto deterministico.
Il protocollo pagine/eventi e il gate di esclusione restano prerequisiti per
estendere l'apply oltre il percorso manuale documentato. Nessun merge.

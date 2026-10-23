# 2 — Dashboard locale di consultazione

Stato: bootstrap/attach readonly (2.1), API (2.2), UI (2.3), distribuzione e rebuild coordinato (2.4) implementati; adozione legacy e export diagnostica ancora futuri. Dipende dal [contratto 1](01-contratto-dati-operazioni.md). Obiettivo utente: collegare una cartella già installata, vedere ontologia, grafo e diagnostica con una chiara indicazione della revisione. Non serve reinstallare o caricare il vault su un servizio remoto. Dettagli effettivamente disponibili nel [registro implementazioni](08-analisi-avanzamento.md).

## Punto di partenza e scope

Il punto di partenza era un kit di strumenti CLI e integrazioni per client; il bootstrap HTTP locale è stato aggiunto nell'incremento 2.1. [build_graph.py](../kit/graph/build_graph.py) produce tabelle `entities`, `relations`, `aliases`, `varianti` e FTS `testo`. [Wiki reference.md](../kit/vault/Wiki%20reference.md) definisce convenzioni e vocabolario, non una API. Questa fase consulta; non modifica ontologia, non esegue ingest/lint e non sincronizza Git. Il rebuild locale derivato resta un job esplicito e coordinato, mai un effetto nascosto di una GET.

## Componenti e flusso proposti

`kit/dashboard/server.py` serve le API readonly e la pagina di collegamento; `read_api.py` legge le generazioni del grafo. Il workbench UI offre grafo/lista, filtri, dettaglio, ontologia e diagnostica. Il launcher disponibile è `python .graph/teseo_dashboard.py --vault "C:/Obsidian/MioVault"`, con `--no-browser` facoltativo. Il registro è in memoria per default; con `--registry <file-assoluto>` persiste solo nel file locale scelto dal launcher, preferibilmente in `.teseo/local/` ignorata da Git. La UI di consultazione è disponibile dal 2.3; non esiste ancora un entrypoint binario `teseo-dashboard`.

1. L'utente indica un percorso locale tramite comando o form e visualizza la cartella risolta.
2. `POST /api/v1/vaults/attach` valida root, file attesi e compatibilità senza eseguire file del vault. Restituisce `vault_id`, modalità `readonly/compatible/legacy/incompatible`, problemi e capacità.
3. Se manca il grafo, la UI mostra «grafo non disponibile» e offre rebuild del passo 1. Una vista precedente rimane leggibile con avviso di obsolescenza e digest.
4. La home mostra conteggi e stato locale. Vista grafo filtrabile per tipo/relazione, frecce e legenda; dettaglio nodo mostra frontmatter, fonti e collegamenti verificabili al testo.
5. Vista ontologia legge la sezione canonica; diagnostica distingue errore di parsing, struttura, compatibilità e controllo semantico. Esportare una diagnosi oscura percorsi sensibili e non include note per default.

## Contratto API di consultazione e rebuild

Le GET sotto sono disponibili su generazioni builder v2 e v3. Dal passo 3.1 il
rebuild esplicito produce v3 con validazione del catalogo tipi; le generazioni v2
restano leggibili con avviso `graph_validation_upgrade`, senza rebuild implicito.
POST rebuild e GET
operations sono disponibili dal 2.4, con sessione/Origin/CSRF sulle POST. Passare `generation=<id>` alle GET successive per
fissare una lettura; cambio della generazione corrente produce `409 revision_changed`.
Un vecchio grafo richiede rebuild esplicito con il kit aggiornato e manifest compatibile, mai una GET.

Tutti i percorsi sotto `/api/v1/vaults/{id}`. GET non lancia modelli, Git o mutazioni dei DB personali.

| Endpoint | Risposta principale |
| --- | --- |
| `GET /status` | digest contenuti, generazione, versione schema, busy, stale, capacità |
| `GET /graph?type=...&relation=...&cursor=...&limit=...` | nodi, archi e cursore con revisione fissata |
| `GET /nodes/{node_id}` | testo escaped, proprietà, fonti e archi; ID URL-encoded |
| `GET /ontology` | tipi, relazioni, direzione, sezioni non interpretate e digest |
| `GET /diagnostics` | lista `{code,severity,path,message,revision}` |
| `POST /rebuild` | job derivato con `operation_id`; nessuna modifica delle note |
| `GET /operations/{operation_id}` | stato e risultato strutturato |

Ogni risposta contiene `content_revision` e `graph_generation`; usare ETag e `If-None-Match` per cache. La paginazione di una generazione scaduta restituisce `409 revision_changed`, non combina revisioni. Errori: `400` input invalido, `403` sessione/path non autorizzato, `404` vault/nodo assente, `409` stato o revisione incompatibile, `422` formato non supportato, `503` capacità temporaneamente indisponibile. Gli errori contengono `code`, messaggio utile e possibilità di retry senza traceback o segreti.

La UI carica il grafo a blocchi con limiti server; non promettere rendering completo di vault arbitrariamente grandi. Ricerca e filtri sono deterministici; la ricerca semantica AI è esclusa. Markdown renderizzato senza HTML attivo; link esterni richiedono navigazione esplicita e non vengono fetchati dal server.

## Concorrenza, sicurezza e alternative

Servizio su `127.0.0.1` con sessione casuale locale, verifica Host/Origin, CSRF sulle POST e CORS chiuso. Non accettare URL remoti al posto di percorsi e non offrire endpoint shell/SQL generici. Una cartella collegata è una scelta esplicita dell'utente; successivi path relativi sono risolti dentro quella root, rifiutando symlink/junction di fuga. Il contenuto del vault è dato non attendibile. Non mostrare DB memoria o sessioni nella home condivisibile.

Ogni lettura usa una generazione stabile e breve connessione SQLite; durante rebuild la UI mantiene quella precedente con badge. Eventi UI futuri possono usare polling ETag iniziale, più semplice di WebSocket; SSE è alternativa se i volumi lo richiedono. Preferire UI piccola statica servita dallo stesso processo; scegliere libreria server e renderer dopo prova di packaging, mantenendo il contratto API indipendente. Obsidian plugin e applicazione desktop separata sono fuori scope.

## Incrementi da una PR

1. Bootstrap servizio/launcher e attach readonly con fixture di vault legacy e invalido; uscita: nessuna esecuzione di script ricevuti e nessuna scrittura nelle note.
2. API generazioni, nodi, ontologia e diagnostica; uscita: stesso digest su tutte le risposte di una sessione di lettura.
3. UI home, filtri e dettaglio, gestione errori e stati stale; uscita: navigazione tastiera, testo dei problemi e rendering di contenuti ostili inerti.
4. Distribuzione con `installa.py`, arresto pulito e rebuild coordinato; uscita: comando disponibile in installazione nuova e aggiornamento con backup.

## Accettazione e test previsti

- Collegare un vault valido preserva hash di note/raw/schema; root errata e formato futuro mostrano errore leggibile.
- Nodo con spazi, accenti e nome vicino per maiuscole viene risolto o segnala ambiguità senza aprire file esterni.
- Frecce distinguono `X usa Y` da archi inversi di consultazione; una relazione nuova è visibile senza inventare inferenze.
- Rebuild fallito mostra l'ultima revisione valida e la causa; una GET non cambia DB domande/memoria.
- Provare vault grande, paginazione, refresh durante cambio generazione, browser senza rete, XSS Markdown, POST cross-origin e path traversal.

Regressioni dalla root: `python installa.py --prova`, `python -m unittest discover -s tests -v`. Test disponibili: `tests/test_dashboard_readonly.py` e `tests/test_dashboard_queries.py`, eseguibili con unittest discover e il relativo pattern. Lo smoke UI riproducibile è in `tests/dashboard_ui_smoke.js`, con fixture generata da `python tests/dashboard_ui_fixture.py <nuova-cartella>`. Le [evidenze ECC](evidence/step-2-3/report.json) documentano lo smoke Chrome; non è una suite browser automatica di CI. Smoke browser ECC e risultati correnti sono registrati nel [registro implementazioni](08-analisi-avanzamento.md); il gate Windows del lettore SQLite aperto è stato verificato nell'incremento 1.4.

## Rollout, rollback e questioni aperte

Rilasciare sola consultazione prima dei pulsanti mutanti, che restano nascosti finché i passi successivi non sono disponibili. Arrestare il processo termina la UI locale; chiudere solo il tab non equivale ad arrestare il servizio. Rollback rimuove l'attivazione del launcher e conserva registro locale; gli asset possono essere ripristinati dal backup dell'installatore. Scelte aperte: porta dinamica, libreria HTTP, accessibilità del grafo tramite lista equivalente e dimensione massima pagina; definirle con fixture rappresentative, senza stime rigide.

## UI disponibile (2.3)

Avviare il launcher aggiornato e aprire il collegamento completo stampato nel
terminale. Il frammento di sessione viene rimosso e il token resta solo in memoria:
ricaricare la scheda richiede riaprire quel collegamento. Il registro termina
con il servizio salvo opzione `--registry`. I dati non vengono salvati nel browser.

Selezione vault e Aggiorna vista caricano status, fissano la generazione e passano
quel pin a tutte le letture successive. Filtri per tipo e relazione sono server-side;
la ricerca testuale riguarda esclusivamente i nodi caricati. Le pagine contengono
al massimo 50 nodi e 50 archi ciascuna; nodi e archi avanzano separatamente nel
medesimo cursore. I conteggi descrivono dati caricati, non totali del vault.
Il disegno mostra al massimo 12 nodi e 80 archi tra questi: frecce e liste esplicitano
sorgente → tipo → destinazione. Su mobile il disegno scorre nel proprio contenitore.
La lista completa dei nodi caricati offre etichette non abbreviate e navigazione
tastiera. Selezione nodo sposta il focus al dettaglio con proprietà, alias, fonti,
archi e documento della generazione. Markdown è testo preformattato: nessun HTML
attivo né fetch di immagini/link dal contenuto. Fonti e relazioni aprono nodi tramite
ID esatto; il percorso della nota è indicativo e non apre file arbitrari.

Lo stato stale riguarda i contenuti vivi rispetto alla generazione pubblicata;
si controlla con Aggiorna vista, senza polling implicito. Un 409 conserva i dati già
caricati e blocca paginazione/filtri/dettagli fino al refresh esplicito. Risposte
obsolete dopo cambio vista/vault/nodo sono scartate. Errori di rete offrono retry,
grafo assente disabilita la consultazione e mantiene il motivo diagnostico. Nessuna
GET avvia rebuild. Dal 2.4 sono disponibili job del servizio, registro opzionale
e rebuild esplicito; export diagnostica non ancora disponibile.


## Distribuzione e operazioni disponibili (2.4)

Python minimo 3.10, coerente con le annotazioni del runtime. `installa.py <cartella-vuota>
--dashboard` crea esplicitamente un manifest v1 con UUID nuovo e costruisce il primo
grafo versionato. L'installazione senza flag conserva il comportamento legacy;
nessun vault esistente non compatibile viene adottato neppure con --aggiorna.
Il launcher Python è disponibile con ogni installazione completa. Un aggiornamento
--aggiorna, a servizio fermo, copia il runtime con backup distinto per modulo e
con timestamp a microsecondi. Manifest esistente, note, raw e DB personali non
sono migrati o sovrascritti. `--solo-integrazione` non distribuisce il runtime.

POST `/api/v1/vaults/{id}/rebuild` richiede esattamente
`{idempotency_key, expected_content_revision}`; la chiave è 8–128 caratteri
ASCII alfanumerici, underscore o trattino; revisione è SHA-256 o null se sconosciuta.
Risposta 202 con operation_id e stato anche per il replay di un risultato terminale.
Stessa chiave/payload recupera il job, anche dopo riavvio; payload diverso dà 409.
Un job attivo per vault, al massimo quattro vault nel processo; altre richieste
ricevono 409, senza coda illimitata. Il lock kernel è lo stesso di CLI/hook: una
richiesta respinta per vault occupato può essere ritentata. Il controllo di digest
prima del build e prima della pubblicazione rileva scritture di editor esterni;
non è una garanzia di esclusione contro editor non cooperanti.

Il journal comune `.teseo/local/operations.sqlite` conserva base, hash, snapshot,
errori e checkpoint della generazione derivata. Solo `complete_rebuild` può
completare questo tipo di job senza apply note: l'apply degli altri tipi resta
bloccato. Stati osservabili: created, waiting_lock, running, validating e terminali
succeeded/failed/cancelled/blocked_external_change/recovery_required. La fase
waiting_lock è registrata all'acquisizione del lock nel worker, non promette una
coda globale. Errori parsing riportano pagina e motivo, validazione semantica al
massimo 20 dettagli da 500 caratteri. Fallimenti generici non espongono traceback.

GET `/operations/{operation_id}` legge il journal readonly senza creare storage
né fare replay; il DTO espone stato, base_content_digest, errore e checkpoint,
non i contenuti degli snapshot. Un record non gestito dal processo corrente è
presentato come recovery_required, con invito a verificare eventuali altri servizi.
Solo una nuova POST sotto lock persiste recovery dei rebuild pendenti; non tocca
operazioni note e non riesegue il vecchio job. Crash dopo pubblicazione e prima
del checkpoint può lasciare grafo valido e job da verificare; nessun rollback
implicito. Si può avviare una nuova richiesta con nuova chiave dopo verifica.

`/status` espone busy_known=true, busy_scope=service, active_operation_id e capacità
rebuild per manifest compatibile. Questo stato riguarda i job di questo processo:
non certifica che editor o altri processi siano inattivi. Durante il build la UI
mantiene la vecchia generazione; alla fine invita a refresh esplicito. La UI riusa
la chiave quando perde la risposta alla POST e distingue esito sconosciuto da
rifiuto certo. Poll limitato a un job visibile, interrotto cambiando vault o
arrestando il servizio; errori di polling richiedono refresh esplicito.

POST `/api/v1/shutdown` con `{}` richiede sessione, Origin e CSRF, restituisce 202
e ferma il listener. Il processo attende i thread HTTP e i worker non daemon;
il rebuild verifica annullamento tra le fasi e prima della pubblicazione. Una
pubblicazione già iniziata può concludersi; nessuna terminazione forzata, nessuna
cancellazione delle generazioni precedenti. Ctrl+C percorre lo stesso close.
Chiudere la scheda non arresta il processo e 202 non certifica già chiuso il terminale.

Registro opzionale con parent esistente, massimo 32 identità/percorsi e 64 KiB.
Scrittura atomica e lock kernel per l'intera sessione impediscono due servizi
sullo stesso file. Nessun token, password o codice ricevuto viene salvato/eseguito.
UUID cambiato, cartella assente o incompatibile al restore sono saltati con avviso;
un registro malformato blocca il launcher senza sovrascriverlo. La scelta del file
è esplicita e distinta dall'attach; le GET restano prive di scritture nei vault.

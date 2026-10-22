# 2 — Dashboard locale di consultazione

Stato: progettazione futura. Dipende dal [contratto 1](01-contratto-dati-operazioni.md). Obiettivo utente: collegare una cartella già installata, vedere ontologia, grafo e diagnostica con una chiara indicazione della revisione. Non serve reinstallare o caricare il vault su un servizio remoto.

## Punto di partenza e scope

Nel [README](../README.md) e nell'[installatore](../installa.py) sono presenti strumenti CLI e integrazioni per client; non è presente un server/frontend. [build_graph.py](../kit/graph/build_graph.py) produce tabelle `entities`, `relations`, `aliases`, `varianti` e FTS `testo`. [Wiki reference.md](../kit/vault/Wiki%20reference.md) definisce convenzioni e vocabolario, non una API. Questa fase consulta; non modifica ontologia, non esegue ingest/lint e non sincronizza Git. Il rebuild locale derivato resta un job esplicito e coordinato, mai un effetto nascosto di una GET.

## Componenti e flusso proposti

`kit/dashboard/server.py` serve API e asset; `graph_service.py` apre generazioni readonly; un registro in `.teseo/local/` associa UUID a percorsi canonici locali. Un comando futuro `teseo-dashboard --vault "C:/Obsidian/MioVault"` avvia su loopback e apre il browser. Il packaging del comando è parte dell'implementazione, non esiste oggi.

1. L'utente indica un percorso locale tramite comando o form e visualizza la cartella risolta.
2. `POST /api/v1/vaults/attach` valida root, file attesi e compatibilità senza eseguire file del vault. Restituisce `vault_id`, modalità `readonly/compatible/legacy/incompatible`, problemi e capacità.
3. Se manca il grafo, la UI mostra «grafo non disponibile» e offre rebuild del passo 1. Una vista precedente rimane leggibile con avviso di obsolescenza e digest.
4. La home mostra conteggi e stato locale. Vista grafo filtrabile per tipo/relazione, frecce e legenda; dettaglio nodo mostra frontmatter, fonti e collegamenti verificabili al testo.
5. Vista ontologia legge la sezione canonica; diagnostica distingue errore di parsing, struttura, compatibilità e controllo semantico. Esportare una diagnosi oscura percorsi sensibili e non include note per default.

## Contratto API futuro

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

Comandi **esistenti** per regressione futura dalla root: `python installa.py --prova`, `python -m unittest discover -s tests -v`. Test **da creare**: `tests/test_dashboard_readonly.py`, poi `python -m unittest discover -s tests -p 'test_dashboard_readonly.py' -v`; smoke browser documentato dopo scelta della libreria, senza inventare oggi un runner E2E. Verifica manuale su Windows: SQLite aperto mentre il servizio pubblica una nuova generazione. Non sono test eseguiti da questa redazione.

## Rollout, rollback e questioni aperte

Rilasciare sola consultazione prima dei pulsanti mutanti, che restano nascosti finché i passi successivi non sono disponibili. Arrestare il processo termina la UI locale; chiudere solo il tab non equivale ad arrestare il servizio. Rollback rimuove l'attivazione del launcher e conserva registro locale; gli asset possono essere ripristinati dal backup dell'installatore. Scelte aperte: porta dinamica, libreria HTTP, accessibilità del grafo tramite lista equivalente e dimensione massima pagina; definirle con fixture rappresentative, senza stime rigide.

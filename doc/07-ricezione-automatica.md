# 7 — Ricezione automatica, recovery e prove multi-clone

Stato: rilevamento periodico opt-in e adozione manuale con recovery implementati (Windows e, dal [passo 10](10-editor-grafo-e-autori.md), POSIX). Apply automatico disabilitato. Richiede [1](01-contratto-dati-operazioni.md), [2](02-dashboard-consultazione.md), [5](05-stato-condiviso.md), [6](06-pubblicazione-github.md). Ogni clone può rilevare una pubblicazione remota, preparare un candidato isolato e adottarlo dopo la conferma esplicita di sospensione degli scrittori esterni. La ricezione ricostruisce grafo e proiezione senza avviare ingest/lint mutanti. La condizione filesystem libero non abilita applicazioni automatiche.

## Contesto e confini

Il [README](../README.md) descrive uso locale e aggiornamento del kit tramite Git, non un daemon dati. [recall_hook.py](../kit/graph/recall_hook.py) reagisce alla freschezza locale del grafo, non ai push remoti. Il builder separato del passo 1 e il publisher esplicito del passo 6 sono i prerequisiti già disponibili. Stato condiviso testuale e proiezione domande sono quelli del passo 5; i DB personali non vengono sostituiti con quelli altrui.

Scope: servizio di ricezione mentre il processo locale è attivo, import di checkpoint Git e invalidazione UI/cache. Avvio automatico del servizio con il sistema operativo è opzionale successivo con consenso locale. Nessuna promessa di aggiornamenti mentre PC è spento/sospeso, servizio arrestato o rete assente.

## Rilevamento disponibile e stato locale

`kit/dashboard/receiver.py` mantiene per vault `last_seen_remote_oid`, `last_applied_oid`, `pending_oid`, `last_fetch_at`, errore, backoff e sync operation ID; questi campi sono locali. Rilevamento inizialmente disabilitato; la UI propone 60 secondi. API: intervallo intero configurabile fra 30 e 3600 secondi, default 45, con jitter. Nessuna garanzia di latenza. Un solo fetch per remote/branch e nessuna sovrapposizione con publisher. Errori rete aumentano backoff con limite, autenticazione fallita sospende retry frequenti e mostra azione richiesta. La scadenza persistita permette un solo controllo alla ripresa del processo o dopo la sospensione, senza recuperare a raffica tutti i tick mancati.

La chiusura del tab lascia attivo il processo avviato dal launcher; l'arresto esplicito ferma poll e import. UI mostra servizio attivo, ultimo controllo, commit visto/applicato, aggiornamento in attesa e motivo del rinvio. Una notifica non implica che i file siano già stati applicati. Non sovrascrivere `last_applied_oid` fino al checkpoint completo.

Rilevamento: `idle → fetching → up_to_date|local_ahead|pending|waiting_idle`. Adozione esplicita: `applying → rebuilding → current`, oppure `recovery_required`; rollback concluso: `rolled_back`. Ripetere la stessa richiesta dopo `current` restituisce il risultato già registrato (idempotente); dopo `rolled_back` è rifiutata con `receiver_stale`, perché il rollback scarta candidato e revisione: occorre rileggere il candidato. Errori `offline`, `auth_required`, `incompatible`, `diverged`, `needs_resolution`, `recovery_required`. Un nuovo OID sostituisce il pending soltanto se ne include la storia; cambi di branch remoto o rewind remoto richiedono attenzione invece di import automatico.

## Condizione di vault libero e algoritmo

Libero significa: nessun job mutante, consolidamento o pubblicazione in corso; nessuna recovery pendente; lock acquisibile; working tree e index puliti, inclusi file non tracked rilevanti; snapshot e digest ricontrollati nelle fasi di preparazione e adozione. Un quiet period misurato e configurabile resta da qualificare. File ignorati personali non impediscono import, ma nuovi file dati non attribuiti sì. Questa condizione rilevata non basta per l'apply: occorre anche modalità cooperativa o esclusione degli scrittori dimostrata secondo il passo 1. Dove non disponibile, sospendere gli scrittori esterni prima dell'apply e lasciare durante editing il receiver in sola rilevazione. Un editor con buffer non salvato e una scrittura tra hash e replace non sono protetti dai soli controlli filesystem: la UI deve dichiarare entrambi i limiti, senza promettere assenza di perdita in modalità non protetta.

1. Fetch rileva `R` senza toccare note; se coincide col già applicato, nessun rebuild, job AI, log condiviso o commit.
2. Se il vault è occupato, conservare `pending_oid` e motivo; non interrompere job o forzare l'import.
3. Acquisire lock e rivalutare digest/index/branch. Verificare relazione fra HEAD locale e `R`: ahead locale resta da pubblicare; se HEAD è antenato di `R`, candidato fast-forward; divergenza passa al protocollo isolato del passo 6 o a risoluzione esplicita, mai pull con merge implicito nel vault vivo.
4. Preparare snapshot isolato di `R`, validare compatibilità kit/schema/eventi, percorsi consentiti, hash raw rispetto alla base locale e integrità dei record. Script, hook e configurazioni client ricevuti non vengono attivati; file non dati inattesi bloccano import con diagnostica.
5. Prima dell’adozione esplicita, verificare struttura, schema, eventi, grafo e sintesi del candidato isolato. Il solo rilevamento prepara snapshot e preview, senza dichiarare conclusi questi gate; la proiezione locale viene ricostruita nel checkpoint finale. Non eseguire ingest/lint mutante di default. Per candidato già validato dal publisher verificare comunque i controlli locali: non fidarsi soltanto di un messaggio commit. Se si integra una divergenza, applicare riconciliazione mirata con chiave del passo 6; se un contributo esterno non ha evidenza di verifica e tocca fatti correlati, sospendere per lo stesso controllo esplicito prima di pubblicare una successiva integrazione.
6. Ricontrollare libertà e hash prima di applicare; un intervento editor rilevato rinvia l'import e conserva il candidato. Acquisire inoltre l'esclusione verificata o richiedere la sospensione degli scrittori esterni prevista dal contratto. Applicare note/eventi e ref/index tramite checkpoint journal; ff-only del branch quando applicabile. Non usare stash o reset automatici. Controllare precondizioni e postcondizioni e fermare recovery in caso di incongruenza; questi controlli diagnosticano molte race, ma non sostituiscono l'esclusione. Aggiungere fault injection tra ultimo hash e replace: se una scrittura non è impedita, quella modalità non può essere qualificata per apply automatico protetto.
7. Pubblicare generazione locale valida e proiezioni; impostare `last_applied_oid`, invalidare cache per revisione e aggiornare UI con evento locale `vault.updated`. Un lettore già aperto può completare sulla vecchia generazione e dichiararla. Se rebuild non riesce, non dichiarare current; conservare ultima generazione e journal, mostrare stale e riprovare solo la fase recuperabile.

Il ricevitore non committa un log solo perché ha importato. Evento `vault.updated` non equivale a `operation.validated`: non innesca il publisher. Una riconciliazione necessaria è job figlio identificato; deduplicare input revisioni/policy ed evitare che il proprio commit di riconciliazione riattivi lo stesso lavoro.

## API, sicurezza e alternative

Disponibili `GET /api/v1/vaults/{id}/sync/status`, `POST /sync/check`, `POST /sync/pause`, `POST /sync/resume` condividono il servizio del passo 6; pause è locale e persistente. Notifiche browser tramite polling ETag del passo 2; SSE facoltativo, niente dipendenza dalla presenza del tab per fare fetch. Le credenziali restano nel Git locale, gli errori pubblici sono redatti. Limiti per dimensione evento/file e numero file evitano import incontrollati; nuove fonti voluminose richiedono policy esplicita. Niente checkout di submodule, filtri o hook ricevuti: la prima PR Git deve anche isolare le impostazioni eseguibili del repository durante staging e mostrare configurazioni locali incompatibili.

Webhook è alternativa successiva per ridurre latenza, non prerequisito. [GitHub invia eventi a un server esterno](https://docs.github.com/en/webhooks/about-webhooks); [localhost non è una destinazione supportata](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/troubleshooting-webhooks#url-host-localhost-is-not-supported). Serve endpoint pubblico o relay autenticato, verifica firma, protezione replay e fallback poll. Gli [hook Git](https://git-scm.com/docs/githooks) locali non notificano da soli push di altre macchine. Il primo rilascio evita questa infrastruttura.

## Articolazione del passo 7

1. Poll con clock/remote finti, backoff e persistenza pending; uscita: riavvio e sospensione non perdono la revisione vista.
2. Gate di idle/dirty/divergenza e staging readonly del remote; uscita: nessuna modifica del vault occupato.
3. Apply/rebuild/import proiezioni con recovery e invalidazione UI; uscita: una vista current ha tutti i componenti sulla stessa revisione.
4. Harness multi-clone e fault injection; uscita: tutti i gate sotto sono riproducibili con bare remote temporaneo.
5. UX pausa/ripresa e documentazione limiti di attività del servizio; uscita: stato comprensibile dopo offline e PC sospeso.

## Adozione manuale e recovery disponibili

`POST /sync/receive` richiede `exclusive_confirmed: true`, `expected_head`,
`pending_oid` ed `expected_digest`, tutti legati al candidato corrente mostrato
nello stato. Il servizio ricontrolla file e storia Git, valida e ricostruisce il
candidato isolato, conserva snapshot e index nel journal locale e applica solo
il fast-forward revisionato. Non esegue merge nel vault vivo né job AI mutanti.

`POST /sync/receive-recover` richiede le stesse precondizioni originali e
`action: "finish"` oppure `"rollback"`. Il recovery verifica che i byte correnti
siano ancora quelli attesi; modifiche esterne successive fermano il ripristino.
Non cancellare `.teseo/local/receive.sqlite`, snapshot o lock di una ricezione
interrotta. Conservare prima copie e diff se la diagnostica richiede intervento.

`sync/status` separa `receiver` e `receive_transaction` dal publisher. La UI
mostra ultimo OID visto/applicato, pending, controlli temporali, errori e digest.
Un candidato pending lascia le viste sulla generazione corrente. Dopo il
checkpoint completo, `vault.updated` segnala la nuova revisione: **Aggiorna
vista** rilegge grafo e stato. Il messaggio non avvia una pubblicazione.

Il protocollo manuale Windows usa journal, verifiche per-file, index lock e
compare-and-swap della ref. Non impedisce salvataggi di editor non cooperanti o
buffer non salvati: sospendere gli scrittori prima di confermare. Altri sistemi
operativi e avvio con il sistema non sono qualificati da questa consegna.

## Matrice di accettazione integrata

| Caso riproducibile | Esito osservabile richiesto |
| --- | --- |
| A conclude ingest+lint, B libero | A pubblica; B importa note/eventi e mostra nuova generazione senza job AI mutante |
| B esegue lint o modifica salvata | Fetch consentito; apply rinviato con motivo; ripresa solo a stato libero |
| A e B cambiano stessa nota | Candidato isolato in conflitto; nessun lato perso o sovrascritto |
| A/B cambiano note distinte ma correlate | Controllo semantico mirato dell'integrazione; contraddizione esplicita o decisione richiesta |
| Entrambi aggiornano index/log | Entry identificabili preservate; testo libero ambiguo richiede risoluzione |
| Raw nuovo / raw modificato o rinominato | Nuovo ammesso se selezionato; preesistente alterato blocca apply e push |
| Poll/import ripetuto stesso OID | No-op: nessun nuovo commit, job lint o incremento di rinvii |
| Offline, timeout push, crash prima/dopo apply | Ripresa dal journal; stato remoto riaccertato; output e stato personale conservati |
| Push rifiutato / branch protetto | Retry limitato solo per race; policy/consenso visibili, nessun force/bypass |
| Editor cambia dopo validazione | Precondizione fallita, candidato conservato e file dell'editor intatto |
| SQLite aperto su Windows | Vecchio lettore coerente; nuova generazione disponibile; pulizia rinviabile |
| Due lint concorrenti | Un solo scrittore e seconda operazione in coda |
| Risposte concorrenti e consolidamento | UUID e replay idempotenti; solo risposte dichiarate consolidate insieme alle note |
| Formato futuro / script ricevuto | Import bloccato o modalità compatibile dichiarata; nessuna esecuzione automatica |

Harness disponibile: `tests/test_dashboard_receiver.py` usa clock/remote controllati per scheduling, backoff, stop e persistenza; `tests/test_receiver_apply.py` usa due clone Git e remoto bare locale per adozione e recovery. Non equivale a una prova end-to-end con client AI autenticati o a fault injection di tutte le transizioni. Comando di verifica del rilevamento: `python -m unittest discover -s tests -p 'test_dashboard_receiver.py' -v`. Regressioni **esistenti** dalla root: `python installa.py --prova`, `python -m unittest discover -s tests -v`. Le prove reali Windows con editor/SQLite aperto e client autenticati sono smoke separati da registrare. Risultati effettivi e limiti nelle [evidenze ECC](evidence/step-7/verification.md); la matrice sopra esprime criteri integrati e non certifica ogni scenario come superato.

## Rollout, rollback e questioni aperte

La preview mostra diff e hash dei file come testo inerte. Preview troncate o oltre i limiti visibili disabilitano l’apply dalla UI; il candidato completo resta locale.
Anche file binari, testo non UTF-8 o non normalizzato NFC possono rendere la
preview incompleta: la sorgente non viene normalizzata per produrre una preview.

Il rilascio offre rilevamento opt-in e import manuale da candidato. Un futuro apply automatico richiede esclusione degli scrittori dimostrata, ulteriori prove e consenso locale; non è un’opzione disponibile nella UI. Prova pilota con due clone prima di attivare per tutto il gruppo. Rollback mette in pausa receiver/publisher e conserva journal, OID e dati; non elimina checkpoint già condivisi. Recovery con modifiche esterne richiede scelta esplicita su copie e diff, mai ripristino automatico distruttivo.

Da definire con misure: intervallo poll, quiet period, retention e limiti dimensionali. Da esplicitare nelle release: supporto Windows/macOS/Linux effettivamente testato e limite dei buffer editor non salvati. Nessuna sincronizzazione immediata garantita mentre servizio o computer sono inattivi.

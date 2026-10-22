# 7 — Ricezione automatica, recovery e prove multi-clone

Stato: progettazione futura. Richiede [1](01-contratto-dati-operazioni.md), [2](02-dashboard-consultazione.md), [5](05-stato-condiviso.md), [6](06-pubblicazione-github.md). Obiettivo utente: ogni clone rileva una pubblicazione remota e, appena libero, importa dati validi, ricostruisce lo stato locale e aggiorna la UI senza avviare un ingest/lint mutante per ogni pull.

## Contesto e confini

Il [README](../README.md) descrive uso locale e aggiornamento del kit tramite Git, non un daemon dati. [recall_hook.py](../kit/graph/recall_hook.py) reagisce alla freschezza locale del grafo, non ai push remoti. [build_graph.py](../kit/graph/build_graph.py) oggi unisce costruzione e pubblicazione; prima della ricezione automatica serve il refactor sicuro del passo 1. Stato condiviso testuale e proiezione domande sono quelli del passo 5; i DB personali non vengono sostituiti con quelli altrui.

Scope: servizio di ricezione mentre il processo locale è attivo, import di checkpoint Git e invalidazione UI/cache. Avvio automatico del servizio con il sistema operativo è opzionale successivo con consenso locale. Nessuna promessa di aggiornamenti mentre PC è spento/sospeso, servizio arrestato o rete assente.

## Poll e stato persistente proposti

`kit/dashboard/receiver.py` mantiene per vault `last_seen_remote_oid`, `last_applied_oid`, `pending_oid`, `last_fetch_at`, errore, backoff e sync operation ID; questi campi sono locali. Poll iniziale proposto ogni 30–60 secondi con jitter, configurabile e da tarare; non è un requisito di latenza garantita. Un solo fetch per remote/branch e nessuna sovrapposizione con publisher. Errori rete aumentano backoff con limite, autenticazione fallita sospende retry frequenti e mostra azione richiesta. Al ritorno dalla sospensione controllare subito con debounce e riprendere dal journal.

La chiusura del tab lascia attivo il processo avviato dal launcher; l'arresto esplicito ferma poll e import. UI mostra servizio attivo, ultimo controllo, commit visto/applicato, aggiornamento in attesa e motivo del rinvio. Una notifica non implica che i file siano già stati applicati. Non sovrascrivere `last_applied_oid` fino al checkpoint completo.

State machine: `idle → fetching → up_to_date|pending → waiting_idle → preparing → validating → importing → rebuilding → current`; errori `offline`, `auth_required`, `incompatible`, `diverged`, `needs_resolution`, `recovery_required`. Un nuovo OID sostituisce il pending soltanto se ne include la storia; cambi di branch remoto o rewind remoto richiedono attenzione invece di import automatico.

## Condizione di vault libero e algoritmo

Libero significa: nessun job mutante, consolidamento o pubblicazione in corso; nessuna recovery pendente; lock acquisibile; working tree e index puliti, inclusi file non tracked rilevanti; digest stabile dopo intervallo di quiete configurato. File ignorati personali non impediscono import, ma nuovi file dati non attribuiti sì. Questa condizione rilevata non basta per l'apply: occorre anche modalità cooperativa o esclusione degli scrittori dimostrata secondo il passo 1. Dove non disponibile, sospendere gli scrittori esterni prima dell'apply e lasciare durante editing il receiver in sola rilevazione. Un editor con buffer non salvato e una scrittura tra hash e replace non sono protetti dai soli controlli filesystem: la UI deve dichiarare entrambi i limiti, senza promettere assenza di perdita in modalità non protetta.

1. Fetch rileva `R` senza toccare note; se coincide col già applicato, nessun rebuild, job AI, log condiviso o commit.
2. Se il vault è occupato, conservare `pending_oid` e motivo; non interrompere job o forzare l'import.
3. Acquisire lock e rivalutare digest/index/branch. Verificare relazione fra HEAD locale e `R`: ahead locale resta da pubblicare; se HEAD è antenato di `R`, candidato fast-forward; divergenza passa al protocollo isolato del passo 6 o a risoluzione esplicita, mai pull con merge implicito nel vault vivo.
4. Preparare snapshot isolato di `R`, validare compatibilità kit/schema/eventi, percorsi consentiti, hash raw rispetto alla base locale e integrità dei record. Rifiutare script/hook/config client ricevuti come attivazioni; eventuali file non dati inattesi bloccano import con diagnostica.
5. Importare eventi in proiezione candidata, ricostruire grafo e verificare deterministici e sintesi. Non eseguire ingest/lint mutante di default. Per candidato già validato dal publisher verificare comunque i controlli locali: non fidarsi soltanto di un messaggio commit. Se si integra una divergenza, applicare riconciliazione mirata con chiave del passo 6; se un contributo esterno non ha evidenza di verifica e tocca fatti correlati, sospendere per lo stesso controllo esplicito prima di pubblicare una successiva integrazione.
6. Ricontrollare libertà e hash prima di applicare; un intervento editor rilevato rinvia l'import e conserva il candidato. Acquisire inoltre l'esclusione verificata o richiedere la sospensione degli scrittori esterni prevista dal contratto. Applicare note/eventi e ref/index tramite checkpoint journal; ff-only del branch quando applicabile. Non usare stash o reset automatici. Controllare precondizioni e postcondizioni e fermare recovery in caso di incongruenza; questi controlli diagnosticano molte race, ma non sostituiscono l'esclusione. Aggiungere fault injection tra ultimo hash e replace: se una scrittura non è impedita, quella modalità non può essere qualificata per apply automatico protetto.
7. Pubblicare generazione locale valida e proiezioni; impostare `last_applied_oid`, invalidare cache per revisione e aggiornare UI con evento locale `vault.updated`. Un lettore già aperto può completare sulla vecchia generazione e dichiararla. Se rebuild non riesce, non dichiarare current; conservare ultima generazione e journal, mostrare stale e riprovare solo la fase recuperabile.

Il ricevitore non committa un log solo perché ha importato. Evento `vault.updated` non equivale a `operation.validated`: non innesca il publisher. Una riconciliazione necessaria è job figlio identificato; deduplicare input revisioni/policy ed evitare che il proprio commit di riconciliazione riattivi lo stesso lavoro.

## API, sicurezza e alternative

Futuri `GET /api/v1/vaults/{id}/sync/status`, `POST /sync/check`, `POST /sync/pause`, `POST /sync/resume` condividono il servizio del passo 6; pause è locale e persistente. Notifiche browser tramite polling ETag del passo 2; SSE facoltativo, niente dipendenza dalla presenza del tab per fare fetch. Le credenziali restano nel Git locale, gli errori pubblici sono redatti. Limiti per dimensione evento/file e numero file evitano import incontrollati; nuove fonti voluminose richiedono policy esplicita. Niente checkout di submodule, filtri o hook ricevuti: la prima PR Git deve anche isolare le impostazioni eseguibili del repository durante staging e mostrare configurazioni locali incompatibili.

Webhook è alternativa successiva per ridurre latenza, non prerequisito. [GitHub invia eventi a un server esterno](https://docs.github.com/en/webhooks/about-webhooks); [localhost non è una destinazione supportata](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/troubleshooting-webhooks#url-host-localhost-is-not-supported). Serve endpoint pubblico o relay autenticato, verifica firma, protezione replay e fallback poll. Gli [hook Git](https://git-scm.com/docs/githooks) locali non notificano da soli push di altre macchine. Il primo rilascio evita questa infrastruttura.

## Incrementi da una PR

1. Poll con clock/remote finti, backoff e persistenza pending; uscita: riavvio e sospensione non perdono la revisione vista.
2. Gate di idle/dirty/divergenza e staging readonly del remote; uscita: nessuna modifica del vault occupato.
3. Apply/rebuild/import proiezioni con recovery e invalidazione UI; uscita: una vista current ha tutti i componenti sulla stessa revisione.
4. Harness multi-clone e fault injection; uscita: tutti i gate sotto sono riproducibili con bare remote temporaneo.
5. UX pausa/ripresa e documentazione limiti di attività del servizio; uscita: stato comprensibile dopo offline e PC sospeso.

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

Harness **futuro**: `tests/test_dashboard_receiver.py`, creare bare remote temporaneo e due vault tramite installatore, adapter finto che produce note valide e conflitti controllati, clock finto per poll; iniettare arresto a ogni transizione. Comando dopo implementazione: `python -m unittest discover -s tests -p 'test_dashboard_receiver.py' -v`. Regressioni **esistenti** dalla root: `python installa.py --prova`, `python -m unittest discover -s tests -v`. Le prove reali Windows con editor/SQLite aperto e client autenticati sono smoke separati da registrare. Questa redazione non ha eseguito né harness né suite runtime.

## Rollout, rollback e questioni aperte

Abilitare prima rilevamento senza apply, poi import manuale da candidato, infine ricezione automatica con pausa locale. Prova pilota con due clone prima di attivare per tutto il gruppo. Rollback mette in pausa receiver/publisher e conserva journal, OID e dati; non elimina checkpoint già condivisi. Recovery con modifiche esterne richiede scelta esplicita su copie e diff, mai ripristino automatico distruttivo.

Da definire con misure: intervallo poll, quiet period, retention e limiti dimensionali. Da esplicitare nelle release: supporto Windows/macOS/Linux effettivamente testato e limite dei buffer editor non salvati. Nessuna sincronizzazione immediata garantita mentre servizio o computer sono inattivi.

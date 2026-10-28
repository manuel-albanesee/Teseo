# 4 — Coordinamento delle skill ingest e lint

Stato: registry/API/ricevute (4.1), handoff client (4.2), pipeline con apply manuale (4.3), adapter e UI (4.4) disponibili. Avvio AI, isolamento nativo e callback automatici non verificati: fallback manuale esplicito per tutti i client. Richiede [1](01-contratto-dati-operazioni.md) e [2](02-dashboard-consultazione.md). Obiettivo: avviare dal servizio un lavoro riconoscibile, ricevere un esito verificabile e rendere pubblicabile soltanto il checkpoint attribuibile al ciclo concluso ingest+lint.

## Contesto attuale e scope

[Ingest](../kit/skills/obsidian-wiki-ingest/SKILL.md) legge fonti, aggiorna note, schema/indice e log e propone lint/lacune. [Lint](../kit/skills/obsidian-wiki-lint/SKILL.md) controlla contraddizioni, può creare sintesi e consolida risposte; contiene limiti sulle riscritture ampie e consensi da rispettare. Sono procedure del client, non comandi CLI indipendenti. [chiedi_codex.py](../kit/graph/chiedi_codex.py) usa sessione effimera readonly per query: non è un runner per scritture. Il ramo `Stop` di [codex_hook.py](../kit/graph/codex_hook.py) chiude memoria/turno; non certifica ingest o lint riusciti. Esaminare anche [claude_hook.py](../kit/graph/claude_hook.py) e [copilot_hook.py](../kit/graph/copilot_hook.py) per adattare ciascun client senza equipararne gli eventi.

Scope: lifecycle di job, adapter e completamento, attribuzione dei file e policy. Lacune con dialogo utente possono sospendere il job e non vanno simulate. Autenticazione AI rimane quella del client installato; nessun nuovo account provider nella dashboard e nessun SDK dato per supportato.

## Protocollo e componenti

`operations.py` orchestra; `adapters.py` implementa protocollo `probe`, `prepare`, `launch_or_handoff`, `cancel`, `collect_receipt`. Il probe registra versione rilevata, capacità effettivamente provate, supporto avvio/isolamento/callback e requisiti di consenso. Se non esiste un'interfaccia affidabile, produce un handoff esplicito alla chat: prompt operativo con UUID e comando di completamento locale. Stato «in attesa del client» resta visibile; non chiamarlo avvio automatico.

API disponibili:

```text
POST /api/v1/vaults/{id}/operations
  {kind: ingest_lint|lint|fill_gaps, inputs: [path],
   base_content_digest, adapter, idempotency_key, scope}
GET /api/v1/vaults/{id}/operations/{operation_id}
POST /api/v1/vaults/{id}/operations/{operation_id}/complete
POST /api/v1/vaults/{id}/operations/{operation_id}/cancel
```

`complete` richiede una ricevuta autenticata locale monouso legata all'operazione, digest della base, esito dichiarato, file prodotti con hash, ID risposte processate, esiti ingest e lint distinti, controlli e motivi delle sospensioni. Il servizio verifica ogni affermazione contro filesystem e controlli deterministici. Token callback non entra in repo o log condivisi. Un callback mancante o un processo terminato con exit 0 senza ricevuta non rende il ciclo riuscito. Un callback fallito si può reinviare idempotentemente; un completamento con hash diverso richiede nuovo controllo.

## Esecuzione e attribuzione

Preferire lavoro su snapshot/area isolata controllata, con scripts/client fidati forniti dal kit locale. Il contesto deve indicare il percorso dello snapshot per impedire scritture accidentali nel vault vivo e vietare mutazioni raw preesistenti. Verificare nella prima integrazione che il client legga davvero quell'area. Se l'adapter scrive solo sul vault vivo, non attribuire i file dal solo `git diff`: usare manifest prima/dopo, registro delle scritture del client quando disponibile e bloccare automaticamente i file ambigui. Una modifica esterna allo stesso file non è separabile in modo affidabile: conservare e chiedere risoluzione del conflitto.

State machine: `queued → preparing → awaiting_client/running_ingest → running_lint → validating → prepared → applying → succeeded`; transizioni laterali `awaiting_user`, `cancelled`, `failed`, `blocked_external_change`. Rilasciare lock durante attese umane, riacquisirlo ricontrollando base e digest. Ingest seguito da lint è un'unica operazione radice con fasi figlie; lint parziale dichiara il perimetro e non certifica l'intero vault come semanticamente corretto. Un job standalone di lint può produrre un checkpoint pubblicabile se include tutti i gate configurati.

La policy dell'utente deve abilitare il ciclo automatico quando lo desidera; le richieste di consenso del client e le conferme richieste dalle skill per riscritture ampie rimangono effettive. `awaiting_user` impedisce pubblicazione, senza ripetere richieste già soddisfatte. Nessun auto-rilancio per aggirare un rifiuto. Input del job seleziona solo fonti presenti o nuove fonti deliberate; non scaricare URL arbitrari tramite un endpoint generico.

Prima dell'apply: validare schema, raw, fonti, link, alias, sintesi e record condivisi; confronto hash dell'intero perimetro contro snapshot iniziale. File estranei nel working tree non vengono inclusi. Solo `succeeded` genera l'evento locale `operation.validated` con manifest immutabile e `publication_eligible`; il [passo 6](06-pubblicazione-github.md) lo consuma. Stop, watcher o commit manuale non generano questo evento. Fallimento del push non cambia retroattivamente l'esito locale della skill.

## Incrementi da una PR

1. Registry job, API, ricevute e adapter finto deterministico; uscita: una ricevuta duplicata non applica due volte.
2. Handoff verificabile a un client e documentazione installazione/consenso; uscita: versione/capacità diagnosticate e conclusione esplicita, senza simulare API inesistenti.
3. Pipeline ingest→lint su snapshot con manifest e validatori; uscita: modifiche estranee e raw alterati bloccano apply.
4. Adapter aggiuntivi verificati sulle versioni installate e integrazione stato UI/pubblicazione; uscita: ogni client ha matrice capacità e fallback manuale documentati.

## Accettazione e verifiche previste

- Due lint simultanei sul medesimo vault: un solo scrittore, secondo job in coda, nessun `.tmp` condiviso.
- Stop durante ingest, timeout, cancellazione e crash mantengono output recuperabile senza checkpoint riuscito.
- Editor esterno cambia una nota durante job o tra validazione e apply: conflitto con hash, nessuna sovrascrittura.
- Ingest riuscito ma lint fallito: UI mostra fasi distinte e nessun push automatico; ripresa usa gli stessi riferimenti o crea nuovo job con nuova base.
- Client richiede consenso: stato sospeso; dopo rifiuto nessun bypass. Mock di scritture e ricevuta falsificata viene respinto.
- Una nuova risposta arriva mentre il lint ne consolida altre: solo ID dichiarati nel job vengono consolidati secondo [5](05-stato-condiviso.md).

Comandi dalla root `python installa.py --prova`, `python -m unittest discover -s tests -v`; nel vault sacrificabile `python .graph/build_graph.py --check`, `python .graph/sintesi.py --verifica`. Non sono runner di ingest/lint. Test disponibili `tests/test_dashboard_operations.py` con adapter finto e fault injection: `python -m unittest discover -s tests -p 'test_dashboard_operations.py' -v`; adapter in `tests/test_dashboard_adapters.py`. Smoke AI reali per ciascun client richiedono account e consenso dell'utente e vanno riportati separatamente dai test deterministici; non sono stati eseguiti.

## Handoff locale disponibile (4.1–4.2)

`POST /operations` accetta il corpo sopra; `scope` è una lista esplicita di
`wiki/`, singole note `wiki/Nome.md`, schema, indice o log. Solo `ingest_lint`
richiede fonti `raw/` esistenti; lint/fill_gaps non selezionano nuovi URL.
Massimo otto cicli pendenti per vault. Un solo ciclo viene preparato alla volta;
gli altri restano queued e una base cambiata li blocca, senza riattribuire output.

La risposta espone il percorso della copia, un prompt e il comando del launcher
fidato `teseo_receipt.py --request <request.json> --outcome succeeded|failed|awaiting_user`.
Il mandato contiene UUID, fase, base e capacità locale; il token resta nello storage
locale ignorato e non viene restituito dalle GET. `receipt.json` contiene i byte
hashati della copia: inviarlo a `POST /operations/{id}/complete` come `{receipt: ...}`.
Sessione, Origin e CSRF restano richiesti. Ricevuta identica è idempotente;
riuso con contenuti diversi o hash non corrispondenti viene respinto.
Ingest e lint consumano capacità distinte. Exit 0 del client non completa nulla.

`awaiting_user` richiede `POST /operations/{id}/resume {decision: continue|refuse}`;
solo continue esplicito emette un nuovo mandato. Cancel non arresta una sessione
esterna: l'utente deve fermarla, l'output isolato resta conservato.
`POST /dispatch {}` ricontrolla la coda sotto lock dopo impedimenti esterni.
Timeout di 24 ore viene verificato al completamento; nessun watcher modifica
lo stato durante una GET e nessun replay automatico al riavvio.

`POST /probe-adapters {}` interroga soltanto `--version`, con timeout e senza
shell, per Codex/Claude/Copilot. Non effettua login o richieste a modelli.
Ogni adapter dichiara manual_handoff, automatic_launch=false,
verified_isolation=false, native_callback=false. La presenza del binario o della
versione non prova avvio affidabile, isolamento o callback. Gli hook Stop dei
tre client non generano ricevute. HANDOFF.md include la skill ingest/lint fidata
del runtime e i limiti del mandato; non copia hook o script dal vault collegato.
I consensi della sessione e quelli richiesti dalla skill restano effettivi.

Il launcher ricevute viene installato con le copie fidate delle due skill anche
quando le integrazioni client opzionali non sono selezionate. Le ricevute possono
contenere dati sensibili: non committarle né incollarle in chat pubbliche.

Tre test adapter verificano versioni simulate, assenza/wrapper/timeout e handoff;
sei test HTTP verificano registry, duplicati, token errati, coda, rifiuto e stop.

## Pipeline e checkpoint disponibili (4.3)

Il completamento del lint confronta il manifest della ricevuta con l'intera
copia isolata, non con git diff. Verifica raw preesistenti immutabili, manifest
di identità invariato, assenza di eventi condivisi, perimetro e assenza di
eliminazioni/rinomine. Le nuove fonti vanno predisposte prima del ciclo; nuovi
raw del client vengono respinti. Validazione integrale di schema, tipi, alias,
fonti e link tramite il parser fidato e build su copia. Il launcher fidato
`teseo_validate.py` esegue anche il verificatore reale delle sintesi su una nuova
copia sacrificabile: non apre memoria o domande personali del vault.

Il candidato valido diventa prepared; live Markdown e generazione pubblicata
restano invariati. Il manifest contiene file attribuiti con hash prima/dopo,
fonti selezionate, perimetro, controlli e diff completi (limite 256 KiB, oltre
il quale ridurre il perimetro). Lint parziale è dichiarato nel manifest, non
certifica semanticamente l'intero vault. L'esito semantico rimane dichiarazione
del client sottoposta a revisione umana; i controlli del servizio sono deterministici.

`POST /operations/{id}/apply` richiede `{mode: manual_paused,
external_writers_paused: true, semantic_reviewed: true}` e If-Match della base.
Usa il protocollo locale (Windows e POSIX) e i backup nativi del 3.4, con supporto a nuove
note e rollback esplicito che conserva i byte rimossi nei backup. Nuovi file o
modifiche estranee nella base impediscono l'applicazione; nessuna esclusione
garantita degli editor e nessun apply automatico. `recover` mantiene le stesse
conferme, senza rieseguire ingest o lint.

Solo dopo verifica finale dei byte e generazione valida, una transazione SQLite
registra succeeded e un solo evento locale `operation.validated` nella tabella
`validated_events` del journal. Evento e manifest sono immutabili, con
publication_eligible=true. Ricevuta, Stop, commit, cancellazione o fallimento
non emettono eventi. Non viene eseguito Git; il consumer è il passo 6.
I job in coda si ricontrollano esplicitamente con dispatch; se il primo ha
cambiato i contenuti, il secondo resta bloccato sulla sua base originale.

Diciassette test HTTP esercitano il ciclo completo e replay, evento unico,
raw/scope/manifest/link/alias/sintesi, stop/timeout/dialogo, nuova nota e rollback,
modifiche esterne e script ostili mai eseguiti. Mapping/consolidamento di risposte
rimane bloccato dal passo 5, anche se il client dichiara ID già processati.

La creazione del record e della configurazione iniziale queued è atomica. Un
errore tra pubblicazione del grafo ed evento lascia recovery_required, senza
publication_eligible; finish esplicito può completare la stessa transazione
logica. L'endpoint complete accetta fino a 256 KiB; gli altri corpi restano
limitati a 16 KiB. Nessun aumento globale del limite delle richieste.

## Adapter e UI disponibili (4.4)

Pannello «Cicli ingest e lint»: ciclo/client, fonti raw e perimetro per riga,
creazione idempotente e diagnostica versioni esplicita. Registro operazioni con
fasi separate, mandato, importazione ricevuta JSON, continuazione o rifiuto del
dialogo, cancellazione, manifest/diff e apply/recovery manuali. Nessun pulsante
esegue Git. Il file JSON resta locale (UI fino a 240 KiB) e contiene una capacità
riservata; non condividerlo. Al termine aggiornare la vista e ricontrollare la
coda esplicitamente. Vault legacy senza form di scrittura.

Matrice rilevata il 23 ottobre 2026 tramite i binari installati:

| Client | Versione osservata | Avvio AI / isolamento / callback nativo | Percorso disponibile |
| --- | --- | --- | --- |
| Codex | 0.163.0-alpha.10.2 | Non verificati; disabilitati nel servizio | Handoff e ricevuta locale espliciti |
| Claude Code | 2.1.305 | Non verificati; disabilitati nel servizio | Handoff e ricevuta locale espliciti |
| Copilot CLI | 1.0.83 | Non verificati; disabilitati nel servizio | Handoff e ricevuta locale espliciti |

Probe e protocolli testati; nessun modello/account AI avviato durante le prove.
L'handoff non è una sandbox di sicurezza del client: verificare il suo working
directory e rispettare consensi/installazione della sessione. Il servizio valida
soltanto il candidato e non esegue script provenienti dalla copia.
[Report ECC, prove e limiti](evidence/step-4/verification.md).

## Rollout, rollback e questioni aperte

Rollout manuale con ricevuta completato. Automazione futura soltanto per client
con avvio/isolamento/callback dimostrati e policy esplicita; non derivarla da Stop.
Mapping/consolidamento risposte e record condivisi attendono il passo 5.
Rollback: cancellare i cicli non applicati conservando output; per apply
interrotti usare recovery esplicito senza annullare modifiche estranee.
Snapshot, ricevute ed eventi locali restano conservati; retention futura.

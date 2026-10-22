# 4 — Coordinamento delle skill ingest e lint

Stato: progetto futuro; richiede [1](01-contratto-dati-operazioni.md) e [2](02-dashboard-consultazione.md). Obiettivo: avviare dal servizio un lavoro riconoscibile, ricevere un esito verificabile e rendere pubblicabile soltanto il checkpoint attribuibile al ciclo concluso ingest+lint.

## Contesto attuale e scope

[Ingest](../kit/skills/obsidian-wiki-ingest/SKILL.md) legge fonti, aggiorna note, schema/indice e log e propone lint/lacune. [Lint](../kit/skills/obsidian-wiki-lint/SKILL.md) controlla contraddizioni, può creare sintesi e consolida risposte; contiene limiti sulle riscritture ampie e consensi da rispettare. Sono procedure del client, non comandi CLI indipendenti. [chiedi_codex.py](../kit/graph/chiedi_codex.py) usa sessione effimera readonly per query: non è un runner per scritture. Il ramo `Stop` di [codex_hook.py](../kit/graph/codex_hook.py) chiude memoria/turno; non certifica ingest o lint riusciti. Esaminare anche [claude_hook.py](../kit/graph/claude_hook.py) e [copilot_hook.py](../kit/graph/copilot_hook.py) per adattare ciascun client senza equipararne gli eventi.

Scope: lifecycle di job, adapter e completamento, attribuzione dei file e policy. Lacune con dialogo utente possono sospendere il job e non vanno simulate. Autenticazione AI rimane quella del client installato; nessun nuovo account provider nella dashboard e nessun SDK dato per supportato.

## Protocollo e componenti futuri

`operations.py` orchestra; `adapters/` implementa protocollo `probe`, `prepare`, `launch_or_handoff`, `cancel`, `collect_receipt`. Il probe registra versione rilevata, capacità effettivamente provate, supporto avvio/isolamento/callback e requisiti di consenso. Se non esiste un'interfaccia affidabile, produrre un handoff esplicito alla chat: prompt operativo con UUID e comando di completamento futuro. Stato «in attesa del client» resta visibile; non chiamarlo avvio automatico.

Proposta API:

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

Comandi **esistenti** dalla root `python installa.py --prova`, `python -m unittest discover -s tests -v`; nel vault sacrificabile `python .graph/build_graph.py --check`, `python .graph/sintesi.py --verifica`. Non sono runner di ingest/lint. Test **da creare** `tests/test_dashboard_operations.py` con adapter finto e fault injection; esecuzione futura `python -m unittest discover -s tests -p 'test_dashboard_operations.py' -v`. Smoke reali per ciascun client richiedono account e consenso dell'utente e vanno riportati separatamente dai test deterministici. Nulla di ciò è dichiarato già eseguito.

## Rollout, rollback e questioni aperte

Attivare prima handoff manuale con ricevuta, poi automazione per client provati. Conservare la possibilità di eseguire skill nella chat; le operazioni esterne non diventano automaticamente pubblicabili. Rollback disabilita nuovi job e adapter, lascia i job esistenti in recovery e conserva manifest/backup. Non annullare file modificati dall'utente. Da verificare: avvio e isolamento reali dei tre client e disponibilità di un segnale esplicito supportato; se manca, usare protocollo manuale locale anziché dipendere da eventi generici.

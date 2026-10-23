# 5 — Risposte e decisioni condivise

Stato: formato/DAG/proiezione (5.1), migrazione selettiva e API (5.2), consolidamento per UUID e checkpoint (5.3) e UI/ripristino (5.4) implementati. Il publisher Git resta al passo 6. Dipendenze: [contratto 1](01-contratto-dati-operazioni.md), [dashboard 2](02-dashboard-consultazione.md) e [coordinator 4](04-coordinamento-ingest-lint.md). Obiettivo: una risposta o decisione utile alla collaborazione attraversa i clone senza scambiare SQLite, sessioni o memoria personale.

## Stato attuale e scope

[domande.py](../kit/graph/domande.py), `apri`, crea `poste`, `scartate`, `aperte`, `risposte`. Gli ID risposta legacy sono interi locali; il precedente ramo CLI `--consolida` massivo è disabilitato. [memoria.py](../kit/graph/memoria.py) conserva domande apprese, pagine lette, sospese e telemetria dei turni. [Wiki reference.md](../kit/vault/Wiki%20reference.md) raccomanda il backup dei due DB perché contengono storia non rigenerabile: il nuovo formato deve migrare quella storia con selezione esplicita, non ignorarla.

Scope: risposte dell'autore, decisioni, rinvii condivisi e motivi degli scarti utili al gruppo. Restano locali `poste`, sessioni, turni, token, apprendimenti personali e preferenze. Memoria personale locale per default; export selettivo futuro distinto. Le domande derivate dalle note continuano a essere ricalcolate; gli eventi conservano identità e decisioni, senza sostituire i fatti nelle note.

## Formato eventi e identità

Un file JSON UTF-8 per evento immutabile in `.teseo/shared/events/<event_id>.json` riduce contese fra file. Canonicalizzazione definita nel contratto (ordinamento chiavi, encoding e newline) per hash ripetibili. Non usare un JSONL unico da appendere insieme. Esempio puramente progettuale:

```json
{
  "format_version": 1,
  "vault_id": "11111111-1111-4111-8111-111111111111",
  "event_id": "22222222-2222-4222-8222-222222222222",
  "kind": "answer.recorded",
  "entity_id": "33333333-3333-4333-8333-333333333333",
  "question_id": "44444444-4444-4444-8444-444444444444",
  "operation_id": "55555555-5555-4555-8555-555555555555",
  "author_id": "66666666-6666-4666-8666-666666666666",
  "created_at": "2026-10-23T10:00:00Z",
  "parents": ["77777777-7777-4777-8777-777777777777"],
  "payload": {"text":"Il referente è Anna", "pages":["Incident settimanale"], "source":"nota-utente"}
}
```

Schema minimo comune include anche `author_id` pseudonimo locale e `created_at` informativo; non usare clock o autore come autorità di ordinamento. `parents` dichiara causalità. Tipi iniziali: `question.registered`, `question.deferred`, `question.decided`, `synthesis.discarded`, `answer.recorded`, `answer.superseded`, `answer.consolidated`, `page.renamed`. Schema per tipo con dimensioni massime, riferimenti obbligatori e rifiuto di eseguibili. Un UUID risposta è globale, diverso dall'intero SQLite storico. Un ID domanda è stabile e ha ancore a pagina/segnale; un mapping collega le chiavi calcolate legacy senza usare esclusivamente il testo mutabile.

Risposte distinte alla stessa domanda restano distinte. Eventi duplicati con stesso ID e hash sono no-op; stesso ID e contenuto diverso è errore bloccante. Non fondere risposte per uguaglianza del testo. Mapping rinomine permette di ritrovare le pagine senza riscrivere eventi storici. Una domanda derivata scomparsa è chiusa nel calcolo, ma riaprirla conserva storia. Due rinvii concorrenti con stesso parent producono conflitto decisionale, non due incrementi automatici del conteggio; l'utente sceglie una nuova decisione causale che li ricomprende.

## Proiezione e consolidamento

`shared_state.py` valida eventi, deduplica per ID/hash, costruisce DAG causale, importa in una transazione SQLite e registra `applied_events`. Eventi arrivati prima dei parent rimangono pending visibili; parent assente nel candidato completo impedisce la pubblicazione di stato consistente. Cicli, vault diverso e versioni incompatibili bloccano import. Ordinamento topologico con tie-break deterministico per ID serve alla riproducibilità; eventi decisionali incompatibili concorrenti diventano stato `needs_decision`, mai last-write-wins basato sul clock.

La modalità indiscriminata `--consolida` è sostituita da `--consolida-id UUID --operazione UUID --request <mandato>` e dal servizio. `answer.consolidated` cita soltanto gli ID processati, hash delle note risultanti e `checkpoint_id` logico UUID dell'operazione. Non contiene l'OID del commit che includerà l'evento: introdurrebbe un riferimento circolare. Il mapping UUID→OID è registrato dal publisher nel journal locale ed è ricostruibile dai metadati del commit. Nessun evento dichiara consolidate risposte arrivate dopo lo snapshot. La UI distingue «risposta archiviata», «applicata alle note» e «pubblicata».

Atomicità logica: preparare note modificate ed eventi di consolidamento nello stesso candidato; validare che note e fonti giustifichino il consolidamento; applicare con journal del passo 1 e marker di checkpoint; solo dopo importare la proiezione locale. Dopo crash prima del marker, recovery completa o ripristina quel candidato senza marcare risposte isolate. Se note+eventi sono già applicati e SQLite no, replay idempotente. Non pretendere atomicità nativa tra file e DB. Nel commit Git futuro note ed eventi di consolidamento appartengono allo stesso albero.

## Migrazione e API

Procedura su backup consistente: censire righe legacy, mostrare dati personali e condivisibili, scegliere export, assegnare UUID e salvare localmente mappa `(vault_id,legacy_db_identity,table,row_id) → uuid`. Un secondo export usa la stessa mappa. Non derivare l'identità dal solo row ID di due clone. Se DB già copiati fra persone non hanno provenienza affidabile, proporre deduplica revisionabile, non eliminazione automatica. Conservare campi e record esclusi nei DB locali con backup.

Endpoint disponibili: `GET /api/v1/vaults/{id}/answers` elenca stato; `POST /answers` registra risposta e UUID; `POST /shared-state/export-preview` mostra diff e privacy; `POST /shared-state/import` avvia job su candidato validato. Nessuna POST accetta SQL o file da eseguire. La selezione di cosa condividere è esplicita prima della prima pubblicazione e resta configurazione; nessun export silenzioso della telemetria.

## Incrementi da una PR

1. Schema eventi, DAG, fixture e import idempotente; uscita: stesso insieme in ordini diversi produce stessa proiezione/conflitti.
2. Migrazione legacy con preview e mapping persistente; uscita: secondo export no-op e DB originale conservato.
3. Consolidamento per UUID e checkpoint note/eventi integrato al passo 4; uscita: risposta sopraggiunta resta pendente.
4. UI stato risposte e decisioni conflittuali, backup/ripristino documentato; uscita: nessun dato personale condiviso per default.

## Accettazione e prove previste

Due clone registrano risposte diverse e importano in ordine inverso: nessuna perdita, conflitto sostanziale visibile. Doppio replay non incrementa rinvii, non duplica risposte né crea commit. Crash tra note, eventi e SQLite viene recuperato. Rinomina pagina mantiene riferimenti storici. Testare ID duplicato malizioso, parent mancante/ciclico, versione futura, risposte consolidate concorrenti e contraddizione con fonti. Il grafo ricostruito e lo stato condiviso ricostruito sono uguali dopo clonazione pulita; la memoria personale resta diversa legittimamente.

Comandi nel vault: `python .graph/domande.py --risposte` legge le pendenti; `python .graph/domande.py --stato` può sincronizzare stato locale e non è audit readonly; `--consolida` massivo è disabilitato; usare UUID e mandato. Regressioni root: `python -m unittest discover -s tests -v`. Test disponibili `tests/test_dashboard_shared_state.py`, comando `python -m unittest discover -s tests -p 'test_dashboard_shared_state.py' -v`. Prove reali e limiti nelle evidenze del passo 5.

## Funzionalità disponibili (5.1–5.2)

`shared_state.py`: otto tipi iniziali, campi comuni obbligatori, UUID canonici,
timestamp UTC informativo, payload stretti e byte canonici. Limiti: 2048 eventi,
64 KiB per evento, 128 parent. DAG deterministico; missing parent pending,
cicli/collisioni/versioni incompatibili bloccanti. La proiezione mantiene risposte
distinte e conflitti causali; mapping page.renamed senza riscrivere eventi.
`import_events` accumula idempotentemente; `rebuild_projection` rigenera la cache
esatta dopo rollback. File JSON restano l'autorità, SQLite locale è rigenerabile.

`GET /answers` legge soltanto eventi, senza aprire DB personali. `POST /answers`
richiede question_id (o null con question_text), pages, text, idempotency_key e
share_confirmed=true. Decisioni: `/shared-state/decision` con question_id, tutti
gli heads correnti, decision open/reopen/closed/accepted/rejected/defer, reason,
chiave e consenso. Versioni concorrenti richiedono un nuovo evento causale;
nessun last-write-wins. `/shared-state/import {}` ricostruisce la cache locale.

`/shared-state/export-preview {}` crea un backup SQLite consistente di domande,
confronto delle righe e censimento delle esclusioni. Memoria personale non aperta;
originali conservati. `/shared-state/export` richiede preview_id, selection_ids,
idempotency_key e share_confirmed=true. Nessuna selezione implicita; UUID e
provenienza locale persistono, un secondo export è no-op sui file. DB copiati
senza storia affidabile producono un avviso e identità distinte, mai deduplica
automatica per uguaglianza del testo. Fonte modificata/WAL cambiato impone nuova
preview. Backup, mapping e ricevute restano `.teseo/local/` ignorata da Git.

Append esclusivo di nuovi UUID, richieste persistite prima dei file: interruzione
fra eventi si riprende con la stessa chiave, senza sovrascrivere dati esistenti.
Durante awaiting_client nuove risposte sono ammesse; apply/recovery parziale
blocca lo stato condiviso. Pubblicazione resta unknown fino al passo 6.

## Consolidamento disponibile (5.3)

Il mandato contiene `SHARED_ANSWERS.json` della sola copia isolata. La ricevuta
del lint dichiarata riuscita può indicare `--consolida-id UUID` ripetibili, con
`--operazione UUID` corrispondente al mandato. Anche `domande.py` offre questi
argomenti insieme a `--request`; `--consolida` massivo è disabilitato prima di
qualsiasi apertura DB. Le risposte legacy restano negli originali: prima export
selettivo, poi consolidamento degli UUID condivisi. Skill e template aggiornati.

Il coordinator verifica UUID presenti e pendenti nello snapshot iniziale,
assenza di conflitti irrisolti e presenza testuale della risposta nel corpo di
almeno una nota modificata fra quelle indicate, con fonte `nota-utente`.
Questa è una prova deterministica conservativa, non certificazione semantica:
resta richiesta la revisione umana dell'apply. Eventi scritti dal client sono
respinti; soltanto il servizio prepara `answer.consolidated` con UUID selezionati,
hash delle note, ID operazione e checkpoint UUID identico a quello del journal.

Una risposta nuova durante il lint può essere aggiunta alla base e al candidato
senza entrare negli UUID processati. Il rebase accetta soltanto nuove registrazioni
domanda/risposta, preservando ogni byte preesistente. Modifiche a note/raw/identità,
nuove decisioni o consolidamenti rendono il ciclo obsoleto e lo bloccano.
Le ricevute restano legate alla base iniziale; l'apply usa quella aggiornata.

Note prima degli eventi, poi marker del checkpoint e cache locale ricostruibile.
Crash prima del marker non attesta risposte applicate; finish/rollback espliciti
gestiscono lo stesso candidato. Se manca solo la cache, `/shared-state/import`
la ricostruisce idempotentemente. Hash storico diverso dopo un successivo edit
non cancella una attestazione riuscita: la UI distingue storia e verifica corrente.
Checkpoint concorrenti: decisione causale accepted su tutte le teste, poi nuovo
lint sugli UUID interessati e nuovo checkpoint validato; nessuna scelta per clock.

Verificati clone pulito con stesso digest/proiezione/grafo, DB personali assenti,
risposta sopraggiunta pendente, guasto prima del marker e dopo il marker, rollback
della cache, eventi client respinti e cancellazione della copia durante i controlli.

Primo rilascio in shadow mode: export-preview senza push, confronto conteggi e campi con legacy; poi import su copia nuova e consolidamento per ID. Non attivare sync prima di completare questo gate. Rollback conserva eventi e DB originali; per tornare al vecchio kit occorre ripristinare un backup compatibile senza eliminare storia nuova. La riservatezza del testo risposte e la distribuzione dei raw sono decisioni del gruppo; la selezione non rimuove dati già presenti nella storia Git. Aperto: gestione redazioni di dati sensibili già condivisi, da trattare come procedura dedicata e non come normale delete di evento immutabile.

## UI e procedure disponibili (5.4)

Pannello «Risposte e decisioni condivise»: stato, motivi degli scarti e cronologia
delle decisioni/rinvii, nuova risposta con consenso, scelta della domanda,
rinvio/decisione causali con motivo e teste osservate. Distinti archiviata,
applicata e pubblicazione non verificata. Le domande derivate continuano a essere
ricalcolate dagli strumenti del vault; il registro condiviso conserva identità
e decisioni e non sostituisce i fatti nelle note.

Preview privacy separata dall'export, nessuna riga inizialmente selezionata,
avviso di provenienza non certificata. Massimo 1000 righe per tabella e 2 MiB
di preview, 200 righe visualizzate/selezionabili nella UI; nessuna selezione
implicita delle altre. Righe il cui JSON supera 24000 caratteri non sono
esportabili dalla UI senza una revisione completa su copia. Il backend non
tronca un export dichiarandolo completo. Rinvii storici selezionati conservano
il conteggio attraverso eventi causali distinti (massimo 128).

Una risoluzione causale resta valida dopo rinvii successivi che ne discendono;
una risposta divergente nuova riapre il conflitto. Parent mancanti restano
pending visibili e bloccano checkpoint completi. Conflitti sui mapping di pagina
sono esposti senza riscrivere automaticamente file o storia: richiedono un
mapping causale revisionato. L'editor di rinomina fisica delle pagine resta
distinto dal formato degli eventi storici.

### Backup e ripristino

La preview conserva backup SQLite consistente e manifest in
`.teseo/local/shared-migration/<preview_id>/`. Il manifest riporta identità,
digest logico, campi ed esclusioni. Originale domande e memoria personale non
vengono alterati; la memoria non è aperta né esportata automaticamente.

Per ricostruire soltanto lo stato condiviso: conservare i JSON immutabili,
arrestare scrittori esterni, usare «Ricostruisci proiezione locale» o POST import.
Cache e mapping locali non sono il materiale da scambiare tra clone. Per un
apply interrotto usare finish/rollback del journal; non copiare singole note o
marcare manualmente risposte nel DB. Output e backup restano conservati.

Se serve recuperare il vecchio archivio personale, fermare prima dashboard,
client e hook, conservare anche una copia dell'archivio attuale e dei sidecar
WAL/SHM; ripristinare il backup consistente su una copia separata e verificarlo
prima di sostituire l'originale. Non ripristinare una vecchia cache condivisa
come autorità e non cancellare JSON già distribuiti: la redazione storica
richiede una procedura dedicata. Nessun restore distruttivo è automatico.

[Evidenze ECC e verifiche](evidence/step-5/verification.md). Nessuna memoria
personale condivisa per default, nessun avvio AI o push Git dalla UI.

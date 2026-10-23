# 5 — Risposte e decisioni condivise

Stato: formato, DAG e proiezione idempotente implementati (5.1); migrazione, consolidamento e UI in completamento. Il formato e l'import dipendono dal [contratto 1](01-contratto-dati-operazioni.md); API/UI richiedono [dashboard 2](02-dashboard-consultazione.md), il consolidamento completo richiede [coordinator 4](04-coordinamento-ingest-lint.md). Obiettivo: una risposta o decisione utile alla collaborazione attraversa i clone senza scambiare SQLite, sessioni o memoria personale.

## Stato attuale e scope

[domande.py](../kit/graph/domande.py), `apri`, crea `poste`, `scartate`, `aperte`, `risposte`. Gli ID risposta sono interi locali; il ramo CLI `--consolida` aggiorna oggi tutte le risposte pendenti. [memoria.py](../kit/graph/memoria.py) conserva domande apprese, pagine lette, sospese e telemetria dei turni. [Wiki reference.md](../kit/vault/Wiki%20reference.md) raccomanda il backup dei due DB perché contengono storia non rigenerabile: il nuovo formato deve migrare quella storia con selezione esplicita, non ignorarla.

Scope: risposte dell'autore, decisioni, rinvii condivisi e motivi degli scarti utili al gruppo. Restano locali `poste`, sessioni, turni, token, apprendimenti personali e preferenze. Memoria personale locale per default; export selettivo futuro distinto. Le domande derivate dalle note continuano a essere ricalcolate; gli eventi conservano identità e decisioni, senza sostituire i fatti nelle note.

## Formato futuro e identità

Un file JSON UTF-8 per evento immutabile in `.teseo/shared/events/<event_id>.json` riduce contese fra file. Canonicalizzazione definita nel contratto (ordinamento chiavi, encoding e newline) per hash ripetibili. Non usare un JSONL unico da appendere insieme. Esempio puramente progettuale:

```json
{
  "format_version": 1,
  "vault_id": "uuid-vault",
  "event_id": "uuid-evento",
  "kind": "answer.recorded",
  "entity_id": "uuid-risposta",
  "question_id": "uuid-domanda",
  "operation_id": "uuid-operazione",
  "parents": [],
  "payload": {"text":"Il referente è Anna", "pages":["Incident settimanale"], "source":"nota-utente"}
}
```

Schema minimo comune include anche `author_id` pseudonimo locale e `created_at` informativo; non usare clock o autore come autorità di ordinamento. `parents` dichiara causalità. Tipi iniziali: `question.registered`, `question.deferred`, `question.decided`, `synthesis.discarded`, `answer.recorded`, `answer.superseded`, `answer.consolidated`, `page.renamed`. Schema per tipo con dimensioni massime, riferimenti obbligatori e rifiuto di eseguibili. Un UUID risposta è globale, diverso dall'intero SQLite storico. Un ID domanda è stabile e ha ancore a pagina/segnale; un mapping collega le chiavi calcolate legacy senza usare esclusivamente il testo mutabile.

Risposte distinte alla stessa domanda restano distinte. Eventi duplicati con stesso ID e hash sono no-op; stesso ID e contenuto diverso è errore bloccante. Non fondere risposte per uguaglianza del testo. Mapping rinomine permette di ritrovare le pagine senza riscrivere eventi storici. Una domanda derivata scomparsa è chiusa nel calcolo, ma riaprirla conserva storia. Due rinvii concorrenti con stesso parent producono conflitto decisionale, non due incrementi automatici del conteggio; l'utente sceglie una nuova decisione causale che li ricomprende.

## Proiezione e consolidamento

Futuro `shared_state.py` valida eventi, deduplica per ID/hash, costruisce DAG causale, importa in una transazione SQLite e registra `applied_events`. Eventi arrivati prima dei parent rimangono pending visibili; parent assente nel candidato completo impedisce la pubblicazione di stato consistente. Cicli, vault diverso e versioni incompatibili bloccano import. Ordinamento topologico con tie-break deterministico per ID serve alla riproducibilità; eventi decisionali incompatibili concorrenti diventano stato `needs_decision`, mai last-write-wins basato sul clock.

Sostituire la modalità indiscriminata `--consolida` con comando futuro per ID (`--consolida-id UUID --operazione UUID`, sintassi da introdurre) e servizio equivalente. `answer.consolidated` cita soltanto gli ID processati, hash delle note risultanti e `checkpoint_id` logico UUID dell'operazione. Non contiene l'OID del commit che includerà l'evento: introdurrebbe un riferimento circolare. Il mapping UUID→OID è registrato dal publisher nel journal locale ed è ricostruibile dai metadati del commit. Nessun evento dichiara consolidate risposte arrivate dopo lo snapshot. La UI distingue «risposta archiviata», «applicata alle note» e «pubblicata».

Atomicità logica: preparare note modificate ed eventi di consolidamento nello stesso candidato; validare che note e fonti giustifichino il consolidamento; applicare con journal del passo 1 e marker di checkpoint; solo dopo importare la proiezione locale. Dopo crash prima del marker, recovery completa o ripristina quel candidato senza marcare risposte isolate. Se note+eventi sono già applicati e SQLite no, replay idempotente. Non pretendere atomicità nativa tra file e DB. Nel commit Git futuro note ed eventi di consolidamento appartengono allo stesso albero.

## Migrazione e API future

Procedura su backup consistente: censire righe legacy, mostrare dati personali e condivisibili, scegliere export, assegnare UUID e salvare localmente mappa `(vault_id,legacy_db_identity,table,row_id) → uuid`. Un secondo export usa la stessa mappa. Non derivare l'identità dal solo row ID di due clone. Se DB già copiati fra persone non hanno provenienza affidabile, proporre deduplica revisionabile, non eliminazione automatica. Conservare campi e record esclusi nei DB locali con backup.

Endpoint futuri: `GET /api/v1/vaults/{id}/answers` elenca stato; `POST /answers` registra risposta e UUID; `POST /shared-state/export-preview` mostra diff e privacy; `POST /shared-state/import` avvia job su candidato validato. Nessuna POST accetta SQL o file da eseguire. La selezione di cosa condividere è esplicita prima della prima pubblicazione e resta configurazione; nessun export silenzioso della telemetria.

## Incrementi da una PR

1. Schema eventi, DAG, fixture e import idempotente; uscita: stesso insieme in ordini diversi produce stessa proiezione/conflitti.
2. Migrazione legacy con preview e mapping persistente; uscita: secondo export no-op e DB originale conservato.
3. Consolidamento per UUID e checkpoint note/eventi integrato al passo 4; uscita: risposta sopraggiunta resta pendente.
4. UI stato risposte e decisioni conflittuali, backup/ripristino documentato; uscita: nessun dato personale condiviso per default.

## Accettazione e prove previste

Due clone registrano risposte diverse e importano in ordine inverso: nessuna perdita, conflitto sostanziale visibile. Doppio replay non incrementa rinvii, non duplica risposte né crea commit. Crash tra note, eventi e SQLite viene recuperato. Rinomina pagina mantiene riferimenti storici. Testare ID duplicato malizioso, parent mancante/ciclico, versione futura, risposte consolidate concorrenti e contraddizione con fonti. Il grafo ricostruito e lo stato condiviso ricostruito sono uguali dopo clonazione pulita; la memoria personale resta diversa legittimamente.

Comandi **esistenti** nel vault: `python .graph/domande.py --risposte` legge le pendenti; `python .graph/domande.py --stato` può sincronizzare stato locale e non è audit readonly; `--consolida` attuale è mutante e non va usato per simulare il nuovo contratto. Regressioni root: `python -m unittest discover -s tests -v`. Test **da creare** `tests/test_dashboard_shared_state.py`, comando futuro `python -m unittest discover -s tests -p 'test_dashboard_shared_state.py' -v`. Nessuna migrazione o prova runtime è stata eseguita per questi documenti.

## Rollout, rollback e rischi

Primo rilascio in shadow mode: export-preview senza push, confronto conteggi e campi con legacy; poi import su copia nuova e consolidamento per ID. Non attivare sync prima di completare questo gate. Rollback conserva eventi e DB originali; per tornare al vecchio kit occorre ripristinare un backup compatibile senza eliminare storia nuova. La riservatezza del testo risposte e la distribuzione dei raw sono decisioni del gruppo; la selezione non rimuove dati già presenti nella storia Git. Aperto: gestione redazioni di dati sensibili già condivisi, da trattare come procedura dedicata e non come normale delete di evento immutabile.

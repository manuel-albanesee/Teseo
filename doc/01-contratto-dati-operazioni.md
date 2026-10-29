# 1 — Contratto dei dati e delle operazioni

> Apply automatico: non previsto ([decisione](13-decisione-apply-automatico.md)).

Primo incremento disponibile in `kit/dashboard/contracts.py`: versioni e manifest,
classificazione percorsi e canonicalizzazione JSON. Dettagli e limiti nel
[registro implementazioni](08-analisi-avanzamento.md). Disponibili anche journal,
lock kernel e snapshot in `kit/dashboard/storage.py` (incremento 1.2);
Disponibili generazioni immutabili, lettori readonly e backup SQLite nel passo
1.4; apply protetto delle note e recovery multi-file restano futuri. Consultare
il registro per la distinzione tra vault compatibili e legacy.

Stato: implementato (contratti, journal, lock, snapshot, generazioni, backup); apply protetto e recovery multi-file sono nei passi 3–5. Prerequisito dei passi successivi. Obiettivo: rendere verificabile cosa viene letto, modificato, condiviso e ripristinato. L'utente vede una revisione coerente e conserva l'ultima vista valida quando una modifica fallisce.

## Contesto verificato e confini

Il [README](../README.md) descrive Python, PyYAML, SQLite e vault installati con `raw/`, `wiki/*.md`, schema, index e log. [build_graph.py](../kit/graph/build_graph.py), funzioni `leggi_vocabolario` e `costruisci`, legge le prime tre colonne della tabella «Relazioni tipizzate», tratta ogni proprietà non speciale come relazione e usa lo stem del filename come ID. Usa un `.tmp` fisso e sostituisce il DB prima che `main` restituisca l'errore di `--check`: oggi un controllo semantico fallito può già avere pubblicato il grafo. [recall_hook.py](../kit/graph/recall_hook.py) ricostruisce quando rileva file più recenti e chiama direttamente `costruisci`.

[memoria.py](../kit/graph/memoria.py) conserva apprendimento, letture e turni; [domande.py](../kit/graph/domande.py) conserva risposte, rinvii, scarti e sessioni. Questi due DB attuali non sono ricostruibili dalle sole note. Il contratto non deve cancellarli scambiandoli per cache. Scope: fondazioni locali, formati e protocollo di applicazione; esclusi UI, OAuth, merge semantico generale e realizzazione degli adapter.

## Dati e versioni proposti

| Categoria | Autorità | Condivisione e recupero |
| --- | --- | --- |
| Note, schema, index, log | Markdown nel vault | Versionati nel repo dati |
| Fonti selezionate | File `raw/` immutabili | Aggiunte consentite; preesistenti protetti per hash e percorso |
| Risposte/decisioni condivise | Eventi `.teseo/shared/events/*.json` | Specifica del [passo 5](05-stato-condiviso.md); SQLite è proiezione |
| Grafo | Generazione derivata da snapshot | Escluso da Git, ricostruibile |
| Memoria personale e stato legacy | SQLite locale | Backup consistente, personale per default |
| Credenziali, sessioni, lock, log tecnici | Stato locale | Mai nel repo dati né nei prompt non necessari |

Esempio futuro `.teseo/project.json`:

```json
{"format_version":1,"vault_id":"uuid","schema_version":1,"event_version":1,"minimum_kit_version":"DA_DEFINIRE","shared_paths":["wiki/","raw/","Wiki reference.md","index.md","log.md",".teseo/shared/"]}
```

La versione minima sarà assegnata dal rilascio che introduce il contratto. Il servizio espone supporto per intervalli espliciti: major sconosciuta blocca le scritture/import, lettura solo se parser compatibile; campo opzionale sconosciuto preservato. Versioni di trasporto API, schema dominio, formato eventi e kit sono distinte. Nessuna modifica dello schema avviene solo cambiando un numero nel manifest. Migrazioni richiedono preview e backup. Mancanza del manifest in vault legacy apre modalità readonly e procedura di adozione, non migrazione implicita.

Canonicalizzazione eventi v1: JSON UTF-8 senza BOM, oggetto radice, chiavi univoche ordinate ricorsivamente per punti di codice Unicode, nessuno spazio fuori dalle stringhe e un solo LF finale. Stringhe e chiavi devono essere NFC; rifiutare input non NFC senza normalizzarlo silenziosamente dopo aver assegnato l'identità. Escape di virgolette, backslash e caratteri di controllo secondo JSON, altri caratteri emessi in UTF-8; vietati surrogate isolati. Valori ammessi: oggetti, array (ordine preservato), stringhe, booleani, null e interi fra −(2^53−1) e 2^53−1; nessun float/NaN. SHA-256 calcolato su tutti i byte canonici, LF incluso, di tutti i campi dell'evento; l'hash resta in journal/proiezione, fuori dall'evento stesso. Campi opzionali sconosciuti compatibili sono inclusi e preservati. Schema e fixture devono fissare i byte attesi, anche per accenti, escape e interi limite.

Configurazioni portabili sono dati dichiarativi allowlist, senza percorsi assoluti. Hook, skill e script ricevuti non sono configurazioni portabili da attivare. Credenziali restano nel credential manager Git/gh di ciascun utente.

## Protocollo operativo e moduli futuri

`kit/dashboard/contracts.py` definisce DTO e validatori; `storage.py` gestisce snapshot, lock e journal; `graph_service.py` costruisce generazioni. Ogni record locale di operazione contiene `operation_id`, `vault_id`, `kind`, `base_git_revision` anche null senza Git, `base_content_digest`, `schema_digest`, hash prima/dopo per percorso, elenco letture, stato, errore strutturato e checkpoint. UUID identifica l'operazione; digest del contenuto identifica lo snapshot anche con working tree non committato. L'UUID è l'identificatore logico (API, ref Git, eventi, journal); le copie su disco stanno in `.teseo/local/snapshots/<token>/`, dove `<token>` sono i primi 16 caratteri esadecimali dell'UUID (`dir_token` in `contracts.py`), per restare sotto MAX_PATH su Windows senza percorsi lunghi. Il percorso reale è quello salvato nel record (`snapshot_path`, `checkpoint.candidate_path`), mai ricavato dall'id: i record con cartelle a UUID intero restano validi. La cartella foglia è creata in modo esclusivo (`snapshot_exists` se già presente).

Stati: `created → waiting_lock → running → validating → prepared → applying → succeeded`; uscite `failed`, `cancelled`, `blocked_external_change`, `recovery_required`. `succeeded` certifica l'applicazione locale; pubblicazione remota è un record collegato separato. Richieste ripetute con stessa chiave idempotente e stesso payload restituiscono lo stesso job; payload diverso con stessa chiave dà conflitto.

Serializzare tutti gli scrittori gestiti per vault tramite lock di sistema e journal persistente. PID da solo non autorizza rimozione di un lock: verificare identità del processo e recovery. Ordinamento: lock vault, snapshot, build, checkpoint, promozione; nessun job mantiene un lock durante attesa di risposta umana o autenticazione. Hook e CLI esistenti devono adottare lo stesso coordinatore o modalità di compatibilità che rinvia il rebuild. Due lint sullo stesso vault: uno esegue, l'altro rimane in coda; annullamento non cancella modifiche estranee.

Lock locale non protegge da editor esterni: rilevare modifiche con watcher più scansione hash prima di ogni apply. Includere file nuovi, eliminazioni, rename, schema e raw, non solo mtime. Rifiutare path traversal, symlink/junction fuori root, collisioni case-insensitive e nomi incompatibili con Windows. Il watcher è un segnale; il digest è il controllo di precondizione.

Il controllo hash seguito da replace ha una finestra di race: non è un compare-and-swap atomico sul file. Per abilitare apply automatico occorre protocollo cooperativo di tutti gli scrittori attivi oppure meccanismo di esclusione dei file/namespace dimostrato sulla piattaforma, inclusi salvataggi via temp+rename. Non presumere che il lock del servizio sia rispettato da Obsidian. Se l'esclusione non è disponibile, indicare modalità non protetta e richiedere sospensione degli scrittori esterni prima dell'apply; la sola quiete dei file non dà tale garanzia. Il supporto ad editor non cooperanti rimane un limite esplicito del primo rilascio; l'utente può tenere il receiver in sola rilevazione durante editing. Il gate di piattaforma deve iniettare scritture proprio tra controllo e sostituzione e provarne il blocco; se fallisce, disabilitare apply automatico in quella modalità.

## Build, pubblicazione e recovery

Separare `parse_snapshot`, `validate_snapshot`, `build_candidate`, `publish_generation`. Il candidato è costruito da copia stabile e usa temporaneo unico per operazione, chiuso prima della validazione SQLite. YAML invalido, link, alias, tipi, fonti, schema ed eventi invalidi impediscono la pubblicazione. Rivalutare digest prima di promuovere; se cambia, scartare il candidato e ricostruire con retry limitato.

Proposta preferita: DB immutabili per generazione in `.teseo/local/graphs/<digest>.sqlite` e manifest locale atomico della generazione corrente. I lettori acquisiscono il percorso da quel manifest, aprono readonly e chiudono presto; una richiesta usa una sola generazione. Questo evita di dover sostituire su Windows un SQLite tenuto aperto. I vecchi DB sono eliminati solo quando non hanno lettori; errore di eliminazione rinvia la pulizia. Se l'atomic rename del piccolo manifest fallisce, resta attiva la vecchia generazione. Aggiornare tutti i lettori/hook; finché usano `.graph/graph.sqlite`, prevedere esplicita compatibilità con sostituzione a lettori chiusi e retry, senza promettere sicurezza prima di averla verificata su Windows. WAL da solo non risolve la sostituzione del file.

Per più file note/eventi non esiste atomicità filesystem globale: salvare journal `prepared` con hash e copie prima/dopo, poi applicare solo alle precondizioni previste e nella modalità di esclusione dichiarata, scrivere marker di checkpoint completato e ricostruire le proiezioni. Le API non espongono uno snapshot a metà; lettori esterni possono vedere il transitorio, che va ridotto e documentato. Al riavvio completare o ripristinare solo file ancora corrispondenti agli hash dell'operazione e riacquisendo la protezione di scrittura; interventi esterni rilevati portano a `recovery_required`. In modalità non protetta non promettere recupero di una scrittura sfuggita ai controlli. Un backup dei DB personali usa un metodo consistente SQLite, non semplice copia di un DB in scrittura.

## Incrementi da una PR

1. Introdurre versioni, parser e fixture legacy/nuove; nessuna migrazione automatica. Uscita: classificazione completa dei percorsi e errori strutturati.
2. Implementare journal, lock e snapshot con iniezione guasti. Uscita: due scrittori non applicano insieme e una modifica esterna invalida il candidato.
3. Separare builder/validator/publisher, adattando i chiamanti esistenti. Uscita: `--check` fallito non sostituisce una generazione valida.
4. Portare lettori alla generazione dichiarata e introdurre recovery/backup. Uscita: lettore aperto su Windows e crash non distruggono l'ultima vista valida.

## Accettazione e verifiche previste

- Stesso snapshot produce stesso digest e stessi dati logici; un no-op non crea operazioni o commit superflui.
- Una modifica di schema senza mtime maggiore invalida il grafo grazie al contenuto.
- Nuova fonte ammessa; mutazione, cancellazione o rename di fonte preesistente respinti, anche in merge.
- Ogni interruzione tra `prepared` e `succeeded` viene recuperata o segnalata con percorso e decisione richiesta.

Comandi **esistenti**, solo per futura regressione: dalla root `python installa.py --prova` e `python -m unittest discover -s tests -v`; in un vault sacrificabile `python .graph/build_graph.py --check`. Quest'ultimo oggi ricostruisce e scrive: non usarlo come validatore readonly. Test **da creare** in `tests/test_dashboard_contracts.py`, eseguibili dopo implementazione con `python -m unittest discover -s tests -p 'test_dashboard_contracts.py' -v`: hash/file esterni, versioni incompatibili, due lint, DB aperto, crash per fase, backup e raw. Nessuno di questi risultati è dichiarato già ottenuto.

## Rollout, rollback e decisioni aperte

Partire da copie di vault con backup personale verificato; migrare lettori e scrittori insieme prima di attivare automazioni. Rollback: disabilitare il servizio, preservare journal/backup, ripristinare solo checkpoint compatibili dopo controllo hash. Non cancellare DB legacy prima del gate del passo 5. Da decidere nella prima PR: libreria lock multipiattaforma, retention generazioni/backup e strategia di distribuzione dei moduli; confrontare dipendenze aggiuntive con implementazione standard library. L'opzione di sostituire sempre `graph.sqlite` è più compatibile ma mantiene il rischio dei lettori Windows: non è il default proposto.

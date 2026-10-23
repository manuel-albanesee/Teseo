# 3 — Editor dell'ontologia e migrazioni

Stato: parser/serializer e validazione (3.1), API preview con impatto (3.2) e form UI delle proposte con diff e capacità semantiche (3.3) implementati. Apply transazionale resta futuro (3.4). Dipendenze: [contratto 1](01-contratto-dati-operazioni.md), [dashboard 2](02-dashboard-consultazione.md); le migrazioni con mapping di pagine condivise richiedono anche il formato/eventi del [passo 5](05-stato-condiviso.md). Parser, preview e modifiche senza mapping possono precederlo. L'utente prepara modifiche a tipi e relazioni, vede le pagine interessate e potrà applicare soltanto una migrazione verificata. Le convenzioni libere conservano testo e struttura.

## Stato attuale e limiti da rispettare

[Wiki reference.md](../kit/vault/Wiki%20reference.md) contiene tipi nell'esempio di frontmatter, la tabella «Relazioni tipizzate», il significato delle relazioni e altre sezioni libere. [build_graph.py](../kit/graph/build_graph.py), `leggi_vocabolario`, usa il parser condiviso [ontology.py](../kit/graph/ontology.py); `tipo_ammesso` interpreta `qualsiasi` e `stesso tipo`. Il verso è dato dalla proprietà nella pagina sorgente; l'inversa viene calcolata. Il nome file è ID del nodo: una rinomina è una migrazione, non una modifica cosmetica.

Le euristiche vanno ispezionate in [recall.py](../kit/graph/recall.py), [candidati.py](../kit/graph/candidati.py), [domande.py](../kit/graph/domande.py) e [sintesi.py](../kit/graph/sintesi.py): per esempio `CATENA` in sintesi codifica `usa/richiede/referente` e domande contiene il caso referente. Aggiungere una relazione valida non introduce automaticamente una nuova inferenza o domanda. Scope: editing dello schema e migrazioni esplicite del vault; esclusi linguaggio generale di regole AI e modifica autonoma di codice da parte della UI.

## Modello e preservazione

`ontology.py` estrae un modello `{types,relations,source_spans,opaque_sections,digest}`. Una relazione contiene `name`, `from_types`, `to_types`, `meaning`, `example`, `direction: source_to_target`; direzione inversa visuale ha etichetta derivata e non una seconda proprietà salvata. Il serializer aggiorna solo le tabelle modificate, preserva sezioni libere, tabelle fonti, commenti e newline. Parser ambiguo, tabella duplicata o Markdown non riconosciuto porta a editing manuale, senza riscrittura totale. Il no-op restituisce sempre i byte originali, anche per documenti non modificabili.

`propose_type_catalog(document, observed_types)` prepara in memoria la sezione canonica «Tipi ammessi», ricavata da convenzioni YAML univoche, tipi osservati e vincoli. Restituisce candidato, digest base e conferma richiesta; non scrive file. L'API preview espone questa proposta dal passo 3.2; UI di conferma e apply restano futuri. Il template e i vault legacy restano invariati. Con catalogo esplicito il builder verifica tipi delle pagine e delle fonti derivate, vincoli, nomi duplicati e riservati. Senza catalogo mantiene la lettura legacy. Il manifest non acquisisce un vocabolario parallelo.

Grammatica v1: UTF-8 fino a 2 MiB, titoli ATX h2 esatti, una tabella contigua per sezione, massimo 2048 righe. Tipi: `Tipo|Descrizione` (anche `Nome`); relazioni: tre colonne `Relazione|Da|A` oppure cinque con `Significato|Esempio`, con etichette legacy `Da (tipo)`/`A (tipo)` supportate. Nomi NFC fino a 64 caratteri, iniziale alfabetica, poi lettere/numeri/underscore/trattino; vincoli separati da virgola. Supportati BOM, LF/CRLF/CR e pipe/backslash escapati. Offset e digest si riferiscono ai byte originali; il cambio di una tabella ne normalizza solo le righe, conservando il suo newline. Fence, commenti, blocchi HTML riconosciuti e codice indentato sono opachi. Formati fuori grammatica e commenti dentro una tabella richiedono intervento manuale.

Builder v3 attiva la nuova validazione al rebuild esplicito. Le generazioni v2 restano consultabili con avviso `graph_validation_upgrade`; nessuna GET ricostruisce o adotta il catalogo. `/ontology` aggiunge span, modificabilità e problemi del parser alla stessa generazione pubblicata. Se la validazione fallisce, il marker precedente rimane intatto.

Regole: nomi relazione univoci, niente collisioni con proprietà speciali (`tipo`, `tags`, `fonti`, `aggiornato`, `aliases`) o archi derivati (`menziona`, `documentato_in`); tipi conosciuti. La coerenza semantica tra testo, esempio e verso richiede revisione umana: il parser conserva il testo senza interpretarlo. Distinguere rimozione, rinomina e restringimento dei tipi. Vietare inversione automatica indiscriminata: se `A usa B` cambia semantica, occorre piano esplicito di modifica delle proprietà e dei testi supportati dalle fonti.

## API preview disponibile (3.2)

`POST /api/v1/vaults/{id}/ontology/preview` richiede sessione, Origin e CSRF come
le altre POST. Solo vault con manifest compatibile; i legacy restano readonly.
La revisione si ottiene da `GET /status`, campo `live_content_revision`: la
preview usa lo snapshot corrente, anche senza grafo, e non la generazione
pubblicata eventualmente stale. Esempio di adozione esplicita del solo catalogo:

```json
{"base_content_digest":"<live_content_revision SHA-256>","idempotency_key":"preview_0001","patch":[{"op":"adopt_types"}]}
```

Campi radice esatti; `patch` è una lista ordinata di 1–64 operazioni, corpo fino
a 16 KiB. Operazioni supportate:

| `op` | Altri campi |
| --- | --- |
| `adopt_types` | Nessuno; solo prima operazione, solo se catalogo assente |
| `add_type`, `update_type` | `name`, `value: {description?: string}` |
| `remove_type` | `name` |
| `rename_type` | `name`, `to`; aggiorna anche i vincoli dello schema candidato |
| `add_relation`, `update_relation` | `name`, `value: {from_types: string[], to_types: string[], meaning?: string, example?: string, direction?: "source_to_target"}` |
| `remove_relation` | `name` |
| `rename_relation` | `name`, `to` |

`update_*` sostituisce la definizione: i campi opzionali omessi tornano vuoti.
Una patch su un catalogo assente richiede prima `adopt_types`. Nomi duplicati,
riservati, tipi sconosciuti e inversioni sono rifiutati. Catene e ulteriori
operazioni sui nomi già rinominati richiedono preview separate; la rinomina di
pagine non è supportata in questo incremento.

Risposta 200: `preview_id`, `proposal_hash` deterministico legato a digest base,
digest schema candidato e patch, digest schema base/candidato, schema e diff
in `escaped_markdown`, modello strutturato, `changes`, `impacted_pages`,
`impacted_edges`, conteggi `usage` e `references` con pagina/proprietà/target.
`usage.types` conta pagine, `derived_types` conta le fonti derivate; sono inclusi
proprietà frontmatter, link corpo/index/log/schema, alias e chiavi fonte. Tutte
le violazioni del builder sono strutturate con `code`, `page`, `property`,
`reason`, `target` opzionale. Anche difetti già presenti nello snapshot bloccano
`schema_only_valid`: significa che il candidato non richiede correzioni delle
note né mapping condivisi, non che sia già applicato.

`migration_suggestions` propone rinomine esatte di tipo/proprietà; collisioni,
YAML non semplice o vincoli/link incompatibili sono manuali. Anche un
suggerimento deterministico richiede conferma e nuova validazione prima di un
futuro apply; nessuna pagina è riscritta. `manual_review` localizza occorrenze
letterali nel testo libero senza attribuirgli significato. `shared_records`
elenca i file condivisi: fino al formato del passo 5 una modifica reale di
schema li segnala con `shared_mapping_unavailable`, senza ignorarli o modificarli.
`semantic_capabilities.automatic_inference` è sempre false: aggiungere o
rinominare relazioni non aggiorna le euristiche di sintesi/domande.

`content_revision` è lo snapshot analizzato; `graph_generation` è null. Hash
ricontrollato dopo l'analisi e anche al replay: cambi esterni danno 409
`preview_stale`/`blocked_external_change`, senza sostituire file. Cache in memoria
di sessione, 16 risultati, TTL 900 secondi (`expires_at`, `ttl_seconds`); stessa
chiave/payload restituisce lo stesso risultato, payload diverso 409
`idempotency_conflict`. Scadenza o riavvio richiedono nuova preview e possono
produrre un nuovo ID. Nessun journal o file di cache scritto nel vault.

Limiti: snapshot esistente 64 MiB, Markdown 8 MiB/1000 documenti/2 MiB per file,
20000 archi/riferimenti/violazioni, 200 errori schema, risposta 2 MiB. Superarli
dà 422 `preview_limit`, senza risultati parziali dichiarati completi. Due
richieste ammesse nel servizio, analisi/cache serializzate; ulteriori richieste
429 `preview_busy`, oltre al rate limit HTTP già esistente. Errori payload 400,
schema/parsing 422 (dettagli localizzati quando disponibili), revisione 409.
`requires_confirmation` è true e `apply_available` false; nessun preview ID
autorizza scritture in questo rilascio.

## Form UI disponibile (3.3)

La vista Ontologia mostra prima il form della proposta e poi, in un dettaglio
separato, il vocabolario della generazione pubblicata. Il form usa la base
corrente dello snapshot e funziona anche senza grafo; un vault senza manifest
compatibile rimane readonly con spiegazione. Nessuna adozione viene selezionata
automaticamente: il catalogo assente richiede la scelta esplicita del checkbox.

Campi per tipi e relazioni, aggiunta/modifica/rimozione/rinomina, vincoli sorgente
e destinazione, significato ed esempio. Il verso è sempre sorgente → relazione
→ destinazione, senza comando di inversione. Le definizioni sono complete:
campi omessi in update tornano vuoti, come indicato nel form. I nomi e vincoli
sono inseriti dall'utente e validati dal servizio; non viene presunto che il
vocabolario pubblicato sia quello corrente. «Aggiungi alla proposta» compone
una coda revisionabile, con rimozione e dettaglio delle definizioni; «Genera
preview» è l'unica azione che invia la patch al servizio.

Risultato con diff, schema candidato inerte, pagina/proprietà/motivo delle
violazioni, suggerimenti di migrazione, testo libero da revisionare, pagine,
archi e riferimenti interessati, uso di tipi/proprietà/alias/fonti. Le liste
mostrano al massimo 200 elementi con conteggio e avviso visibile; la risposta
completa rimane quella del servizio. Nessuna nuova inferenza automatica viene
promessa e nessun pulsante di apply è disponibile.

Bozza e campi conservati soltanto in memoria per vault durante refresh e cambio
selezione; chiudere la scheda li elimina. Una modifica alla bozza o un refresh
marca il risultato precedente da rigenerare. Risposte tardive dopo modifica o
cambio vault non sostituiscono la bozza corrente. Invio duplicato disabilitato,
chiave riusata se la risposta è persa, errori localizzati e retry esplicito.
Per conflitto esterno «Aggiorna base corrente» conserva la patch e richiede
nuova preview. ID/hash e scadenza visibili; alla scadenza il risultato è marcato
da rigenerare. Nessuna persistenza browser o scrittura nel vault.

Label connesse, live status, focus sul risultato, form a due colonne desktop e
impilato su mobile. Verifiche browser riproducibili in
`tests/dashboard_ontology_smoke.js`; [evidenze ECC](evidence/step-3-3/report.json).

## Apply e migrazione futuri

- `POST /api/v1/vaults/{id}/ontology/apply` con `preview_id`, hash e migrazioni selezionate. Usa `If-Match` sul digest; `409 preview_stale` impone una nuova preview.
- `GET /api/v1/vaults/{id}/operations/{operation_id}` segue l'applicazione. Errori seguono il contratto del passo 2.

Preview calcolata su snapshot: conteggio uso di ogni tipo/proprietà, link frontmatter e corpo, alias, riferimenti index, fonti e record condivisi eventualmente interessati. Una rinomina di pagina deve includere riferimenti in eventi tramite mapping esplicito, senza riscrivere eventi immutabili: aggiungere evento di mapping del passo 5. Proporre migrazioni deterministiche solo se univoche (es. rinomina proprietà senza collisioni); testo libero ambiguo e semantica richiedono revisione umana o job esplicito del passo 4.

Applicazione: lock, ricontrollo hash, backup, candidato isolato con schema e pagine migrate, validazione completa, checkpoint journal e pubblicazione della generazione. Nessuno schema invalido diventa corrente. Una modifica solo descrittiva può non richiedere riscritture note; una restrizione con 20 archi invalidi resta bloccata finché sono risolti, non cancella gli archi automaticamente. La UI mostra prima il diff e poi il risultato, con un elenco dei file cambiati.

## Incrementi da una PR

1. Parser e serializer con preservazione byte delle sezioni non toccate; adozione catalogo tipi e nuova validazione. Uscita: roundtrip no-op identico e legacy non riscritto implicitamente.
2. Preview API con analisi impatto e suggerimenti di migrazione; uscita: ogni violazione ha pagina, proprietà e motivo.
3. Form UI con verso visibile, diff e capacità semantiche; uscita: nessuna promessa di inferenza automatica per nuove relazioni.
4. Apply transazionale, mapping rinomine e recovery; uscita: applicazione concorrente o preview scaduta respinta senza perdita.

## Accettazione, test e sicurezza

Provare aggiunta `approva` con tipi ammessi, rimozione di una relazione usata, restringimento a `persona`, `stesso tipo`, rinomina con collisione, inversione di verso e pagina con nome case-insensitive duplicato. L'editor conserva sezioni personalizzate e tabella fonti. Un editor esterno modifica lo schema dopo preview: l'apply dà conflitto e conserva entrambe le proposte. Due editor schema non applicano sullo stesso digest. Niente prompt dal testo dello schema eseguito come istruzione di sistema, né snippet/script ricevuti.

Comandi **esistenti** nel vault di prova: `python .graph/build_graph.py --check`, `python .graph/sintesi.py --verifica`; `python .graph/misura.py` usa un banco dipendente dal dominio e va confrontato con baseline del medesimo vault, non con aspettative dell'esempio su dati arbitrari. Dalla root, regressioni installer e unittest documentate nel [README](../README.md). `python -m unittest discover -s tests -p 'test_dashboard_ontology.py' -v` verifica roundtrip, adozione pura, validazioni, preservazione della generazione e lettura v2/upgrade v3. `python -m unittest discover -s tests -p 'test_dashboard_preview.py' -v` verifica preview HTTP, impatto, suggerimenti, conflitti, limiti e assenza di scritture. Apply, crash delle migrazioni e rollback restano test futuri. Esiti effettivi nel [registro implementazioni](08-analisi-avanzamento.md).

## Rollout, rollback e alternative

Prima esporre preview, poi apply su vault di prova, infine editing del vault reale con backup. Rollback locale ripristina il checkpoint schema+note solo se hash ancora coerenti; dopo pubblicazione condivisa occorre operazione compensativa validata del passo 6, non reset del branch. Alternativa JSON separato come autorità scartata per evitare due schemi divergenti. Aperto: quali cambiamenti semantici possano avere migrazione assistita; il primo rilascio deve bloccare i casi non deterministici e offrire istruzioni chiare, senza fingere di risolverli.

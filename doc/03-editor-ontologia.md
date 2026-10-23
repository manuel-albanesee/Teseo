# 3 — Editor dell'ontologia e migrazioni

Stato: parser/serializer, proposta pura di adozione e validazione del catalogo tipi implementati (3.1). Preview API, editor UI e apply restano futuri (3.2–3.4). Dipendenze: [contratto 1](01-contratto-dati-operazioni.md), [dashboard 2](02-dashboard-consultazione.md); le migrazioni con mapping di pagine condivise richiedono anche il formato/eventi del [passo 5](05-stato-condiviso.md). Parser, preview e modifiche senza mapping possono precederlo. L'utente modifica tipi, relazioni, direzione e tipi ammessi, vede le pagine interessate e applica soltanto una migrazione verificata. Le convenzioni libere conservano testo e struttura.

## Stato attuale e limiti da rispettare

[Wiki reference.md](../kit/vault/Wiki%20reference.md) contiene tipi nell'esempio di frontmatter, la tabella «Relazioni tipizzate», il significato delle relazioni e altre sezioni libere. [build_graph.py](../kit/graph/build_graph.py), `leggi_vocabolario`, usa il parser condiviso [ontology.py](../kit/graph/ontology.py); `tipo_ammesso` interpreta `qualsiasi` e `stesso tipo`. Il verso è dato dalla proprietà nella pagina sorgente; l'inversa viene calcolata. Il nome file è ID del nodo: una rinomina è una migrazione, non una modifica cosmetica.

Le euristiche vanno ispezionate in [recall.py](../kit/graph/recall.py), [candidati.py](../kit/graph/candidati.py), [domande.py](../kit/graph/domande.py) e [sintesi.py](../kit/graph/sintesi.py): per esempio `CATENA` in sintesi codifica `usa/richiede/referente` e domande contiene il caso referente. Aggiungere una relazione valida non introduce automaticamente una nuova inferenza o domanda. Scope: editing dello schema e migrazioni esplicite del vault; esclusi linguaggio generale di regole AI e modifica autonoma di codice da parte della UI.

## Modello e preservazione

`ontology.py` estrae un modello `{types,relations,source_spans,opaque_sections,digest}`. Una relazione contiene `name`, `from_types`, `to_types`, `meaning`, `example`, `direction: source_to_target`; direzione inversa visuale ha etichetta derivata e non una seconda proprietà salvata. Il serializer aggiorna solo le tabelle modificate, preserva sezioni libere, tabelle fonti, commenti e newline. Parser ambiguo, tabella duplicata o Markdown non riconosciuto porta a editing manuale, senza riscrittura totale. Il no-op restituisce sempre i byte originali, anche per documenti non modificabili.

`propose_type_catalog(document, observed_types)` prepara in memoria la sezione canonica «Tipi ammessi», ricavata da convenzioni YAML univoche, tipi osservati e vincoli. Restituisce candidato, digest base e conferma richiesta; non scrive file. La futura preview renderà questa proposta approvabile. Il template e i vault legacy restano invariati. Con catalogo esplicito il builder verifica tipi delle pagine e delle fonti derivate, vincoli, nomi duplicati e riservati. Senza catalogo mantiene la lettura legacy. Il manifest non acquisisce un vocabolario parallelo.

Grammatica v1: UTF-8 fino a 2 MiB, titoli ATX h2 esatti, una tabella contigua per sezione, massimo 2048 righe. Tipi: `Tipo|Descrizione` (anche `Nome`); relazioni: tre colonne `Relazione|Da|A` oppure cinque con `Significato|Esempio`, con etichette legacy `Da (tipo)`/`A (tipo)` supportate. Nomi NFC fino a 64 caratteri, iniziale alfabetica, poi lettere/numeri/underscore/trattino; vincoli separati da virgola. Supportati BOM, LF/CRLF/CR e pipe/backslash escapati. Offset e digest si riferiscono ai byte originali; il cambio di una tabella ne normalizza solo le righe, conservando il suo newline. Fence, commenti, blocchi HTML riconosciuti e codice indentato sono opachi. Formati fuori grammatica e commenti dentro una tabella richiedono intervento manuale.

Builder v3 attiva la nuova validazione al rebuild esplicito. Le generazioni v2 restano consultabili con avviso `graph_validation_upgrade`; nessuna GET ricostruisce o adotta il catalogo. `/ontology` aggiunge span, modificabilità e problemi del parser alla stessa generazione pubblicata. Se la validazione fallisce, il marker precedente rimane intatto.

Regole: nomi relazione univoci, niente collisioni con proprietà speciali (`tipo`, `tags`, `fonti`, `aggiornato`, `aliases`) o archi derivati (`menziona`, `documentato_in`); tipi conosciuti. La coerenza semantica tra testo, esempio e verso richiede revisione umana: il parser conserva il testo senza interpretarlo. Distinguere rimozione, rinomina e restringimento dei tipi. Vietare inversione automatica indiscriminata: se `A usa B` cambia semantica, occorre piano esplicito di modifica delle proprietà e dei testi supportati dalle fonti.

## API e migrazione future

- `POST /api/v1/vaults/{id}/ontology/preview` con `base_content_digest`, patch dichiarativa e chiave idempotente. Non scrive il vault; produce `preview_id`, hash proposta, diff schema, pagine/archetti impattati, incompatibilità, migrazioni necessarie e capacità inferenziali non supportate.
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

Comandi **esistenti** nel vault di prova: `python .graph/build_graph.py --check`, `python .graph/sintesi.py --verifica`; `python .graph/misura.py` usa un banco dipendente dal dominio e va confrontato con baseline del medesimo vault, non con aspettative dell'esempio su dati arbitrari. Dalla root, regressioni installer e unittest documentate nel [README](../README.md). `python -m unittest discover -s tests -p 'test_dashboard_ontology.py' -v` verifica roundtrip, adozione pura, validazioni, preservazione della generazione e lettura v2/upgrade v3. Preview/apply, crash delle migrazioni e rollback restano test futuri. Esiti effettivi nel [registro implementazioni](08-analisi-avanzamento.md).

## Rollout, rollback e alternative

Prima esporre preview, poi apply su vault di prova, infine editing del vault reale con backup. Rollback locale ripristina il checkpoint schema+note solo se hash ancora coerenti; dopo pubblicazione condivisa occorre operazione compensativa validata del passo 6, non reset del branch. Alternativa JSON separato come autorità scartata per evitare due schemi divergenti. Aperto: quali cambiamenti semantici possano avere migrazione assistita; il primo rilascio deve bloccare i casi non deterministici e offrire istruzioni chiare, senza fingere di risolverli.

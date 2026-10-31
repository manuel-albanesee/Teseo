# 16 — Tassonomia e ontologia dentro il grafo

Stato: **fase A implementata il 31 ottobre 2026 sul branch `ICM_Integration`; fasi B–E proposte.** Riferimento:
[«Taxonomy vs. ontology vs. knowledge graph»](https://neo4j.com/blog/knowledge-graph/taxonomy-vs-ontology-vs-knowledge-graph/)
(J. Stegeman, Neo4j, 16 giugno 2026). Il riferimento usa Neo4j; qui il grafo resta **SQLite** e Neo4j non è
in programma. Dipendenze: [contratto 1](01-contratto-dati-operazioni.md), [editor dell'ontologia 3](03-editor-ontologia.md).

## Il modello di riferimento

- **Tassonomia**: gerarchia padre-figlio di categorie (*broader/narrower*, SKOS). Serve a etichette e tag coerenti,
  ricerca a faccette, vocabolari controllati che evitano nomi paralleli.
- **Ontologia**: significati e regole logiche fra entità («Person placed Order»). Serve a dare senso a persone e AI,
  a dedurre informazioni implicite, a vocabolari condivisi. RDF non è necessario: bastano etichette, relazioni e proprietà.
- **Knowledge graph**: nodi, relazioni, proprietà di nodi e relazioni e **principi organizzativi** (tassonomia e
  ontologia) *nel grafo*, interrogabili con i dati nella stessa query.
- **Metodo**: domande del caso d'uso → schema → tassonomia se ci sono categorie → ontologia se servono significati →
  ingest secondo lo schema → evoluzione dello schema. **GraphRAG**: l'agente percorre relazioni a più passi.

## Teseo rispetto al riferimento

| Requisito | Prima di questo piano | Esito |
| --- | --- | --- |
| Domande del caso d'uso | `banco.json`, `misura.py` | presente |
| Schema, ingest secondo lo schema | `Wiki reference.md`, `build_graph.py --check` | presente |
| Evoluzione dello schema | editor con preview, migrazioni, apply e recovery ([3](03-editor-ontologia.md)) | presente |
| Relazioni con significato e vincoli | tabella «Relazioni tipizzate», `Da`/`A`, verso | presente |
| Deduzione | nessuna; inverse senza nome | **fase D** |
| Gerarchia di categorie | tipi piatti, un tipo per pagina; `parte_di` è una partonomia | **fase B** |
| Tag controllati, faccette | `tags` liberi uniti in una stringa, usati solo come marcatori (`entropia`, `sintesi`) | **fase B** |
| Principi organizzativi nel grafo | ontologia solo nel Markdown, `relations.type` stringa libera | **fase A** |
| Una query su ontologia e dati | impossibile: il DB non conosce lo schema | **fase A** |
| Semantica usata da recall, sintesi, domande | relazioni e tipi scritti nel codice (`CATENA`, `CON_REFERENTE`, `causa`) | **fase C** |
| Vocabolari condivisi (SKOS/RDF) | nessuno | **fase E**, facoltativa |

## Principi

Il Markdown resta l'autorità dell'ontologia (passo 1): nel grafo entra una **copia derivata in sola lettura**,
riscritta a ogni build. Nessuna tabella `onto_*` si modifica direttamente; si cambia `Wiki reference.md` (a mano o
con l'editor del passo 3) e si ricostruisce. Il manifest non acquisisce un vocabolario parallelo. Ogni fase cambia
prima questo documento, poi i test, poi il codice.

## Fase A — l'ontologia nel grafo (implementata)

`build_graph.build_candidate` scrive quattro tabelle in ogni grafo, legacy e a generazioni:

| Tabella | Colonne | Righe |
| --- | --- | --- |
| `onto_tipi` | `nome` PK, `descrizione`, `dichiarato` (0/1), `posizione` | con catalogo «Tipi ammessi»: i tipi dichiarati, nell'ordine del documento, `dichiarato = 1`; senza: i tipi osservati nelle pagine e nelle fonti più quelli citati nei vincoli, jolly esclusi, in ordine alfabetico, `dichiarato = 0`, descrizione vuota |
| `onto_relazioni` | `nome` PK, `significato`, `esempio`, `verso`, `posizione` | le relazioni della tabella «Relazioni tipizzate», nell'ordine del documento; nessuna se la tabella manca |
| `onto_vincoli` | `relazione`, `lato` (`da`/`a`), `tipo`, `posizione`; PK sulle prime tre | i tipi delle colonne `Da` e `A`, jolly `qualsiasi` e `stesso tipo` compresi come valori letterali |
| `onto_metadata` | `chiave` PK, `valore` | `formato` = `1`; `schema_digest` = SHA-256 dei byte di `Wiki reference.md` (vuoto se il file manca o è vuoto); `tipi` = `dichiarati` o `osservati`; `vocabolario` = `presente` o `assente` |

Le righe sono quelle che il builder ha usato per validare la stessa generazione: un grafo invalido non viene
pubblicato, quindi nomi duplicati o vincoli ripetuti non arrivano alle tabelle. Gli archi derivati `menziona` e
`documentato_in` non sono relazioni dell'ontologia e non compaiono in `onto_relazioni`.

`BUILDER_VERSION` passa a 5: la stessa revisione dei contenuti produce una nuova generazione al primo rebuild
esplicito. Le generazioni 4 e precedenti restano consultabili senza le tabelle; nessuna GET le ricostruisce. Il
lettore delle API accetta ora anche le generazioni 5.

`GET /ontology` prende `types`, `types_source` e `relations` dalle tabelle quando ci sono e, nelle generazioni
precedenti, dal Markdown memorizzato come prima: la risposta è identica nei due casi. Span, sezioni opache, problemi
del parser e testo vengono sempre dal Markdown della generazione.

Esempio di query su ontologia e dati insieme: gli archi del vault con il significato della loro relazione e i tipi
che lo schema ammette come destinazione.

```sql
SELECT r.source_id, r.type, r.target_id, o.significato,
       group_concat(v.tipo, ', ') AS destinazioni_ammesse
FROM relations r
JOIN onto_relazioni o ON o.nome = r.type
LEFT JOIN onto_vincoli v ON v.relazione = r.type AND v.lato = 'a'
GROUP BY r.source_id, r.type, r.target_id;
```

Prove: `tests/test_ontologia_grafo.py` (catalogo dichiarato, tipi osservati, schema assente, query congiunta,
generazione v5 a generazioni, risposta `/ontology` identica con e senza tabelle).

## Fase B — tassonomia (proposta)

1. **Gerarchia dei tipi.** Colonna facoltativa `Sottotipo di` in «Tipi ammessi» (grammatica v1 estesa a tre colonne);
   `onto_tipi.padre`. `tipo_ammesso` accetta i discendenti: un `servizio` sottotipo di `sistema` soddisfa `usa → sistema`.
   Cicli e padri sconosciuti sono errori dello schema. Cambia la validazione: serve una preview che mostri gli archi
   che diventano validi.
2. **Categorie dei tag.** Sezione `## Categorie` con `Categoria | Più ampia | Descrizione` (*broader*), tabella
   `categorie(nome, padre, descrizione)`; tag normalizzati in `entity_tags(entity_id, tag)` invece della stringa unita.
   Validazione dei tag facoltativa per vault, come il catalogo dei tipi; i marcatori di sistema (`entropia`, `sintesi`)
   restano ammessi.
3. **Faccette.** `GET /graph?category=X` include le sottocategorie con una CTE ricorsiva; l'editor del grafo propone i
   tag del vocabolario.

Da decidere: se le categorie danno punti di partenza al recall («i sistemi di fatturazione») o restano solo navigazione.

## Fase C — semantica letta dall'ontologia (proposta)

Ruoli semantici in un insieme chiuso, dichiarati in `Wiki reference.md` e copiati in `onto_relazioni.ruolo`:
`dipendenza` (oggi `usa`, `richiede`), `responsabile` (`referente`), `composizione` (`parte_di`), `causale`
(`causa`). `sintesi.py`, `domande.py` e `/causal` leggono i ruoli invece dei nomi; senza la sezione vale una mappa
di default identica alle costanti di oggi. Pesi per relazione nel recall e nome dell'inversa in `formatta`.
`semantic_capabilities.automatic_inference` diventa un elenco dei comportamenti attivati dai ruoli.

## Fase D — deduzione dichiarata (proposta)

Flag `transitiva` e nome `inversa` per relazione; le deduzioni sono viste SQL (`relazioni_dedotte`) ricalcolate a ogni
build, marcate come dedotte nel recall e nelle API, mai scritte nelle note.

## Fase E — interoperabilità (facoltativa)

Export in sola lettura di tipi e categorie in SKOS/Turtle; nessun import.

## Fuori perimetro

Neo4j o altri database a grafo, motori OWL, regole scritte in un linguaggio generale, inferenza affidata a un modello.

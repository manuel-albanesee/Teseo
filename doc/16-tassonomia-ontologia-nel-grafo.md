# 16 — Tassonomia e ontologia dentro il grafo

Stato: **fase A implementata il 31 ottobre 2026 sul branch `ICM_Integration`; fase B in corso: B1 implementata, B2–B4 da fare; fasi C–E proposte.** Riferimento:
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
| `onto_tipi` | `nome` PK, `descrizione`, `dichiarato` (0/1), `posizione`; `padre` da B1 | con catalogo «Tipi ammessi»: i tipi dichiarati, nell'ordine del documento, `dichiarato = 1`; senza: i tipi osservati nelle pagine e nelle fonti più quelli citati nei vincoli, jolly esclusi, in ordine alfabetico, `dichiarato = 0`, descrizione vuota |
| `onto_relazioni` | `nome` PK, `significato`, `esempio`, `verso`, `posizione` | le relazioni della tabella «Relazioni tipizzate», nell'ordine del documento; nessuna se la tabella manca |
| `onto_vincoli` | `relazione`, `lato` (`da`/`a`), `tipo`, `posizione`; PK sulle prime tre | i tipi delle colonne `Da` e `A`, jolly `qualsiasi` e `stesso tipo` compresi come valori letterali |
| `onto_metadata` | `chiave` PK, `valore` | `formato` = `1`; `schema_digest` = SHA-256 dei byte di `Wiki reference.md` (vuoto se il file manca o è vuoto); `tipi` = `dichiarati` o `osservati`; `vocabolario` = `presente` o `assente` |

Le righe sono quelle che il builder ha usato per validare la stessa generazione: un grafo invalido non viene
pubblicato, quindi nomi duplicati o vincoli ripetuti non arrivano alle tabelle. Gli archi derivati `menziona` e
`documentato_in` non sono relazioni dell'ontologia e non compaiono in `onto_relazioni`.

`BUILDER_VERSION` passa a 5 (6 con B1): la stessa revisione dei contenuti produce una nuova generazione al primo rebuild
esplicito. Le generazioni 4 e precedenti restano consultabili senza le tabelle; nessuna GET le ricostruisce. Il
lettore delle API accetta ora anche le generazioni 5 e 6.

`GET /ontology` prende `types`, `types_source` e `relations` (e da B1 `type_parents` e `categories`) dalle tabelle quando ci sono e, nelle generazioni
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

## Fase B — tassonomia e domande globali

Come si risolve in letteratura il rischio di «inondare» il contesto con le pagine di una categoria, e che cosa ne
prende Teseo:

| Idea | Fonte | In Teseo |
| --- | --- | --- |
| Domande **locali** (un'entità) e **globali** (un insieme): strategie diverse, per le globali riassunti calcolati prima | Edge et al., *From Local to Global* (GraphRAG, 2024); LightRAG (Guo et al., 2024); Adaptive-RAG (Jeong et al., 2024) | B2 separa la misura, B4 aggiunge le panoramiche come pagine per entropia |
| La categoria è **un nodo**; i nodi con molti archi si aggregano | modello a grafo del riferimento; problema dei *supernodi* | B1 tabelle, B3 un solo seme e un solo fatto aggregato |
| **Specificità**: una categoria vale −log(quota di pagine); l'espansione verso le sottocategorie perde peso con la distanza | Resnik (1995); Carpineto e Romano (2012) sul *query drift* | B3 |
| **Diversità** dei risultati invece delle prime k pagine simili | MMR, Carbonell e Goldstein (1998) | B3, nella scelta delle pagine del fatto aggregato |
| Diffusione pesata dai semi (*Personalized PageRank*) | Collins e Loftus (1975); HippoRAG (Gutiérrez et al., 2024) | esperimento separato, non in questo piano: sostituirebbe il cammino di `recall.py` |
| Decidere misurando, **per tipo di domanda** | paradigma di Cranfield | B2 prima di toccare il recall |

Ordine: B1 → B2 → B3 → B4, un commit verificato per voce. B1 e B2 non cambiano le risposte del recall; B3 e B4 si
tengono solo se il banco non peggiora sulle domande locali.

### B1 — tassonomia: gerarchia dei tipi, categorie, tag e faccette (implementata)

**Gerarchia dei tipi.** «Tipi ammessi» accetta una terza colonna facoltativa `Sottotipo di`
(`Tipo | Descrizione | Sottotipo di`); vuota significa tipo radice. Il padre deve essere un tipo dichiarato, diverso
dal tipo, senza cicli (`unknown_parent`, `type_cycle`). Il serializer scrive la terza colonna solo se almeno un tipo ha
un padre. `tipo_ammesso` accetta un tipo se lui o un suo antenato è fra gli ammessi: un `servizio` sottotipo di
`sistema` soddisfa `usa → sistema`; `stesso tipo` resta l'uguaglianza esatta. Vale nel builder, in `piano.py`, in
`candidati.py` e nelle rinomine della preview. L'editor dell'ontologia ha il campo «Sottotipo di»; `update_type`
sostituisce la definizione come oggi, quindi un padre omesso torna vuoto; `rename_type` aggiorna anche i padri.

**Categorie.** Nuova sezione `## Categorie` con `Categoria | Più ampia | Descrizione` (il *broader* di SKOS): stessi
vincoli sui nomi dei tipi, categoria più ampia dichiarata, niente cicli (`unknown_broader`, `category_cycle`), nomi
univoci senza distinguere le maiuscole (`duplicate_category`). In questa voce la sezione si scrive a mano: il serializer
la conserva byte per byte, l'editor non la modifica.

**Tag.** Con la sezione presente ogni tag di una pagina deve essere una categoria, tranne i marcatori di sistema
`entropia` e `sintesi` (`unknown_tag`); senza la sezione i tag restano liberi, come nei vault esistenti.

**Grafo** (`BUILDER_VERSION` 6): `onto_tipi.padre` (NULL per le radici); `categorie(nome PK, padre, descrizione,
posizione)`; `entity_tags(entity_id, tag)`, sempre riempita dai tag delle pagine, con o senza sezione;
`onto_metadata.categorie` = `presenti` o `assenti`. `entities.tags` resta per compatibilità.

**API e UI.** `GET /graph?category=X` restituisce i nodi con un tag uguale a X o a una sua sottocategoria (CTE
ricorsiva) e gli archi fra quei nodi; senza tabelle `graph_upgrade_required`, come il filtro per autore.
`GET /ontology` aggiunge `type_parents` (tipo → padre, solo i tipi con un padre) e `categories`
(`name`, `broader`, `description`), anche per le generazioni precedenti, ricavati dal Markdown. Il grafo della
dashboard ha il filtro «Categoria».

Non cambia: recall, sintesi, domande. Prove: `tests/test_tassonomia.py` (15 test: parser e serializer, errori della
gerarchia, builder, tabelle, `piano.py`, preview, filtro HTTP, generazione 5 senza tabelle), aggiornato
`tests/test_ontologia_grafo.py`; quattro mutazioni (antenati nel builder e in `piano.py`, CTE delle sottocategorie,
rinomina dei padri nella preview) fatte fallire dai test. Browser: `tests/dashboard_tassonomia_browser.py`, 14 controlli
a 1440×900 e 390×844 ([schermate](evidence/tassonomia-b1/)). Non provati: lettori di schermo, browser diversi da Chromium.
`Wiki reference.md` del kit e `ADATTA.md` descrivono le due sezioni facoltative; il comportamento del modello che
sceglie i tag durante l'ingest non è provato con un client AI.

### B2 — misura per tipo di domanda

Le voci di `banco.json` accettano `"tipo": "locale" | "globale"` (predefinito `locale`); `banco.py --verifica` rifiuta
altri valori. `misura.py` stampa il riepilogo del banco per tipo oltre al totale, `--banco-salva` registra il tipo e
`--banco-confronta` dà il saldo per tipo: una modifica che migliora le globali e peggiora le locali si vede. Il banco
d'esempio riceve domande globali. Il recall non cambia; la misura di partenza si salva come base per B3.

### B3 — la categoria come seme aggregato (dopo B2)

Una categoria nominata nella domanda (nome o forma ridotta a radici) diventa **un solo seme**, il nodo categoria, e
**un solo fatto**: «fatturazione [categoria, parte di amministrazione]: N pagine (…)», con al più `MAX_CATEGORIA`
pagine scelte per rilevanza e diversità e il conteggio delle omesse. Una categoria con più di `SOGLIA_CATEGORIA` delle
pagine non fa da seme (bassa specificità). Le sottocategorie entrano con peso decrescente. Il nome di una pagina vince
su una categoria omonima. Si tiene solo se B2 non mostra peggioramenti sulle domande locali né semi spuri.

### B4 — panoramiche di categoria (dopo B3)

`sintesi.py` propone una domanda «Che cosa comprende <categoria>?» per ogni categoria con almeno `MIN_ALTRE` + 1
pagine: il lint scrive la pagina per entropia, come per le catene, e la pagina diventa il riassunto calcolato prima
che risponde alle domande globali (le comunità di GraphRAG). Verifica e copertura come le altre famiglie di `sintesi.py`.

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

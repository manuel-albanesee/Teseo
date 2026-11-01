# 17 — Concetti da grafo aziendale, restando una LLM Wiki

Stato: **fase 0 in corso dal 2 novembre 2026 sul branch `ICM_Integration`; fasi 1–5 proposte.** Piano esecutivo:
[`.claude/PRPs/plans/concetti-grafo-aziendale.plan.md`](../.claude/PRPs/plans/concetti-grafo-aziendale.plan.md).
Dipendenze: [tassonomia e ontologia nel grafo 16](16-tassonomia-ontologia-nel-grafo.md) (ne chiude le fasi C, D, E e
richiede B3), [editor dell'ontologia 3](03-editor-ontologia.md), [KPI del recall](kpi-recall.md),
[KPI della coerenza](kpi-coerenza.md).

## L'idea

Dei grafi aziendali (knowledge graph con ontologie OWL/SKOS) Teseo prende i concetti che un modello può **leggere e
citare** e lascia fuori quelli che richiedono un motore che il modello non vede. Ogni concetto entra come sezione di
`Wiki reference.md`, che resta l'autorità; il grafo SQLite ne ha una copia derivata, riscritta a ogni build.

Un'ontologia esterna (FIBO, ESCO…) entra come **fonte**, non come schema: un file immutabile in `raw/vocabolari/`,
citato con una chiave di «Chiavi delle fonti». Nello schema si promuovono solo i concetti che una pagina usa, con il
passaggio esplicito che esiste già: piano di ingest, controllo, scrittura.

Il contesto resta piccolo: lo schema si legge **a fette** (solo la parte che riguarda le pagine o la fonte in
lavorazione) e del vocabolario esterno arrivano al modello al più pochi candidati trovati nel testo della fonte.

## Cosa si prende e cosa no

| Concetto aziendale | Standard | In Teseo | Fase |
| --- | --- | --- | --- |
| Peso dello schema nel contesto | — | `schema.py`: livello 1 sempre, livello 2 mirato, livello 3 su richiesta | 1 |
| Ruoli semantici | `subPropertyOf` in piccolo | sezione `## Semantica delle relazioni`, colonna Ruolo in un insieme chiuso; sostituisce `CATENA`, `CON_REFERENTE`, `'causa'` | 2 |
| Inverse con nome, transitive, simmetriche | `owl:inverseOf`, `TransitiveProperty`, `SymmetricProperty` | stessa sezione; l'inversa è un nome di lettura; deduzioni in viste SQL marcate «dedotto», mai nelle pagine | 2 |
| Vincoli e cardinalità | SHACL | sezione `## Vincoli`; un vincolo violato è una domanda aperta, non un errore | 2 |
| Sinonimi | `skos:altLabel` | sezione `## Sinonimi` per tipi e categorie; un sinonimo nominato è un seme aggregato (B3) | 3a |
| Identità condivisa | IRI, `skos:exactMatch`/`closeMatch` | sezione `## Corrispondenze` con chiave del vocabolario ed esattezza | 3a |
| Vocabolari esterni, moduli e versioni | `owl:imports`, `versionIRI` | TSV in `raw/vocabolari/`, chiave con la versione, lint delle versioni sui soli concetti promossi | 3b |
| Provenienza | PROV-O | le definizioni promosse citano la chiave del vocabolario | 3b |
| Proprietà con valore | `owl:DatatypeProperty` | sezione `## Attributi`, chiave `attributi` nel frontmatter | 4 |
| Interoperabilità | RDF/Turtle | export deterministico in sola lettura dello schema | 5 |
| Reasoner, restrizioni, classi definite | OWL DL | escluso | — |
| Più tipi per pagina | ereditarietà multipla | escluso: le classi secondarie diventano categorie | — |
| SPARQL, sincronizzazione continua | — | escluso: restano SQL sulle tabelle `onto_*` e l'export | — |

## Principi

Valgono quelli di doc/16: il Markdown è l'autorità, il grafo una copia in sola lettura, `raw/` immutabile, ogni cambio
di schema passa dai controlli, niente Neo4j né motori OWL. In più:

- **Prima si misura.** Ogni fase si tiene solo se non peggiora la coerenza delle risposte e il peso dello schema
  ([KPI](kpi-coerenza.md)) né il recall sul banco ([KPI](kpi-recall.md)).
- **Senza le sezioni nuove nulla cambia.** Un vault che non le scrive si comporta come oggi, byte per byte nelle
  domande aperte e nelle sintesi.
- **Sezioni nuove, tabelle esistenti intatte.** Le colonne nuove stanno in sezioni separate che il serializer conserva
  byte per byte, come «Categorie» in B1.
- Ogni fase cambia prima questo documento, poi i test, poi il codice.

## Correzioni alla proposta di partenza

Verificate sul codice di `ICM_Integration` (testa `d38d536`).

| # | Problema | Evidenza | Scelta |
| --- | --- | --- | --- |
| C1 | doc/16, `onto_*`, `piano.py`, `contratti.py` esistono solo su `ICM_Integration` | `git log ICM_Integration..codex/dashboard-foundations` vuoto | si lavora su `ICM_Integration` |
| C2 | B3 (categoria come seme aggregato) non è fatto, e i sinonimi ci si appoggiano | doc/16, stato e B3 | B3 prima della fase 3a |
| C3 | il validatore rifiuta un verso diverso da `source_to_target`, la preview l'«inversione automatica» | `ontology.py:182-183`, `ontology_preview.py:106` | l'inversa è solo un nome; nessun arco inverso |
| C4 | la tabella delle relazioni ha 3 o 5 colonne e il serializer ne riscrive sempre 5: una colonna nuova si perderebbe | `ontology.py:363,407-408` | sezioni separate, conservate byte per byte |
| C5 | ogni chiave del frontmatter non riservata è una relazione; le chiavi riservate sono in quattro posti | `build_graph.py:77`, `correzioni.py:30`, `graph_edit.py:30`, `ontology.py:15` | `attributi` riservata nei quattro insiemi, con un test che li allinea |
| C6 | `raw/` è già nello snapshot e nel digest, `.tsv` è già condivisibile; manca il parser | `storage.py:220`, `git_sync.py:25`, `build_graph.py:206-210` | si estende solo `parse_snapshot` |
| C7 | la domanda sul referente ha chiave `referente\|<pagina>\|`, su cui stanno rinvii e risposte | `domande.py:143,177` | segnale e chiave invariati per il referente; `vincolo` per i vincoli nuovi |

Il livello 1 non può contenere tutte le «Chiavi delle fonti» (crescono con le call) né le sezioni h2 intere (sotto
«Relazioni tipizzate» c'è la descrizione degli script): `schema.py` estrae tabelle e paragrafi di regola.

## Fasi

Ordine: 0 → 1 → 2 → B3 → 3a → go/no-go → 3b → 4 → 5. B3 si può fare in parallelo alla 2.

| Fase | Contenuto | Soglia per tenerla | Stato |
| --- | --- | --- | --- |
| 0 — Misurare | [KPI di coerenza](kpi-coerenza.md): coerenza dei nomi, stabilità fra giri e fra parafrasi, peso dello schema; basi sul vault d'esempio e sul vault ISP | basi salvate | **in corso** |
| 1 — Schema mirato | `schema.py`, tre livelli, contratti di ingest e lint, `contratti.py --peso` che conta `schema.py` | peso dello schema giù; recall e coerenza invariati | proposta |
| 2 — Semantica dichiarata | ruoli, inverse, transitive e simmetriche (fasi C e D di doc/16), vincoli, blocco «Schema pertinente» nel recall; `BUILDER_VERSION` 7 | senza sezioni, domande e sintesi identiche sul vault d'esempio | proposta |
| B3 | categoria come seme aggregato, come in doc/16 | regola di doc/16 | proposta |
| 3a — Sinonimi interni | `## Sinonimi`, `## Corrispondenze`; sinonimo come seme; `BUILDER_VERSION` 8 | coerenza dei nomi su; semi spuri invariati | proposta |
| 3b — Vocabolari esterni | riduttore da CSV, TSV in `raw/vocabolari/`, `schema.py --per-testo`, sezione del piano, lint delle versioni | coerenza dei nomi su rispetto alla 3a | da decidere dopo la 3a |
| 4 — Attributi | `## Attributi`, chiave `attributi`, attributi nei fatti del recall; `BUILDER_VERSION` 9 | nessun peggioramento | proposta |
| 5 — Export | Turtle deterministico dello schema (fase E di doc/16, ampliata) | golden file stabile | proposta |

### Fase 0 — misurare (in corso)

I KPI sono definiti in [kpi-coerenza.md](kpi-coerenza.md). Strumenti:

- `coerenza.py --risposte DIR`: coerenza dei nomi e stabilità fra giri sulle risposte salvate da
  `misura.py --modello --giri N --out DIR`; deterministico, nessun modello chiamato.
- Campo facoltativo `parafrasi` nel banco: `misura.py` misura la stabilità fra parafrasi (deterministica, anche in
  CI), `--banco-salva` la registra e `--banco-confronta` ne dà la variazione; `banco.py --verifica` controlla il campo.
- Peso dello schema: `contratti.py --peso` sulle quattro skill e il token medio del banco.

Basi: vault d'esempio in [evidence/concetti-0](evidence/concetti-0/); vault ISP (213 pagine, banco di 106 domande)
da misurare quando il vault è disponibile su questo computer, con solo numeri aggregati nel repository. Le misure con
un modello si lanciano solo con il via esplicito dell'autore: costano.

## Decisioni (2 novembre 2026)

| # | Decisione | Esito |
| --- | --- | --- |
| 1 | Dove sta un vocabolario esterno | `raw/vocabolari/`, immutabile e citato come fonte |
| 2 | Vincolo violato | domanda aperta per default |
| 3 | Export delle pagine come individui | no: solo lo schema; l'identità stabile delle pagine si decide dopo la fase 4 |
| 4 | Ingresso del riduttore | solo CSV (FIBO Data Dictionary, ESCO); nessuna dipendenza nuova |
| 5 | Vault reale per le basi | vault ISP |
| 6 | Branch | `ICM_Integration` |

## Fuori perimetro

Neo4j o altri database a grafo, reasoner e restrizioni OWL, SPARQL, più tipi per pagina, archi dedotti scritti nelle
pagine, import o aggiornamento automatico di un vocabolario, rdflib nel kit, inferenza affidata a un modello.

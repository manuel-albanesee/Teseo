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
| 1 — Schema mirato | `schema.py`, tre livelli, contratti di ingest e lint, `contratti.py --peso` che conta `schema.py` | peso dello schema giù; recall e coerenza invariati | **implementata** (2 novembre 2026) |
| 2 — Semantica dichiarata | ruoli, inverse, transitive e simmetriche (fasi C e D di doc/16), vincoli, blocco «Schema pertinente» nel recall; `BUILDER_VERSION` 7 | senza sezioni, domande e sintesi identiche sul vault d'esempio | **implementata** (2 novembre 2026) |
| B3 | categoria come seme aggregato, come in doc/16 | regola di doc/16 | implementata (2 novembre 2026) |
| 3a — Sinonimi interni | `## Sinonimi`, `## Corrispondenze`; sinonimo come seme; `BUILDER_VERSION` 8 | coerenza dei nomi su; semi spuri invariati | **implementata** (2 novembre 2026); go/no-go aperto: servono K1 sul vault reale |
| 3b — Vocabolari esterni | riduttore da CSV, TSV in `raw/vocabolari/`, `schema.py --per-testo`, sezione del piano, lint delle versioni | coerenza dei nomi su rispetto alla 3a | da decidere dopo la 3a |
| 4 — Attributi | `## Attributi`, chiave `attributi`, attributi nei fatti del recall; `BUILDER_VERSION` 9 | nessun peggioramento | **implementata** (2 novembre 2026) |
| 5 — Export | Turtle deterministico dello schema (fase E di doc/16, ampliata) | golden file stabile | **implementata** (2 novembre 2026) |

### Fase 0 — misurare (in corso)

I KPI sono definiti in [kpi-coerenza.md](kpi-coerenza.md). Strumenti:

- `coerenza.py --risposte DIR`: coerenza dei nomi e stabilità fra giri sulle risposte salvate da
  `misura.py --modello --giri N --out DIR`; deterministico, nessun modello chiamato.
- Campo facoltativo `parafrasi` nel banco: `misura.py` misura la stabilità fra parafrasi (deterministica, anche in
  CI), `--banco-salva` la registra e `--banco-confronta` ne dà la variazione; `banco.py --verifica` controlla il campo.
- Peso dello schema: `contratti.py --peso` sulle quattro skill e il token medio del banco.

Basi sul vault d'esempio (2 novembre 2026, [evidence/concetti-0](evidence/concetti-0/)):

| Misura | Valore di partenza | File |
| --- | --- | --- |
| Recall sul banco, totale | 1/11 pagine attese (9%), domande complete 0/5, rumore medio 0,6, token medio 14 | [testo](evidence/concetti-0/banco-esempio-base.txt), [salvataggio](evidence/concetti-0/banco-esempio-base.json) |
| Recall, locali / globali | 1/4 e 0/7 (come la base di B2 in doc/16) | stesso file |
| K3 stabilità fra parafrasi | 0,50 su 2 voci con 2 parafrasi; stesso seme 1/2 | stesso file |
| K4 peso dello schema, livello 3 | ingest ~4515 token, lint ~4515, query ~3194, lacune ~3194 | [testo](evidence/concetti-0/peso-skill.txt) |
| K1, K2 | non misurati: servono un modello e un vault reale | — |

Il `Wiki reference.md` del kit pesa ~4515 token e ingest e lint lo caricano per intero: sul vault d'esempio il
guadagno della fase 1 è piccolo, per questo le basi che contano sono quelle del vault ISP (213 pagine, banco di 106
domande). Il vault ISP non è su questo computer: quando c'è, si misurano le stesse cose e nel repository entrano solo
numeri aggregati. Le misure con un modello (K1 e K2) si lanciano solo con il via esplicito dell'autore: costano.

### Fase 1 — schema mirato (implementata)

`kit/graph/schema.py` stampa fette di `Wiki reference.md`, in sola lettura e senza modello:

| Livello | Cosa contiene | Tetto |
| --- | --- | --- |
| 1, sempre (`--livello 1`) | Regole non negoziabili, Convenzioni delle pagine senza le pagine generate per entropia, il formato delle Chiavi delle fonti, l'indice dei nomi di tipi, relazioni e categorie (uno per voce, senza descrizioni); con `--entropia` e `--sezione "…"` le sezioni che il lint chiede | 3000 token |
| 2, mirato (`--per-pagine`, `--per-tipi`, `--fonti`) | Le righe complete dei tipi indicati e dei loro antenati; le relazioni che possono partire da quei tipi o arrivarci (antenati e `qualsiasi` compresi); le righe delle chiavi delle fonti citate | 1500 token |
| 3, su richiesta | `Wiki reference.md` per intero, quando c'è un dubbio o il vault non ha `schema.py` | — |

I tetti sono avvisi, non errori. Senza il catalogo «Tipi ammessi» il livello 2 stampa tutte le relazioni; con errori di
schema avvisa di leggere il file per intero. Le fette sono tabelle e paragrafi, non sezioni h2 intere (C: sotto
«Relazioni tipizzate» c'è la descrizione degli script).

`contratti.py --peso` non esegue il comando: per `--livello 1` calcola la fetta in-process con `schema.fette`, per
le fette mirate usa il tetto del livello 2 e marca la riga «(stima)». Le skill di ingest e lint hanno le righe di Input
su `schema.py` e la regola «se hai un dubbio leggi tutto»; query e lacune citavano già solo sezioni.

Peso dello schema nei contratti (K4, vault d'esempio, token caricati di livello 3):

| Skill | Prima | Dopo | Variazione |
| --- | --- | --- | --- |
| ingest | ~4515 | ~2156 (livello 1 ~656 + livello 2 al tetto 1500) | −52% |
| lint | ~4515 | ~3307 (livello 1 con entropia e manutenzione ~1807 + livello 2 al tetto 1500) | −27% |
| query, lacune | ~3194 | invariato | — |

Il livello 2 è un tetto, non una misura: sul vault d'esempio, che non ha il catalogo dei tipi, stamperebbe tutte le
relazioni. Il guadagno reale si misura sul vault ISP. Recall e K3 sul banco non cambiano: il recall non è stato toccato;
K1 e K2 richiedono il modello e restano da misurare con il via dell'autore.

Prove: `tests/test_schema_mirato.py` (23 test: livelli, antenati, jolly, fonti, avvisi, grafo, comando, peso nei
contratti); tre mutazioni (senza antenati, senza il jolly `qualsiasi`, entropia sempre inclusa) fatte fallire. Aggiornati
due test di `tests/test_contratti.py` che codificavano la lettura intera.

### Fase 2 — semantica dichiarata (implementata)

Due sezioni facoltative di `Wiki reference.md`, in tabelle separate dalle esistenti (C4) e conservate byte per byte dal
serializer:

| Sezione | Colonne | Che cosa fa |
| --- | --- | --- |
| `## Semantica delle relazioni` | `Relazione \| Ruolo \| Inversa \| Proprietà` | `Ruolo` in un insieme chiuso (`dipendenza`, `responsabile`, `composizione`, `causale`, `sequenza`); `Inversa` è un nome di lettura (C3: mai un arco, `verso` resta fisso); `Proprietà` è `transitiva` e/o `simmetrica` |
| `## Vincoli` | `Tipo \| Relazione o attributo \| Minimo \| Massimo \| Se manca` | un vincolo vale anche per i sottotipi; `Se manca` = `domanda` (default) o `nulla` |

Errori del parser (`ontology.py`): `unknown_relation`, `invalid_role`, `invalid_property`, `duplicate_semantics`,
`symmetric_with_inverse`, `unknown_type`, `invalid_cardinality`, `invalid_if_missing`, `duplicate_cardinality`. Rinominare
o togliere dall'editor una relazione o un tipo citati nelle sezioni è rifiutato dalla preview con questi codici, non
perde righe in silenzio.

**Grafo** (`BUILDER_VERSION` 7): colonne `ruolo`, `inversa`, `transitiva`, `simmetrica` in `onto_relazioni`; tabella
`onto_cardinalita`; metadati `semantica` e `vincoli` (`presente`/`assente`); vista `relazioni_dedotte(source_id,
target_id, type, origine)`: chiusura delle relazioni transitive fino a 3 passi e speculari delle simmetriche, mai ciò che
una pagina già dichiara, `origine = 'dedotto'`, ricalcolata a ogni build e mai scritta nelle pagine.

**I ruoli di default stanno nel codice, non nelle tabelle** (`semantica.RUOLI_DEFAULT`: `usa` e `richiede` dipendenza,
`referente` responsabile, `parte_di` composizione, `causa` causale). Le tabelle hanno solo ciò che l'autore dichiara, e un
ruolo dichiarato sostituisce il default di quella relazione: una sezione che dichiara solo inverse non toglie a `causa` il
suo ruolo causale, e una che dà `precede: dipendenza` la fa entrare nelle catene.

**Letto dai ruoli**: le catene e le persone di `sintesi.py`, il vincolo sul referente e le aree (`parte_di`) di
`domande.py`, `/causal` di `read_api.py`. La sezione «Vincoli», se c'è, sostituisce il vincolo di default (sistemi,
processi e progetti hanno un referente, salvo le parti di un tutto). Il vincolo sul referente conserva segnale e chiave
(`referente|<pagina>|`: C7), quindi rinvii e risposte già archiviati restano; gli altri hanno segnale `vincolo` (chiave
`vincolo|<pagina>|<relazione> min` o `max`), dopo `referente` nell'ordine.

**Recall**: se la semantica è dichiarata, `formatta` aggiunge in coda il blocco «Schema pertinente», al più 300 token:
«- usa (dipendenza; inversa: è usato da): X funziona tramite Y», solo per le relazioni presenti nei fatti.
`GRAFO_SENZA_SCHEMA=1` lo spegne. Senza la sezione il contesto è quello di prima. L'hook lo calcola prima di chiudere il
grafo (un test lo copre: la prima versione falliva con «closed database»).

**Altro**: `GET /ontology` espone `semantics` e `constraints`; `semantic_capabilities.automatic_inference` è l'elenco dei
comportamenti attivati (`role_chains`, `inverse_labels`, `transitive_views`, `symmetric_views`, `cardinality_questions`),
vuoto senza le sezioni; il livello 2 di `schema.py` porta con i tipi toccati anche le righe di ruoli, inverse e vincoli.

Scostamenti dal piano: (1) le relazioni dedotte restano una vista SQL e non entrano ancora nei fatti del recall né nelle
API, per non toccare il cammino di `recall.py`; (2) le inverse compaiono nel blocco di schema e non nelle righe dei
fatti; (3) un vincolo si riferisce per ora a una relazione, gli attributi arrivano con la fase 4.

Prove: `tests/test_semantica.py` (36 test: parser, roundtrip, errori, preview, tabelle e vista, ruoli, vincoli, recall,
hook, API) con tre confronti byte per byte con l'output di `domande.py` e `sintesi.py` di prima della fase
(`tests/fixtures/semantica/`): senza sezioni, con sole inverse e con ruoli e vincolo uguali ai default. Tre mutazioni
(sottotipi ignorati nei vincoli, ruoli dichiarati ignorati, profondità della vista) fatte fallire. Aggiornati
`tests/test_ontologia_grafo.py` (versione 7, due metadati). Non misurati: K1 e K2 con il modello, e K3 e il token medio del
banco con il blocco di schema sul vault ISP.

### Fase 3a — sinonimi e corrispondenze interni (implementata)

Due sezioni facoltative di `Wiki reference.md`, in tabelle proprie e conservate byte per byte dal serializer (C4):

| Sezione | Colonne | Che cosa fa |
| --- | --- | --- |
| `## Sinonimi` | `Nome \| Sinonimi` | `Nome` è un tipo o una categoria dichiarati; i sinonimi sono separati da `;` («SPV; società veicolo»). Una domanda che nomina un sinonimo porta lo stesso seme aggregato del nome (B3) |
| `## Corrispondenze` | `Nome \| Corrispondenza \| Vocabolario \| Esattezza` | `Corrispondenza` è un IRI o un CURIE; `Vocabolario` è una chiave censita in «Chiavi delle fonti»; `Esattezza` è `esatta` o `vicina` (solo `esatta` potrà ereditare sinonimi da un vocabolario, fase 3b) |

Errori del parser (`ontology.py`): `invalid_synonyms`, `unknown_name`, `duplicate_synonyms`, `synonym_collision` (un sinonimo
uguale dopo `norm` a un altro nome, a un suo stesso nome o a un sinonimo di un altro nome), `invalid_iri`, `invalid_exactness`,
`duplicate_match`. Il build aggiunge `unknown_vocabulary_key` (la chiave non è fra le «Chiavi delle fonti»). Rinominare o
togliere dall'editor un tipo o una categoria citati nelle sezioni è rifiutato con questi codici, come per la fase 2.

**La pagina vince** (regola di doc/16): un sinonimo uguale dopo `norm` al nome, a un alias o a una variante di una pagina non fa da
seme e il build lo segnala come avviso (`snapshot["avvisi"]`, stampato da `build_graph.py`), mai come errore.

**Grafo** (`BUILDER_VERSION` 8): tabelle `onto_sinonimi(nome, sinonimo, posizione)` e
`onto_corrispondenze(nome, iri, vocabolario, esattezza, posizione)`; metadati `sinonimi` e `corrispondenze`
(`presente`/`assente`). `GET /ontology` espone `synonyms` e `matches`; `automatic_inference` aggiunge `synonym_seeds` quando ci
sono sinonimi.

**Recall** (`recall.py`): un sinonimo di una categoria produce lo stesso seme e lo stesso fatto aggregato di B3; un sinonimo di un
tipo produce un seme `(tipo, 'tipo[, sottotipo di X]', descrizione)` e un fatto `→ tipo →` con al più `MAX_CATEGORIA` pagine di
quel tipo e dei suoi sottotipi (stessa diversità e stessa `SOGLIA_CATEGORIA`). `PAROLE_COMUNI` vale anche per i sinonimi, e un
sinonimo contenuto nel nome di una pagina già riconosciuta non conta. Il ripiego sul testo non scatta se la domanda nomina un
sinonimo. Senza le sezioni nulla cambia.

Scostamenti dal piano: (1) `onto_sinonimi` ha anche `posizione`, come le altre tabelle `onto_*`; (2) il confronto fra sinonimo e
pagina usa nomi, alias e varianti grafiche, non le sole pagine; (3) `unknown_vocabulary_key` è un errore del build (serve
l'elenco delle «Chiavi delle fonti», che il parser dello schema non ha), gli altri codici sono del parser; (4) il sinonimo si
confronta con la frase ridotta a radici e contigua, non con le radici sparse; (5) il banco d'esempio resta senza sinonimi: la
sezione è facoltativa e `kit/vault/Wiki reference.md` la documenta soltanto, la misura utile è quella sul vault ISP.

Prove: `tests/test_sinonimi.py` (31 test: parser, errori, roundtrip, preview, tabelle, avvisi, seme di categoria e di tipo,
soglia, pagina che vince, parole comuni, ripiego, API) con otto mutazioni (collisione, pagina che vince, contiguità, soglia
dei tipi, sinonimo dentro il nome di una pagina, parole comuni, avvisi, ripiego sul testo), tutte uccise.

Go/no-go dopo questa fase: si procede con la 3b solo se K1 sale sul vault reale **e** esiste un vocabolario esterno concreto.

**Esito del go/no-go (2 novembre 2026): no-go per ora.** Mancano le due condizioni: K1 sul vault reale (il vault ISP non è su
questo computer e K1 richiede un modello, quindi il via esplicito dell'utente) e un vocabolario esterno concreto. La 3b resta
proposta; si passa alla fase 4. Si riapre quando l'utente indica il vocabolario (FIBO, ESCO, altro) e il percorso `VAULT_ISP`.

### Fase 4 — attributi (implementata)

Un attributo è un valore scalare di una pagina, non un arco: «data_liquidazione_prevista: 2031-12-31». Si dichiara in una
sezione facoltativa di `Wiki reference.md` e si scrive nel frontmatter sotto la chiave riservata `attributi`.

| Elemento | Forma |
| --- | --- |
| `## Attributi` | `Attributo \| Di (tipo) \| Valore \| Descrizione`; `Di` è un tipo dichiarato (vale anche per i sottotipi); `Valore` è `testo`, `numero`, `data`, `importo`, `codice`, `sì/no` o `categoria:X` (X una categoria dichiarata) |
| frontmatter | `attributi: {nome: valore}`, una mappa: la chiave `attributi` non è una relazione |
| `## Vincoli` | la colonna «Relazione o attributo» può citare un attributo: minimo 1 = obbligatorio (domanda aperta se manca), massimo al più 1 |

Valori: `numero` è un intero o un decimale; `data` è una data ISO (YAML la legge come `datetime.date`: si normalizza a
`AAAA-MM-GG` prima del confronto); `importo` è un numero o «250000 EUR» (numero e codice di tre lettere maiuscole); `codice` ha
lettere, cifre e `._/-`, fino a 64 caratteri; `sì/no` è un booleano YAML o «sì»/«no»; `categoria:X` è X o una sua
sottocategoria. Un attributo vale per la pagina del tipo `Di` e dei suoi sottotipi; se due righe coprono la stessa pagina vince il
tipo più specifico.

Errori del parser (`ontology.py`): `invalid_attribute`, `duplicate_attribute` (stesso nome e stesso tipo), `unknown_type`,
`unknown_name` (la categoria di `categoria:X`), `invalid_value_type`, `reserved_attribute` (nome fra le chiavi speciali del
frontmatter o uguale a una relazione). Errori del build, per pagina: `unknown_attribute` (non dichiarato per il tipo della
pagina), `attribute_type` (tipo Python sbagliato), `attribute_value` (tipo giusto, contenuto no). Senza la sezione il build ignora la
mappa `attributi` e nulla cambia.

**Chiave riservata** (C5): `attributi` entra in quattro insiemi che oggi dicono quali chiavi del frontmatter non sono relazioni:
`build_graph.NON_RELAZIONI`, `correzioni.NON_RELAZIONI`, `graph_edit.RESERVED`, `ontology.SPECIAL`. Un test controlla che ci sia in
tutti. Un vault con una relazione chiamata `attributi` riceve `reserved_relation` (da scrivere in `ADATTA.md`).

**Grafo** (`BUILDER_VERSION` 9): `onto_attributi(nome, tipo, valore, descrizione, posizione)` e
`entity_attributi(entity_id, attributo, valore)` (il valore normalizzato, come testo); metadato `attributi`.

**Recall**: `formatta` aggiunge sotto ogni pagina seme una riga «· data_liquidazione_prevista: 2031-12-31; …» con al più
`MAX_ATTRIBUTI` attributi, nell'ordine della sezione; categorie e tipi non ne hanno. **Domande**: un vincolo su un attributo
mancante è una domanda aperta di segnale `vincolo` (chiave `<attributo> min`).

Scostamenti dal piano: (1) il build ignora la mappa `attributi` se manca la sezione, invece di segnalarla; (2) una data scritta senza
apici e inesistente (2031-13-45) la rifiuta YAML prima di arrivare al kit: `leggi_testo` ora la trasforma in un errore che nomina la
pagina («P.md: frontmatter non valido (month must be in 1..12)»), come già faceva per gli altri errori di YAML; (3) un vincolo su un
attributo ammette minimo 0 o 1 e massimo vuoto o 1 (`invalid_cardinality` altrimenti); (4) il confronto del peso medio del
contesto (+5%) richiede il vault reale e resta da fare con il vault ISP; (5) le righe che documentano le sezioni facoltative in `kit/vault/Wiki reference.md` sono brevi di proposito: stanno nel livello 1 dello schema, e con la terza versione più lunga il test dei tre quarti (`test_contratti`) è fallito per 17 token. Il dettaglio sta qui, non nello schema.

Prove: `tests/test_attributi.py` (29 test: parser, errori, roundtrip, chiave riservata nei quattro insiemi, preview, build, valori
normalizzati, ereditarietà, recall, vincoli, API) con nove mutazioni (importo, albero delle categorie, tipo più specifico, sezione
assente, data inesistente, tetto, vincolo sull'attributo, cardinalità, nomi riservati), tutte uccise.

### Fase 5 — export Turtle dello schema (implementata)

`python .graph/esporta_rdf.py [--db graph.sqlite] [--base IRI] [--out FILE]` scrive lo **schema** (decisione del 2 novembre 2026:
solo lo schema, non le pagine) in Turtle, per aprirlo in uno strumento di ontologie o confrontarlo con un vocabolario esterno. Sola
lettura del grafo corrente, solo libreria standard, nessun rdflib: il grafo resta quello che il builder ha costruito dal Markdown.

| Dal grafo | In Turtle |
| --- | --- |
| tipi (`onto_tipi`) | `owl:Class`, `rdfs:label`, `rdfs:comment`, `rdfs:subClassOf` verso il padre |
| categorie (`categorie`) | `skos:Concept`, `skos:prefLabel`, `skos:definition`, `skos:broader` verso la più ampia |
| relazioni (`onto_relazioni`, `onto_vincoli`) | `owl:ObjectProperty`; `rdfs:domain` e `rdfs:range` solo se il lato ammette un tipo solo (né `qualsiasi` né `stesso tipo` né più tipi); `owl:TransitiveProperty` e `owl:SymmetricProperty` come secondo tipo |
| attributi (`onto_attributi`) | `owl:DatatypeProperty`; `rdfs:domain` se il nome ha un solo tipo; `rdfs:range`: `xsd:date`, `xsd:decimal`, `xsd:boolean`, `xsd:string`, o `skos:Concept` per `categoria:X` |
| sinonimi (`onto_sinonimi`) | `skos:altLabel "…"@it` sul tipo o sulla categoria |
| corrispondenze (`onto_corrispondenze`) | `skos:exactMatch` o `skos:closeMatch` verso l'IRI, più `prov:wasDerivedFrom` verso la fonte del vocabolario |

Scelte: (1) **nessun `owl:inverseOf`**: l'inversa dichiarata è un nome di lettura («è usato da»), non una relazione con un IRI (C3);
(2) i **CURIE** delle corrispondenze non hanno una mappa di prefissi nel vault: si esportano come `urn:curie:<curie>`, riconoscibili
e riconvertibili; (3) gli IRI dei termini sono `<base>tipo/<nome>`, `categoria/`, `relazione/`, `attributo/`, `fonte/`, con la base che
finisce per `/` o `#` (default `https://example.org/teseo/`), i nomi codificati in percentuale; (4) **ordine totale**: ogni tripla è
una riga `soggetto predicato oggetto .`, ordinate per soggetto, predicato, oggetto, senza date né altro che cambi fra due esecuzioni:
due esecuzioni sullo stesso grafo producono byte identici; (5) stringhe con le fughe di Turtle (`\`, `\"`, `\n`, `\r`, `\t`,
`\uXXXX`). Le tabelle che una generazione più vecchia non ha si saltano.

Prove: `tests/test_esporta_rdf.py` (28 test: ogni tabella dello schema, dominio e codominio solo se univoci, nessun `owl:inverseOf`,
CURIE, provenienza, forma di ogni riga, ordine totale, due esecuzioni byte identiche, golden file `tests/fixtures/rdf/schema.ttl`, base
non valida, generazioni senza le tabelle, grafo non modificato, CLI con `--out` in LF) con otto mutazioni (univocità, jolly, ordine, dominio
degli attributi, esattezza, CURIE, fughe, padre dei tipi, nomi non dichiarati), tutte uccise. Il file non è validato da un parser Turtle
(niente rdflib): lo controllano la forma di ogni riga e il golden, da aprire a mano in uno strumento di ontologie la prima volta.

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

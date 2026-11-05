# Piano: concetti da grafo aziendale in Teseo, restando una LLM Wiki

## Sommario

Portare in Teseo i concetti dei grafi aziendali che un modello può leggere e citare (sinonimi, corrispondenze con IRI,
ruoli, inverse con nome, transitività, vincoli, attributi, provenienza, export), sempre come sezioni di
`Wiki reference.md` copiate nel grafo SQLite. Lo schema entra nel contesto a fette, non per intero. Un vocabolario
esterno (FIBO, ESCO…) entra come fonte immutabile in `raw/vocabolari/` e se ne promuovono solo i concetti usati.
Ogni fase si tiene solo se non peggiora due KPI misurati per primi: la coerenza delle risposte e il peso dello schema.

## Stato e ambito delle esecuzioni

Piano finale del 2026-11-02, scritto sul branch `ICM_Integration` (testa `d38d536`). Ogni fase è un'esecuzione
separata di `/ecc:prp-implement`: la fase N+1 parte solo se la fase N ha superato la sua soglia, registrata in doc/17.

| Fase | Stato | Esecuzione |
| --- | --- | --- |
| 0 — Misurare | **in corso** | questa: task 0.1–0.4 |
| 1 — Schema mirato | da fare | dopo la soglia della 0 |
| 2 — Semantica dichiarata | da fare | — |
| P — B3 di doc/16 | da fare | in parallelo alla 2 |
| 3a — Sinonimi interni | da fare | dopo P |
| 3b — Vocabolari esterni | da decidere | go/no-go dopo la 3a |
| 3c — Editor | facoltativa | — |
| 4 — Attributi | da fare | — |
| 5 — Export | da fare | — |

**Parametro `VAULT_ISP`.** Il vault ISP è il vault reale della base (decisione confermata), ma sul disco non c'è
(`C:\Obsidian\Wiki-ISP` assente il 2026-11-02). Il suo percorso serve solo al task 0.4b: tutto il resto della fase 0
si esegue e si verifica senza.

## Valutazione della proposta

**Giudizio: direzione approvabile, con sette correzioni bloccanti e un ordine delle fasi rivisto.** La proposta
rispetta i principi di doc/16 (Markdown come autorità, copia derivata, nessun reasoner, Neo4j fuori perimetro) e
chiude in modo coerente le fasi C, D ed E già proposte lì. Il metodo «prima i KPI» corrisponde alla decisione
dell'utente del 2026-11-01 (coerenza come KPI accanto al recall). I punti seguenti sono verificati sul codice di
`ICM_Integration`, non del branch corrente.

### Cosa regge

| Affermazione della proposta | Verifica |
| --- | --- |
| Ingest e lint caricano `Wiki reference.md` per intero | vero: `kit/skills/obsidian-wiki-ingest/SKILL.md:22` e `obsidian-wiki-lint/SKILL.md:34` dicono «tutto»; query e lacune caricano già per sezioni (`obsidian-wiki-query/SKILL.md:17-18`, `obsidian-wiki-fill-gaps/SKILL.md:38-39`) |
| `contratti.py --peso` ignora i comandi | vero: `kit/graph/contratti.py:16-17` e regex `COMANDO` a `:37` |
| Ripiego «leggi tutto se hai un dubbio» | vero: `obsidian-wiki-fill-gaps/SKILL.md:155`, `obsidian-wiki-query/SKILL.md:62` |
| La semantica è scritta nel codice | vero: `sintesi.py:49` `CATENA`, `domande.py:56` `CON_REFERENTE`, `read_api.py:334` `'causa'` per `/causal`, e anche `domande.py:100,173-174` (`parte_di`, `referente`) |
| L'editor non ha operazioni sulle categorie | vero: `ontology_preview.py:56-57` elenca solo operazioni su tipi e relazioni |
| `--giri` esiste | vero: `misura.py:622`; le risposte di ogni giro si salvano già in JSON (`misura.py:524`) |
| PyYAML unica dipendenza | vero: `CONTRIBUTING.md:18,43-44` |
| doc/16:95, :152, :179 | vero: regola di B3, la pagina vince sulla categoria omonima, fuori perimetro |

### Correzioni (bloccanti se non recepite)

| # | Problema | Evidenza | Correzione nel piano |
| --- | --- | --- | --- |
| C1 | **Branch.** doc/16, le tabelle `onto_*`, `piano.py` e `contratti.py` esistono solo su `ICM_Integration`. Il branch corrente `codex/dashboard-foundations` ne è un antenato: `git log ICM_Integration..codex/dashboard-foundations` è vuoto | `git ls-tree ICM_Integration doc/` | il lavoro parte da `ICM_Integration` (risponde alla decisione 6) |
| C2 | **B3 non è fatto.** I sinonimi come seme aggregato si appoggiano a B3, che doc/16 dà «da fare» | `doc/16:3`, `:146-152` | B3 diventa prerequisito della fase 3 (Task P) |
| C3 | **Il validatore rifiuta le inverse.** `direction != 'source_to_target'` → `invalid_direction`; anche la preview rifiuta «inversione automatica» | `ontology.py:182-183`, `ontology_preview.py:106` | l'inversa è solo un **nome** (etichetta di lettura); `verso` resta fisso; nessun arco inverso nelle pagine |
| C4 | **Il serializer perderebbe colonne nuove.** La tabella relazioni accetta solo 3 o 5 colonne e `_table` ne riscrive sempre 5: una colonna `Ruolo`/`Inversa`/`Proprietà` sparirebbe al primo salvataggio dall'editor | `ontology.py:363`, `:407-408` | colonne nuove **in sezioni separate** che il serializer conserva byte per byte, come «Categorie» in B1 (`doc/16:107-110`) |
| C5 | **`attributi` è una relazione.** Ogni chiave del frontmatter che non è riservata diventa relazione; senza link dà `property_without_link`. Le chiavi riservate sono in **quattro** posti | `build_graph.py:77,274-280`, `correzioni.py:30`, `graph_edit.py:30`, `ontology.py:15` | `attributi` riservata nei quattro insiemi, con un test che li tiene allineati |
| C6 | **Snapshot già pronto, parser no.** `raw/` è già nello snapshot e nel digest (`storage.py:220`, `PathKind.RAW`) e `.tsv` è già testo condivisibile (`git_sync.py:25`). Manca solo il parser: `parse_snapshot` legge `wiki/*.md` e i tre file di schema | `build_graph.py:206-210`; `graph_service.py:104-112` copia tutto lo snapshot e chiama `parse_snapshot(copy)` | si estende solo `parse_snapshot` (vale per legacy e generazioni); la preview riceve i vocabolari a parte (limite di 8 MiB su Markdown, `ontology_preview.py:131`) |
| C7 | **Le chiavi di `domande.sqlite`.** La domanda sul referente ha chiave `referente|<pagina>|`; rinvii e risposte stanno su quella chiave. Rinominare il segnale in «vincolo» chiuderebbe e riaprirebbe tutte le domande con i rinvii azzerati | `domande.py:143,177`, `Wiki reference.md:93` del kit | il vincolo di default produce segnale e chiave identici a oggi; i vincoli nuovi hanno segnale `vincolo` |

### Correzioni minori

- Numeri di riga sfasati in `build_graph.py`: proprietà come relazioni a `:274-284` (non 262-268), chiavi delle fonti a
  `:87,222` (non 210), `relazioni_dettaglio` a `:285-310` (non 273-298).
- **Il livello 1 non è limitato.** «Chiavi delle fonti» cresce con le fonti (una riga per call). Nel livello 1
  vanno solo il formato delle chiavi e le chiavi citate dalle pagine in lavorazione.
- **Le sezioni h2 non bastano come fette.** Sotto `## Relazioni tipizzate` stanno anche le descrizioni degli
  script (`kit/vault/Wiki reference.md:85-96`, circa un terzo del file). `schema.py` deve estrarre le tabelle e i
  paragrafi di regola, non le sezioni h2 intere.
- Peso attuale: il `Wiki reference.md` del kit pesa 18.232 byte, circa 4.500 token. Sul vault d'esempio il
  guadagno della fase 1 è piccolo; si vede su un vault reale con schema e fonti grandi. La fase 0 richiede quindi un
  vault reale.
- `contratti.py --peso` non deve eseguire comandi: conta in-process la funzione pura di `schema.py`.
- Ogni salita di `BUILDER_VERSION` richiede di aggiornare l'elenco delle versioni accettate in `read_api.py:89`.

### Ordine rivisto e perché

`0 Misurare → 1 Schema mirato → 2 Semantica dichiarata → P (B3) → 3a Sinonimi interni → [go/no-go] → 3b Vocabolari esterni → 4 Attributi → 5 Export`.

La 3a (sinonimi e corrispondenze scritti a mano, senza FIBO) dà gran parte della coerenza dei nomi con il 20% del
costo, perché non servono riduttore, TSV né FTS. La 3b parte solo se la 3a sposta il KPI di coerenza dei nomi e un
vault reale ha davvero un vocabolario esterno da usare. B3 si può fare in parallelo alla fase 2.

### Decisioni (confermate dall'utente il 2026-11-02)

| # | Decisione | Esito | Motivo |
| --- | --- | --- | --- |
| 1 | Dove sta il vocabolario | `raw/vocabolari/` | immutabilità già imposta (`storage.validate_raw_unchanged`, `storage.py:274-279`), condivisione già prevista per `.tsv` |
| 2 | Vincolo violato | domanda aperta per default | è il comportamento di oggi per il referente (una domanda, non un errore); `--check` resta per gli errori di schema |
| 3 | Pagine come individui nell'export | non ora: solo lo schema | l'identità stabile (attributo `id`) è una decisione a sé; si riapre dopo la fase 4 |
| 4 | rdflib | solo CSV in ingresso; niente rdflib | `installa.py:516` copia `kit/graph/*.py`, non `script/`: il kit resta leggero |
| 5 | Vault per la base | **vault ISP** (213 pagine, banco di 106 domande, `doc/kpi-recall.md:48-51`), percorso `VAULT_ISP` | il guadagno si vede solo su uno schema reale |
| 6 | Branch | `ICM_Integration` | C1 |

## User story

Come autore di un vault Teseo in un dominio con un vocabolario consolidato, voglio che lo schema dichiari sinonimi,
ruoli, vincoli e attributi e che il modello ne legga solo la parte che serve, così che ingest e risposte usino gli
stessi nomi e lo stesso significato senza riempire il contesto.

## Problema → soluzione

Oggi lo schema si legge per intero in ingest e lint, la semantica sta nelle costanti del codice, i sinonimi esistono
solo come alias di pagina e non c'è un modo citabile di usare un vocabolario esterno. Dopo, lo schema si legge a
fette con un tetto misurato, la semantica sta in sezioni di `Wiki reference.md` copiate in tabelle `onto_*`, il
recall riceve un piccolo blocco di schema pertinente e i vocabolari esterni sono fonti da cui si promuove un concetto
alla volta.

## Metadati

- **Complessità**: XL (da dividere: un commit verificato per task, una PR per fase)
- **Documento di origine**: proposta incollata in chat (2026-11-02); `doc/16-tassonomia-ontologia-nel-grafo.md`
- **Fase**: piano completo; esecuzione corrente: fase 0 (Medium: 7 file, circa 400 righe)
- **File stimati**: circa 35 (12 nuovi)
- **Base**: branch `ICM_Integration`, `BUILDER_VERSION` 6

---

## UX

### Prima

```
ingest/lint ──▶ legge Wiki reference.md per intero (~4.500 token nel kit, cresce con fonti e schema)
recall ───────▶ fatti: «A → usa → B (B [sistema]: descrizione)»; nessun significato di «usa»
domanda «quali SPV?» ─▶ nessun seme se «SPV» non è alias di una pagina
```

### Dopo

```
ingest/lint ──▶ schema.py --livello 1 (tetto ~3.000) + schema.py --per-pagine P1,P2 (tetto ~1.500)
                [+ schema.py --per-testo raw/x.md: ≤5 candidati dal vocabolario, ~500]
recall ───────▶ fatti + «Schema pertinente»: «usa (dipendenza; inversa: è usato da): X funziona tramite Y»
domanda «quali SPV?» ─▶ «SPV» sinonimo di veicolo_societario ─▶ seme aggregato (B3), un fatto solo
```

### Cambiamenti di interazione

| Punto di contatto | Prima | Dopo | Note |
| --- | --- | --- | --- |
| Input delle skill di ingest e lint | `Wiki reference.md` «tutto» | `schema.py` livello 1 + livello 2 | ripiego: se hai un dubbio leggi tutto |
| Piano di ingest | 5 sezioni | sezione facoltativa `## Concetti dal vocabolario` | `piano.py` la valida |
| Blocco del recall | solo fatti | fatti + al più ~300 token di schema | solo relazioni presenti nei fatti |
| Domande aperte | referente mancante | anche vincoli dichiarati violati | stesse chiavi per il referente |
| Dashboard | — | nessuna modifica obbligatoria; operazioni editor sulle sezioni nuove facoltative (3c) | |

---

## Lettura obbligatoria

| Priorità | File (su `ICM_Integration`) | Righe | Perché |
| --- | --- | --- | --- |
| P0 | `doc/16-tassonomia-ontologia-nel-grafo.md` | tutto | principi, fasi A–E, regole di B3 |
| P0 | `kit/graph/ontology.py` | 13-17, 40-77, 151-214, 304-409 | parser lossless, validazione, serializer: ogni sezione nuova passa di qui |
| P0 | `kit/graph/build_graph.py` | 77-89, 200-378, 392-456 | chiavi riservate, `parse_snapshot`, `parse_documents`, `righe_ontologia`, schema SQL |
| P0 | `kit/vault/Wiki reference.md` | tutto | grammatica attuale e testo da aggiornare |
| P1 | `kit/graph/piano.py` | 1-185 | formato del piano e stile dei controlli |
| P1 | `kit/graph/contratti.py` | 1-40, 184-208 | `peso()` da estendere |
| P1 | `kit/graph/domande.py` | 52-58, 135-182 | segnali, chiavi stabili, referente |
| P1 | `kit/graph/sintesi.py` | 48-98, 108-120 | `CATENA`, `DA_CATENA`, famiglia persona |
| P1 | `kit/graph/recall.py` | 61-90, 405-508 | cammino, punteggio, `formatta` |
| P1 | `kit/graph/misura.py` | 294-410, 488-540, 610-667 | banco, confronto, `--modello`, file per giro |
| P1 | `kit/dashboard/graph_service.py` | 21, 80-135 | `BUILDER_VERSION`, copia dello snapshot, `graph_documents` |
| P1 | `kit/dashboard/ontology_preview.py` | 42-135, 265-290 | operazioni, documenti, `semantic_capabilities` |
| P1 | `kit/dashboard/read_api.py` | 85-120, 325-345 | versioni accettate, `/causal` |
| P2 | `tests/test_tassonomia.py`, `tests/test_ontologia_grafo.py`, `tests/test_banco_tipi.py`, `tests/test_contratti.py`, `tests/test_piano_ingest.py` | tutto | modelli dei test |
| P2 | `doc/kpi-recall.md` | tutto | forma del documento KPI |
| P2 | `kit/skills/obsidian-wiki-ingest/SKILL.md`, `obsidian-wiki-lint/SKILL.md` | Input | contratti da cambiare |
| P2 | `installa.py` | 46-50, 510-535 | quali script si installano, `FACOLTATIVI` |

## Documentazione esterna

Nessuna ricerca web in questa sessione. Prima della fase 3b e della fase 5 si verificano sulle fonti ufficiali:

| Argomento | Fonte da consultare | A cosa serve |
| --- | --- | --- |
| SKOS (`prefLabel`, `altLabel`, `exactMatch`, `closeMatch`, `broader`) | W3C SKOS Reference | semantica di Sinonimi e Corrispondenze; export |
| OWL 2 (`inverseOf`, `TransitiveProperty`, `SymmetricProperty`, `DatatypeProperty`) | W3C OWL 2 Primer | nomi delle proprietà nell'export |
| Turtle | W3C RDF 1.1 Turtle | serializzazione deterministica, escape |
| FIBO Data Dictionary e maturità Release/Provisional | EDM Council | colonne del CSV in ingresso, filtro Release, licenza MIT |
| ESCO CSV | Commissione europea | secondo formato CSV, licenza |
| PROV-O (`wasDerivedFrom`) | W3C PROV-O | provenienza delle definizioni promosse |

---

## Pattern da imitare

### NOMI E DATI DELLO SCHEMA
```python
# SOURCE: kit/graph/ontology.py:47-51, 17
@dataclass(frozen=True)
class Category:
    name: str
    broader: str = ''  # «Più ampia» (skos:broader): vuota per una categoria radice
    description: str = ''
HEADINGS = {'Tipi ammessi': 'types', 'Relazioni tipizzate': 'relations', 'Categorie': 'categories'}
```
Nomi italiani nel codice del grafo, inglesi nelle dataclass di `ontology.py`; codici di errore in inglese
`snake_case` (`unknown_broader`, `category_cycle`).

### ERRORI
```python
# SOURCE: kit/graph/ontology.py:208-213 (validazione → Issue, mai eccezioni)
for name, parent in broader.items():
    if parent not in names or parent == name:
        issues.append(Issue('unknown_broader', name + ': categoria più ampia non dichiarata: ' + str(parent)))
# SOURCE: kit/graph/build_graph.py:238-241 (problemi del build con codice e pagina)
def problem(message, page, prop, code, target=None):
    problemi.append(message)
    problem_details.append({'code': code, 'page': page, 'property': prop, 'reason': message, 'target': target})
# SOURCE: kit/graph/piano.py:77-78 (controlli del piano)
def segnala(codice, riga, messaggio):
    problemi.append({"codice": codice, "riga": riga, "messaggio": messaggio})
```
Nella dashboard: `ContractError(code, reason)` con `details` (`ontology_preview.py:36-39`).

### OUTPUT (niente logging)
```python
# SOURCE: kit/graph/piano.py:200-206
if args.json:
    print(json.dumps(problemi, ensure_ascii=False, indent=2))
else:
    for q in problemi:
        print(f"{args.piano.name}:{q['riga'] or 1}: {q['codice']}: {q['messaggio']}")
```
CLI con `argparse`, `--json`, `sys.stdout.reconfigure(encoding="utf-8")`, exit 1 per problemi. Nessun modulo `logging`.

### COPIA NEL GRAFO
```python
# SOURCE: kit/graph/build_graph.py:370-378 (righe_ontologia) e :437-443 (inserimento)
return {"tipi": tipi,
        "categorie": [(c.name, c.broader or None, c.description, i) for i, c in enumerate(ontology.categories or ())],
        ...
        "metadati": [..., ("categorie", "presenti" if ontology.categories is not None else "assenti")]}
db.executemany("INSERT INTO categorie VALUES (?,?,?,?)", onto["categorie"])
```
Ogni sezione nuova: dataclass → `parse` → `validate` → riga in `righe_ontologia` → tabella in `build_candidate` →
metadato `presenti/assenti`.

### LETTURA DEL GRAFO DA UNO SCRIPT
```python
# SOURCE: kit/graph/piano.py:56-69
riferimento = graph_reference(grafo)
db = connect_graph(grafo, riferimento)
try:
    pagine = {id_.lower(): id_ for (id_,) in db.execute("SELECT id FROM entities WHERE path LIKE 'wiki/%'")}
finally:
    db.close()
```
Una tabella assente in una generazione vecchia si gestisce con `sqlite3.OperationalError` → comportamento di prima
(`recall.py:381-382`).

### TEST
```python
# SOURCE: tests/test_tassonomia.py:1-20, 42-47, 78-89
"""Voce B1 di doc/16: ..."""
import _shortpath  # noqa: F401
import unittest
from kit.graph.ontology import Category, TypeDef, parse, serialize
SCHEMA = '# Schema\n' + TIPI + RELAZIONI + CATEGORIE + FONTI
def documenti(schema=SCHEMA, **pagine):
    return {'Wiki reference.md': schema, **{'wiki/%s.md' % nome: testo for nome, testo in pagine.items()}}
class Parser(unittest.TestCase):
    def test_errori_della_gerarchia(self):
        casi = {'unknown_parent': SCHEMA.replace(...), ...}
        for codice, schema in casi.items():
            with self.subTest(codice):
                self.assertIn(codice, {i.code for i in parse(schema).issues if i.severity == 'error'})
```
`unittest`, non pytest; un file per voce del piano (`test_<voce>.py`); mutazioni dichiarate nel documento
(«quattro mutazioni fatte fallire dai test», `doc/16:127-128`).

---

## File da cambiare

| File | Azione | Fase | Motivo |
| --- | --- | --- | --- |
| `doc/17-concetti-grafo-aziendale.md` | CREATE | 0 | documento di piano nello stile di doc/16 |
| `doc/kpi-coerenza.md` | CREATE | 0 | KPI di coerenza e peso dello schema, accanto a `kpi-recall.md` |
| `kit/graph/coerenza.py` | CREATE | 0 | calcolo deterministico dei KPI da risposte salvate e dal grafo |
| `kit/graph/misura.py` | UPDATE | 0 | `--coerenza DIR`, stabilità fra parafrasi sul banco |
| `kit/graph/banco.py` | UPDATE | 0 | campo facoltativo `parafrasi` in `--verifica` |
| `kit/esempio/banco.json` | UPDATE | 0 | parafrasi d'esempio |
| `installa.py` | UPDATE | 0 | `coerenza.py` fra i `FACOLTATIVI` (`:50`) |
| `doc/README.md`, `README.md`, `CHANGELOG.md` | UPDATE | 0 | indice dei documenti, voce «Non rilasciato» |
| `doc/evidence/concetti-0/` | CREATE | 0 | basi salvate |
| `kit/graph/schema.py` | CREATE | 1 | fette dello schema: `--livello 1`, `--per-pagine`, `--per-tipi`, poi `--per-testo` |
| `kit/graph/contratti.py` | UPDATE | 1 | `peso()` conta `schema.py` in-process |
| `kit/skills/obsidian-wiki-ingest/SKILL.md`, `obsidian-wiki-lint/SKILL.md` | UPDATE | 1 | Input su `schema.py` |
| `kit/vault/AGENTS.md`, `CLAUDE.md`, `copilot-instructions.md` | UPDATE se citano lo schema | 1 | copie volute (`tests/test_istruzioni_coerenti.py`) |
| `kit/graph/ontology.py` | UPDATE | 2, 3a, 4 | sezioni `Semantica delle relazioni`, `Vincoli`, `Sinonimi`, `Corrispondenze`, `Attributi` |
| `kit/graph/build_graph.py` | UPDATE | 2, 3, 4 | tabelle, viste, `attributi` riservata, lettura dei TSV |
| `kit/graph/correzioni.py`, `kit/dashboard/graph_edit.py` | UPDATE | 4 | `attributi` riservata (C5) |
| `kit/graph/domande.py` | UPDATE | 2 | vincoli dichiarati; default identico |
| `kit/graph/sintesi.py` | UPDATE | 2 | catene dai ruoli; default identico |
| `kit/graph/recall.py` | UPDATE | 2, 3a, 4 | blocco «Schema pertinente», inverse, sinonimi come semi, attributi nei fatti |
| `kit/dashboard/read_api.py` | UPDATE | 2, 3, 4 | versioni accettate; `/causal` dal ruolo; `/ontology` con le sezioni nuove |
| `kit/dashboard/graph_service.py` | UPDATE | 2, 3b, 4 | `BUILDER_VERSION` 7, 8, 9 |
| `kit/dashboard/ontology_preview.py` | UPDATE | 2, 3b | `semantic_capabilities`; vocabolari passati alla validazione |
| `kit/graph/piano.py` | UPDATE | 3b | sezione `## Concetti dal vocabolario` |
| `script/riduci_vocabolario.py` | CREATE | 3b | CSV (FIBO Data Dictionary, ESCO) → TSV a colonne fisse |
| `kit/graph/vocabolario.py` | CREATE | 3b | lettura e validazione dei TSV, confronto fra versioni |
| `kit/graph/esporta_rdf.py` | CREATE | 5 | Turtle deterministico dello schema |
| `kit/vault/Wiki reference.md`, `ADATTA.md`, `README.md`, `CHANGELOG.md`, `doc/architettura-motore.md`, `doc/api.md` | UPDATE | ogni fase | documentazione (`CONTRIBUTING.md:50-59`) |
| `tests/test_coerenza.py`, `test_schema_mirato.py`, `test_semantica.py`, `test_vincoli.py`, `test_sinonimi.py`, `test_vocabolari.py`, `test_attributi.py`, `test_esporta_rdf.py` | CREATE | 0–5 | un file per voce |
| `tests/fixtures/vocabolari/` | CREATE | 3b | piccolo CSV e TSV fittizi, niente dati reali |

## Cosa NON si costruisce

- Reasoner, restrizioni OWL, classi definite, SPARQL, Neo4j, sincronizzazione continua con vocabolari esterni.
- Più tipi per pagina: le classi secondarie diventano categorie.
- Archi inversi o dedotti scritti nelle pagine: le deduzioni stanno solo in viste SQL.
- Import automatico o aggiornamento automatico di un concetto promosso.
- Pagine come individui RDF e identificatori stabili di pagina (decisione 3, rinviata).
- rdflib nel kit installato.
- Nuove colonne nella tabella «Relazioni tipizzate» o «Tipi ammessi» (C4): tutto in sezioni separate.
- Personalized PageRank e altre modifiche al cammino di `recall.py` oltre al blocco di schema e ai semi.
- Operazioni dell'editor sulle sezioni nuove nelle fasi 2–4 (si scrivono a mano, come le Categorie in B1); vedi 3c.

---

## Task passo per passo

Metodo per ogni task: documento (doc/17) → test RED in un commit `test(...)` → codice in un commit
`feat(...)`/`fix(...)` → `build_graph.py --check`, suite, `ruff`, `mypy`, `genera_api_doc.py --check`. Formato dei
commit `tipo(scope): descrizione` in italiano (`CONTRIBUTING.md:47-48`).

### Fase 0 — Misurare (2–3 g). Soglia: basi salvate, nessun codice di recall toccato

Commit previsti (formato `tipo(scope): descrizione`, uno per passo verificato):
`docs(17): piano dei concetti da grafo aziendale e KPI di coerenza` → `test(coerenza): KPI di coerenza e parafrasi
del banco (RED)` → `feat(misura): coerenza dei nomi, stabilità fra giri e fra parafrasi` → `docs(17): basi della
fase 0 sul vault d'esempio`.

#### Task 0.1: documento doc/17 e doc/kpi-coerenza.md
- **AZIONE**: CREATE `doc/17-concetti-grafo-aziendale.md` nello stile di doc/16: riga di stato, riferimenti,
  «Teseo rispetto ai grafi aziendali» (la tabella dei concetti presi ed esclusi), principi, correzioni C1–C7,
  fasi 0–5 con soglia e stato, «Fuori perimetro». CREATE `doc/kpi-coerenza.md` con la struttura di
  `doc/kpi-recall.md`. UPDATE `doc/README.md` (riga 17 nella tabella dopo la riga 33; voce KPI vicino alla riga 98) e
  `README.md:508` (riga per `doc/kpi-coerenza.md`).
- **IMPLEMENTARE**: definizioni operative dei KPI (doc/kpi-coerenza.md):
  - **K1 coerenza dei nomi** = menzioni canoniche / menzioni, sulle risposte salvate. Una menzione è un nome di
    pagina, un alias (`aliases`) o una variante (`varianti`) trovato nella risposta come sequenza di parole intere
    dopo `norm`, il nome più lungo per primo e senza sovrapposizioni. È canonica se la forma trovata, dopo `norm`, è
    il nome della pagina. Dalla fase 3a valgono come canonici anche i nomi di tipo e categoria.
  - **K2 stabilità fra giri** = per ogni (domanda, condizione) con almeno 2 giri, la media della somiglianza di
    Jaccard a coppie fra gli insiemi di pagine menzionate; poi la media sulle domande. In più la quota di domande con
    lo stesso esito di correttezza in tutti i giri.
  - **K3 stabilità fra parafrasi** (deterministica, senza modello, misurabile in CI) = per ogni voce del banco con
    `parafrasi`, la media della Jaccard fra le pagine portate dalla domanda e da ciascuna parafrasi, e la quota di
    parafrasi con lo stesso insieme di semi della domanda.
  - **K4 peso dello schema** = token di livello 3 di `contratti.py --peso` per le skill di ingest, lint, query e
    lacune, più il token medio del banco (`misura.py --solo-banco`).
  - Jaccard di due insiemi vuoti = 1.0 (nessuna menzione in entrambe è un accordo).
  - Regola: in una fase K1, K2 e K3 non calano, K4 non sale salvo la fase che lo dichiara; un calo di K1/K2 sotto
    0,05 su 3 giri è rumore e si rimisura prima di decidere.
- **IMITARE**: `doc/kpi-recall.md` (tabella metrica/significato/verso buono, «Come e quando misurare», regola).
- **GOTCHA**: K1 e K2 richiedono `claude` nel PATH e costano: non vanno mai in CI né nella suite. Le basi del vault ISP
  vanno in evidence solo come numeri aggregati (`CONTRIBUTING.md:45-46`).
- **VALIDARE**: link relativi validi (`doc/16-…`, `kpi-recall.md`); la tabella di doc/README.md resta ben formata.

#### Task 0.2: `kit/graph/coerenza.py`
- **AZIONE**: CREATE. Modulo con docstring-contratto (`CONTRIBUTING.md:39-40`) e funzioni pubbliche con la prima
  riga del docstring autonoma (vanno in `doc/api.md`):
  - `jaccard(a, b) -> float`: |a∩b| / |a∪b|, 1.0 se entrambi vuoti.
  - `nomi_del_grafo(db) -> dict[str, tuple[str, bool]]`: `norm(forma) → (pagina, canonica)` da `entities` (solo
    `path LIKE 'wiki/%'`, canonica True), `aliases` e `varianti` (canonica False); una forma che appartiene a più
    pagine si scarta, come `varianti_nomi` (`build_graph.py:136-140`).
  - `menzioni(testo, nomi) -> list[tuple[str, bool]]`: `(pagina, canonica)` nell'ordine del testo; scansione delle
    parole di `norm(testo)` cercando prima le forme più lunghe (al più tante parole quante la forma più lunga).
    Un nome in `recall.PAROLE_COMUNI` conta solo se nel testo originale compare con l'iniziale maiuscola.
  - `leggi_risposte(cartella) -> dict[tuple[int, str], list[dict]]`: legge `NN-<condizione>-G.json` (scritti da
    `misura.py:524` con condizione `ricerca`/`grafo` e da `misura.py:607` con `hook`); chiave `(NN, condizione)`,
    giri ordinati per G. Esito di correttezza: campo `corretta` se c'è, altrimenti `all(regex)` (file `hook`).
    File illeggibili o senza `risposta` si contano a parte, non si scartano in silenzio.
  - `coerenza_nomi(risposte, nomi) -> dict`: `{"menzioni", "canoniche", "quota"}` su tutte le risposte.
  - `stabilita_giri(risposte, nomi) -> dict`: `{"domande", "jaccard_medio", "esito_stabile"}` per condizione.
  - CLI: `python .graph/coerenza.py --risposte DIR [--db .graph/graph.sqlite] [--json]`; stampa una riga per
    condizione, per esempio `grafo: nomi canonici 41/50 (82%) · stabilità fra giri 0.74 · esito stabile 4/5 · 15 risposte`;
    exit 0 (è una misura), exit 2 se la cartella non ha risposte.
- **IMITARE**: lettura del grafo con `connect_graph` come `banco.connetti` (`banco.py:42-45`); stampa e `--json`
  come `piano.py:200-206`; `sys.stdout.reconfigure(encoding="utf-8")`.
- **IMPORT** (piatti, lo script gira da `.graph/`): `from build_graph import norm`, `from graph_db import
  connect_graph, resolve_graph`, `from recall import PAROLE_COMUNI`.
- **GOTCHA**: UPDATE `installa.py:50` → `FACOLTATIVI = {"banco.py", "candidati.py", "coerenza.py"}` (è solo
  l'etichetta «(facoltativo)» nel rapporto, `installa.py:523`): lo script si installa comunque perché
  `installa.py:516` copia tutti i `kit/graph/*.py`. Nessuna chiamata a modelli nel modulo.
- **VALIDARE**: `tests/test_coerenza.py` (vedi la strategia di test); mutazioni da far fallire: alias contato come
  canonico; Jaccard di due vuoti a 0; parola comune minuscola contata.

#### Task 0.3: `parafrasi` nel banco e K3 in `misura.py`
- **AZIONE**:
  - `banco.verifica` (`banco.py:141-182`): `parafrasi` facoltativa; se c'è deve essere una lista di testi non vuoti,
    altrimenti ERRORE `voce N «…»: «parafrasi» deve essere una lista di domande`; ogni parafrasi diversa (dopo `norm`)
    dalla domanda, dalle altre parafrasi e dalle domande delle altre voci (ERRORE `parafrasi uguale alla voce N`);
    AVVISO di eco del titolo come per la domanda (`banco.py:177-181`). Aggiornare il docstring (`banco.py:3-16`).
  - `misura.carica_banco` (`misura.py:294-311`): `parafrasi`, se c'è, è una lista di stringhe.
  - `misura.misura_banco` (`misura.py:314-343`): per le voci con parafrasi, `esito_banco` su ogni parafrasi; nell'esito
    della voce `"parafrasi": [{"domanda", "semi", "portate"}]`, `"stabilita": media jaccard(portate)` e
    `"stesso_seme": n parafrasi con set(semi) == set(semi della domanda)`. Dopo le righe di riepilogo, se almeno una
    voce ha parafrasi: `parafrasi: N voci, M parafrasi · stabilità media 0.83 · stesso seme 5/7`. Le parafrasi non
    entrano nelle righe per domanda né nel riepilogo esistente (i numeri di oggi non cambiano).
  - `misura.confronta_banco` (`misura.py:373-418`): se entrambi gli esiti hanno `stabilita`, una riga in coda
    `stabilità fra parafrasi: 0.83 → 0.86 (+0.03)` sulla media delle voci presenti in entrambi.
  - `kit/esempio/banco.json`: `parafrasi` su due voci locali (testi fittizi, senza le parole dei titoli).
- **IMITARE**: come B2 ha aggiunto `tipo` (`misura.py:305,329,339-342,402-403`; `banco.py:163-164`;
  `tests/test_banco_tipi.py`).
- **GOTCHA**: `carica_salvataggio` (`misura.py:363-370`) controlla solo i campi obbligatori: un salvataggio vecchio
  senza `stabilita` resta valido e il confronto salta la riga. `test_riepilogo_totale_e_per_tipo`
  (`tests/test_banco_tipi.py:48-58`) filtra le righe per prefisso: la riga nuova inizia con `parafrasi:` e non lo
  rompe. I numeri delle righe `banco:` devono restare identici con e senza parafrasi (test esplicito).
- **VALIDARE**: `python -m unittest tests.test_banco_tipi tests.test_coerenza -v`; sul vault d'esempio installato in
  una cartella temporanea `banco.py --verifica` senza errori.

#### Task 0.4a: basi sul vault d'esempio
- **AZIONE**: in una cartella temporanea con il vault d'esempio (`python installa.py --prova` o copia come
  `tests/test_banco_tipi.py:28-38`) salvare in `doc/evidence/concetti-0/`:
  `banco-esempio-base.txt` e `.json` (`misura.py --solo-banco --banco-salva`), `peso-skill.txt`
  (`python kit/graph/contratti.py kit/skills/*/SKILL.md --radice kit/vault --peso`). Citarli in doc/17 con i numeri.
- **VALIDARE**: i file esistono; i numeri in doc/17 coincidono con i file.

#### Task 0.4b: basi sul vault ISP (richiede `VAULT_ISP`)
- **AZIONE**: con il percorso del vault:
  1. `python kit/graph/misura.py --db "$VAULT_ISP/.graph/graph.sqlite" --banco "$VAULT_ISP/.graph/banco.json"
     --solo-banco --banco-salva "$VAULT_ISP/.graph/banco_base_2026-11-XX.json"` (sola lettura del vault; il salvataggio
     resta nel vault);
  2. `python kit/graph/contratti.py kit/skills/*/SKILL.md --radice "$VAULT_ISP" --peso`;
  3. **solo con il via esplicito dell'utente** (costa, usa `claude -p`): `misura.py --modello <haiku> --giri 3 --out
     <cartella fuori dal repo>` dalla copia installata nel vault (`misura_modello` usa `qui.parent` come vault,
     `misura.py:514`), poi `python kit/graph/coerenza.py --risposte <cartella> --db "$VAULT_ISP/.graph/graph.sqlite"`.
  4. In doc/17 e in `doc/evidence/concetti-0/isp-aggregati.md` solo i numeri aggregati.
- **GOTCHA**: il banco ISP non ha `parafrasi`: K3 sull'ISP richiede di aggiungerle (decisione dell'autore del vault,
  non di questo piano). `DOMANDE` di `misura.py` nella copia del vault sono quelle del vault, non dell'esempio.
- **VALIDARE**: aggregati presenti; nessun nome di pagina o testo del vault ISP nel repository.

### Fase 1 — Schema mirato (3–4 g). Soglia: K4 giù; recall sul banco e K1–K3 invariati

#### Task 1.1: `kit/graph/schema.py`
- **AZIONE**: CREATE. Funzione pura `fette(ontology_source, *, livello=1, tipi=(), pagine_tipi=None) -> str` e CLI:
  `--livello 1`, `--per-pagine "A,B"` (tipi letti dal grafo), `--per-tipi "x,y"`, `--json`, `--tetto` (solo avviso).
- **IMPLEMENTARE**:
  - livello 1: «Regole non negoziabili», «Convenzioni delle pagine» (senza il blocco «Pagine generate per entropia»,
    che va nel livello 2 del lint), formato delle chiavi delle fonti, **indice dei nomi** di tipi, relazioni e
    categorie, uno per voce, senza descrizioni;
  - livello 2: le righe complete dei tipi indicati e dei loro antenati (`Ontology.ancestors`); le relazioni con
    quei tipi in `Da` o in `A` (antenati e `qualsiasi` compresi, stessa regola di `tipo_ammesso`,
    `build_graph.py:189-197`); le chiavi delle fonti citate dalle pagine; dalla fase 2 anche vincoli, ruoli e inverse,
    dalla 3a sinonimi e corrispondenze, dalla 4 gli attributi.
  - estrazione per **tabelle e paragrafi**, non per sezioni h2 (le descrizioni degli script stanno sotto «Relazioni
    tipizzate»).
- **IMITARE**: `ontology.parse` per le tabelle; `contratti.testo_sezione` (`contratti.py:170-181`) per i paragrafi.
- **GOTCHA**: senza catalogo «Tipi ammessi» (vault legacy) il livello 2 cade sul livello completo delle relazioni;
  con un errore di schema stampa un avviso e consiglia di leggere `Wiki reference.md` per intero. Output
  deterministico (stesso ordine del documento).
- **VALIDARE**: `tests/test_schema_mirato.py`: livello 1 senza descrizioni; per-tipi con antenati e `qualsiasi`;
  tetto superato → avviso, exit 0; vault senza catalogo; la somma delle fette non perde regole non negoziabili.

#### Task 1.2: `contratti.py --peso` conta `schema.py`
- **AZIONE**: UPDATE `peso()` (`contratti.py:184-208`). Una cella File `` `python .graph/schema.py --livello 1` ``
  si conta chiamando in-process `schema.fette`. Le varianti con argomenti di esecuzione (`--per-pagine {pagine}`)
  valgono quanto il tetto dichiarato, marcate come stima.
- **GOTCHA**: non eseguire mai comandi; la regex `COMANDO` (`:37`) oggi li scarta: aggiungere un caso esplicito
  solo per `schema.py`, con argomenti presi da una lista chiusa.
- **VALIDARE**: `tests/test_contratti.py`: un contratto con `schema.py` ha `livello3` > 0; un comando diverso resta ignorato.

#### Task 1.3: contratti di ingest e lint
- **AZIONE**: UPDATE `obsidian-wiki-ingest/SKILL.md:22` e `obsidian-wiki-lint/SKILL.md:34`: due righe di Input
  (`schema.py --livello 1` sempre; `schema.py --per-pagine` sulle pagine del piano o del lint) e la regola di ripiego
  già usata da query e lacune (`fill-gaps/SKILL.md:155`).
- **GOTCHA**: il lint completo può toccare tutto il vault: per il lint completo resta «tutto». Le regole e gli elenchi
  copiati nei file client vanno cambiati insieme (`tests/test_istruzioni_coerenti.py`).
- **VALIDARE**: `python kit/graph/contratti.py kit/skills/*/SKILL.md --radice kit/vault --peso` mostra il calo;
  confronto con la base 0.4 in doc/17.

### Fase 2 — Semantica dichiarata (5–7 g). Soglia: con le sezioni assenti, output di `domande.py --json` e `sintesi.py --json` identici byte per byte sul vault d'esempio

#### Task 2.1: sezione `## Semantica delle relazioni`
- **AZIONE**: UPDATE `ontology.py`: `HEADINGS['Semantica delle relazioni'] = 'semantics'`, dataclass
  `RelationSemantics(name, role, inverse, properties)`, tabella `Relazione | Ruolo | Inversa | Proprietà`.
- **IMPLEMENTARE**: `Ruolo` in un insieme chiuso `RUOLI = ('dipendenza', 'responsabile', 'composizione',
  'causale', 'sequenza')` o vuoto; `Inversa` è un nome leggibile («è usato da»), testo libero ma `_text`: solo un nome di
  lettura, mai un arco (decisione 7 di doc/17); `Proprietà`
  è un sottoinsieme di `transitiva, simmetrica, aciclica`. Errori: `unknown_relation` (relazione non nella tabella relazioni),
  `invalid_role`, `invalid_property`, `duplicate_semantics`, `symmetric_with_inverse`,
  `symmetric_acyclic` (una relazione simmetrica forma sempre un giro A → B → A).
- **GOTCHA**: C3 e C4. Il serializer non tocca questa sezione: estendere `source_spans` e `opaque_bytes` come per le
  categorie. Una rinomina dall'editor che lascia un nome vecchio nella sezione deve far fallire la preview
  (`unknown_relation`), non perdere righe in silenzio: test esplicito.
- **VALIDARE**: `tests/test_semantica.py` sugli errori del parser; roundtrip byte per byte; rinomina relazione →
  preview con `invalid_schema`.

#### Task 2.2: tabelle e viste (`BUILDER_VERSION` 7)
- **AZIONE**: UPDATE `build_graph.py`: colonne `ruolo`, `inversa`, `transitiva`, `simmetrica` in `onto_relazioni`
  (NULL/0 senza sezione); vista `relazioni_dedotte(source_id, target_id, type, via, origine)`: chiusura transitiva con CTE
  ricorsiva limitata in profondità (3), simmetriche speculari, `origine = 'dedotto'`; `via` = le pagine intermedie in ordine, separate da ` → `, accumulate nella CTE
  (servono già a fermare la profondità), vuota per un fatto a un passo; i percorsi che tornano sul nodo di partenza
  non producono fatti (niente «A precede A»); metadato `semantica` =
  `presente/assente`. UPDATE `graph_service.py:21` → 7 e `read_api.py:89` (+ `"7"`).
- **IMITARE**: CTE ricorsiva delle sottocategorie di B1 (`GET /graph?category=`).
- **GOTCHA**: i ruoli di default (`usa`, `richiede` → dipendenza; `referente` → responsabile; `parte_di` →
  composizione; `causa` → causale) valgono **solo nel codice di lettura**, non vengono scritti nelle tabelle: con la
  sezione assente `onto_relazioni.ruolo` è NULL e `onto_metadata.semantica = assente`. Le generazioni 6 restano
  leggibili.
- **VALIDARE**: `tests/test_ontologia_grafo.py` aggiornato (colonne nuove); query della vista su una catena
  transitiva di 4 nodi; generazione 6 aperta senza errori.

#### Task 2.3: `sintesi.py`, `domande.py`, `/causal`, `recall.formatta` leggono i ruoli
- **AZIONE**: funzione condivisa `ruoli(db)` → `{relazione: ruolo}`: dalle tabelle se `semantica = presente`,
  altrimenti `RUOLI_DEFAULT`. `CATENA` = relazioni con ruolo dipendenza o responsabile; `"referente"` →
  responsabile in `sintesi.py:95,110`; `parte_di` in `domande.py:100,173` → composizione; `read_api.py:334` →
  causale. `formatta` aggiunge l'inversa per i fatti a ritroso: «B ← usa (è usato da) ← A»; un fatto
  dedotto si scrive «A dipende da C (dedotto, via B)».
- **GOTCHA**: la funzione va in un modulo che non importa `recall` (catena di import `recall → domande →
  build_graph`, vedi il commento a `build_graph.py:58-59`): metterla in `build_graph.py` o in un `semantica.py` leggero
  importato in modo lazy. `precede` resta fuori da `CATENA` per default (commento a `sintesi.py:49`).
- **VALIDARE**: test golden: `domande.py --json` e `sintesi.py --json` sul vault d'esempio identici prima e dopo
  (salvati nel commit RED); una sezione che dà ruolo `dipendenza` a `precede` cambia le catene (mutazione).

#### Task 2.4: sezione `## Vincoli` e domande aperte
- **AZIONE**: UPDATE `ontology.py` (tabella `Tipo | Relazione o attributo | Minimo | Massimo | Se manca`; `Se manca`
  ∈ `domanda`, `nulla`), `build_graph.py` (tabella `onto_cardinalita`), `domande.py` (un segnale per vincolo violato).
- **IMPLEMENTARE**: senza sezione vale il vincolo di default `sistema|processo|progetto · referente · 1 · · domanda`,
  con l'eccezione di oggi «una parte ha il referente del tutto» (`domande.py:172-178`).
- **GOTCHA**: C7, segnale `referente` e chiave `referente|<pagina>|` per il vincolo sul referente, anche se
  dichiarato; segnale `vincolo` per gli altri, aggiunto in `ORDINE` (`domande.py:55`) dopo `referente`; segnale
  `ciclo` per le relazioni `aciclica` (decisione 8), subito dopo `vincolo`: visita completa delle relazioni tipizzate di
  quella relazione (non la vista, limitata a 3 passi), una domanda per ciclo con chiave `ciclo|<relazione>|<pagine del
  ciclo ruotate a partire dalla minore>`, testo «Ciclo su `precede`: A → B → A. Quale ordine è giusto?» e le fonti
  delle pagine. Massimo
  superato → domanda, mai errore di build (decisione 2).
- **VALIDARE**: `tests/test_vincoli.py`; un `domande.sqlite` con un rinvio sul referente mantiene il rinvio dopo
  l'aggiornamento.

#### Task 2.5: blocco «Schema pertinente» nel recall
- **AZIONE**: `recall.formatta` (o `recall_hook`) aggiunge al più `MAX_SCHEMA_TOKEN = 300` token: per ogni relazione
  presente nei fatti, una riga «nome (ruolo; inversa): significato». Si tiene solo se la fase 2 lo misura neutro o
  positivo su K1/K2.
- **GOTCHA**: il token medio del banco sale: il confronto (`misura.py:373-410`) lo segnalerà; la soglia della fase lo
  accetta solo con K1/K2 non in calo. Interruttore `GRAFO_SENZA_SCHEMA=1` come gli altri (`misura.py:497`).
- **VALIDARE**: `tests/test_recall_testo.py` o nuovo test su `formatta`; `misura.py --solo-banco --banco-confronta` con la base 0.4.

#### Task 2.6: `semantic_capabilities`
- **AZIONE**: `ontology_preview.py:272` → `automatic_inference` diventa l'elenco dei comportamenti attivati (es.
  `["inverse_labels", "transitive_views"]`), vuoto senza sezione (`doc/16:166`).
- **VALIDARE**: `tests/test_dashboard_preview.py` aggiornato.

### Task P — B3 di doc/16 (3–4 g, in parallelo alla fase 2). Soglia di doc/16:152

- **AZIONE**: implementare B3 come già specificato (`doc/16:146-152`): categoria nominata → un seme, un fatto
  aggregato con al più `MAX_CATEGORIA` pagine scelte per rilevanza e diversità (MMR), `SOGLIA_CATEGORIA`, peso
  decrescente per le sottocategorie, la pagina vince sulla categoria omonima.
- **GOTCHA**: non cambia `BUILDER_VERSION` (le tabelle esistono da B1). Generazioni 5 senza `categorie` → nessun seme
  di categoria, nessun errore.
- **VALIDARE**: `misura.py --solo-banco --banco-confronta doc/evidence/tassonomia-b2/banco-esempio-base.json`:
  globali su, locali non giù, semi spuri invariati. Aggiornare doc/16.

### Fase 3a — Sinonimi e corrispondenze interni (3–4 g). Soglia: K1 su; semi spuri invariati

#### Task 3a.1: sezioni `## Sinonimi` e `## Corrispondenze`
- **AZIONE**: `ontology.py`: `Sinonimi` = `Nome | Sinonimi` (nome di tipo o categoria; sinonimi separati da `;`),
  `Corrispondenze` = `Nome | Corrispondenza | Vocabolario | Esattezza` (`Esattezza` ∈ `esatta`, `vicina`; IRI o
  CURIE; `Vocabolario` = chiave censita in «Chiavi delle fonti»).
- **IMPLEMENTARE**: errori `unknown_name`, `synonym_collision` (un sinonimo uguale dopo `norm` a un altro nome, alias
  o sinonimo), `unknown_vocabulary_key`, `invalid_iri`. Tabelle `onto_sinonimi(nome, sinonimo)` e
  `onto_corrispondenze(nome, iri, vocabolario, esattezza)`. `BUILDER_VERSION` 8.
- **GOTCHA**: un sinonimo uguale al nome o all'alias di una pagina: la pagina vince (`doc/16:152`), il sinonimo non fa
  da seme, avviso in `--check`. Solo `esatta` può ereditare i sinonimi da un vocabolario (fase 3b).
- **VALIDARE**: `tests/test_sinonimi.py`.

#### Task 3a.2: sinonimo → seme aggregato
- **AZIONE**: in `recall.punti_di_partenza`, un sinonimo di categoria o di tipo nominato nella domanda produce lo
  stesso seme di B3 (categoria) o un seme di tipo con lo stesso fatto aggregato.
- **GOTCHA**: dipende da P. `PAROLE_COMUNI` vale anche per i sinonimi.
- **VALIDARE**: banco d'esempio con una domanda per sinonimo; `misura.py` (semi spuri 0) e confronto.

#### Go/no-go dopo la 3a
Si procede con la 3b solo se K1 sale sul vault reale **e** l'utente ha un vocabolario esterno concreto. Altrimenti
si passa alla fase 4 e la 3b resta proposta in doc/17.

### Fase 3b — Vocabolari esterni come fonti (5–7 g). Soglia: K1 su rispetto alla 3a; semi spuri invariati

#### Task 3b.1: `script/riduci_vocabolario.py` (strumento di sviluppo)
- **AZIONE**: CREATE. CSV in ingresso (FIBO Data Dictionary, ESCO) → TSV UTF-8 con colonne fisse
  `iri, genere, etichetta, etichetta_it, sinonimi, definizione, piu_ampio, da, a, valore, maturita, deprecato`.
  `--solo-release`, ordine stabile per IRI, nessuna rete.
- **GOTCHA**: solo libreria standard (`csv`). Più genitori: il primo è il principale, gli altri vanno in una colonna
  di categorie suggerite oppure si scartano, da decidere in doc/17. Licenze share-alike rifiutate senza
  `--accetta-share-alike` (rischio dichiarato nella proposta).
- **VALIDARE**: test su `tests/fixtures/vocabolari/` (CSV fittizio di 10 righe): TSV atteso byte per byte.

#### Task 3b.2: lettura dei TSV nel build (`kit/graph/vocabolario.py`)
- **AZIONE**: `parse_snapshot` (`build_graph.py:206-210`) legge anche `raw/vocabolari/*.tsv`; `parse_documents` li
  riceve sotto le stesse chiavi di percorso. `vocabolario.leggi(testo)` valida intestazione, limiti (4 MiB, 20.000 righe
  per file), IRI univoci. Il nome del file senza estensione deve essere una chiave censita in «Chiavi delle fonti».
  Tabelle `onto_vocabolario(chiave, iri, …)` e FTS5 `onto_vocabolario_testo(etichette, sinonimi)` con lo stesso
  tokenizer di `testo` (`build_graph.py:426-427`).
- **GOTCHA**: C6, lo snapshot e il digest includono già `raw/`: aggiungere un TSV crea già una nuova generazione.
  `graph_documents` (`graph_service.py:128-131`) resta limitato al Markdown. La preview dell'ontologia passa i
  vocabolari alla validazione fuori dal limite degli 8 MiB di Markdown (`ontology_preview.py:131`). `raw/` resta
  immutabile: un trimestre nuovo è un file nuovo.
- **VALIDARE**: `tests/test_vocabolari.py`: build legacy e a generazioni; TSV oltre limite → errore con il nome del
  file; chiave non censita → `source_missing`.

#### Task 3b.3: `schema.py --per-testo raw/x.md`
- **AZIONE**: al più 5 candidati dal vocabolario, trovati con la FTS sulle parole della fonte (radici con
  `ridotto`), esclusi i già promossi (presenti in `onto_corrispondenze`) e i deprecati, prima `Release`. Output:
  IRI, etichetta, definizione breve, genere, `piu_ampio`.
- **VALIDARE**: fixture con una fonte che cita «SPV»: un solo candidato atteso; tetto ~500 token.

#### Task 3b.4: `## Concetti dal vocabolario` in `piano.py`
- **AZIONE**: sezione facoltativa (non entra nelle cinque obbligatorie di `piano.py:31-32`), righe
  `- nome_italiano ← <chiave> <IRI o nome locale> (genere; sottotipo di X)`. Controlli: chiave censita, IRI presente
  nel vocabolario, non deprecato, nome valido (`ontology._name`), nome non già usato.
- **IMITARE**: `RELAZIONE`/`segnala` di `piano.py:36,145-167`.
- **GOTCHA**: regex lineari su input ostili (commento a `piano.py:34`; test esistenti sugli input ostili).
- **VALIDARE**: `tests/test_piano_ingest.py` esteso.

#### Task 3b.5: promozione e lint delle versioni
- **AZIONE**: l'ingest scrive le righe promosse in `Tipi ammessi`/`Categorie`, `Corrispondenze` e (fase 4)
  `Attributi`, come oggi scrive le «Chiavi delle fonti»; nei vault gestiti passa dalla validazione dell'operazione
  (`operation_validation.py:26`). Il lint confronta due versioni dello stesso vocabolario (stesso prefisso di chiave,
  versione diversa) **solo sui concetti promossi**: definizione cambiata o concetto deprecato → contraddizione fra
  fonti registrata nella pagina e nei punti aperti di `index.md`, mai aggiornata da sola.
- **VALIDARE**: test su due TSV di fixture; contratto di lint aggiornato.

#### Task 3c (facoltativo, 2–3 g): operazioni dell'editor
- `add/update/remove/rename_category` e le operazioni sulle sezioni nuove in `ontology_preview._patch`
  (`:56-106`). Da pianificare a parte se l'uso reale lo chiede.

### Fase 4 — Attributi (4–6 g). Soglia: nessun peggioramento di recall e K1–K3

#### Task 4.1: sezione `## Attributi` e chiave `attributi`
- **AZIONE**: tabella `Attributo | Di (tipo) | Valore | Descrizione`; `Valore` ∈ `testo, numero, data, importo,
  codice, sì/no, categoria:X`. Frontmatter `attributi: {nome: valore}`. Tabelle `onto_attributi` e
  `entity_attributi(entity_id, attributo, valore)`. `BUILDER_VERSION` 9.
- **GOTCHA**: C5, `attributi` in `build_graph.NON_RELAZIONI`, `correzioni.NON_RELAZIONI`, `graph_edit.RESERVED`,
  `ontology.SPECIAL`, con un test che confronta i quattro insiemi. Un vault con una relazione chiamata `attributi`
  riceve `reserved_relation`: da scrivere in `ADATTA.md`. Le date YAML arrivano come `datetime.date`: normalizzare a
  ISO prima del confronto. Errori: `unknown_attribute`, `attribute_type`, `attribute_value`.
- **VALIDARE**: `tests/test_attributi.py`.

#### Task 4.2: attributi nei fatti del recall e nei vincoli
- **AZIONE**: `formatta` aggiunge gli attributi del seme («data_liquidazione_prevista: 2031-12-31»); i vincoli
  della fase 2 possono riferirsi a un attributo.
- **VALIDARE**: confronto del banco; token medio entro +5%.

### Fase 5 — Export Turtle dello schema (2–3 g). Soglia: golden file stabile

#### Task 5.1: `kit/graph/esporta_rdf.py`
- **AZIONE**: CREATE. Dal grafo corrente: tipi → `owl:Class` + `rdfs:subClassOf`; categorie → `skos:Concept` +
  `skos:broader`; relazioni → `owl:ObjectProperty` con `rdfs:domain/range` quando univoci, `owl:inverseOf` solo se è
  dichiarata un'inversa con IRI, `owl:TransitiveProperty`/`SymmetricProperty`; attributi → `owl:DatatypeProperty`;
  corrispondenze → `skos:exactMatch`/`closeMatch`; sinonimi → `skos:altLabel "…"@it`; provenienza →
  `prov:wasDerivedFrom` verso la chiave del vocabolario. Base IRI da `--base`.
- **GOTCHA**: ordine totale delle triple (ordinamento per soggetto, predicato, oggetto), escape Turtle, nessuna data
  nell'output. Sola lettura. Nessuna libreria esterna.
- **VALIDARE**: `tests/test_esporta_rdf.py` con golden file del vault d'esempio; due esecuzioni producono byte identici.

---

## Strategia di test

### Test unitari principali

| Test | Ingresso | Atteso | Caso limite |
| --- | --- | --- | --- |
| `jaccard` | `{a,b}`, `{b,c}`; due vuoti | 1/3; 1.0 | sì |
| `menzioni` | «Anna Rossi e il Modulo fatture» sul vault d'esempio | `[("Anna Rossi", True), ("Modulo fatture", True)]` | — |
| `menzioni` con alias e variante | alias del vault d'esempio; «service desk» | canonica False per entrambi, pagina giusta | nome più lungo vince |
| `menzioni` parola comune | `PAROLE_COMUNI` con un nome di pagina, testo minuscolo | nessuna menzione | sì |
| `coerenza_nomi` | 2 risposte, 3 canoniche su 4 | quota 0.75 | — |
| `leggi_risposte` | cartella con `01-grafo-1.json`, `01-grafo-2.json`, `01-hook-1.json`, un file rotto | 2 chiavi, 1 illeggibile contato | sì |
| `stabilita_giri` | 3 giri, insiemi {A,B}, {A,B}, {A} | jaccard medio (1 + 0.5 + 0.5)/3 | esiti diversi → non stabile |
| CLI `coerenza.py` | cartella vuota | exit 2 | sì |
| `banco.verifica` parafrasi | non lista; duplicata; eco del titolo | ERRORE; ERRORE; AVVISO | — |
| `misura_banco` con parafrasi | banco d'esempio con parafrasi | riga `parafrasi:`; righe `banco:` identiche a senza parafrasi | sì |
| `confronta_banco` | salvataggio vecchio senza `stabilita` | nessuna riga di stabilità, nessun errore | sì |
| fette livello 1 | schema del kit | nessuna descrizione di tipo; regole presenti | schema senza catalogo |
| fette livello 2 | tipo `portale` | righe di `portale`, `servizio`, `sistema` e relazioni ammesse | `qualsiasi`, `stesso tipo` |
| peso con `schema.py` | contratto di ingest | livello 3 > 0 | comando non ammesso ignorato |
| semantica parser | ruolo fuori insieme | `invalid_role` | simmetrica con inversa |
| rinomina vs semantica | `rename_relation` | preview `invalid_schema` | — |
| default identico | vault d'esempio senza sezioni | `domande --json`, `sintesi --json` byte per byte | — |
| vincolo referente | rinvio esistente | rinvio conservato | parte di un tutto |
| vista dedotta | catena transitiva lunga | profondità ≤ 3, `via` con le pagine intermedie | ciclo: nessun «A → A» |
| ciclo `aciclica` | `precede` A → B → A; giro di 5 pagine; A → A | una domanda per ciclo, segnale `ciclo`, chiave stabile | `aciclica` con `simmetrica` → `symmetric_acyclic` |
| sinonimo vs pagina | sinonimo = alias | la pagina vince, avviso | maiuscole/accenti |
| TSV | 20.001 righe | errore con nome file | BOM, CRLF |
| piano con concetti | IRI deprecato | `concetto_deprecato` | input ostile lungo |
| attributi | data YAML | valore ISO | relazione chiamata `attributi` |
| export | vault d'esempio | golden identico | caratteri da escapare |

### Casi limite

- [ ] Schema vuoto o assente (vault legacy): ogni fase degrada al comportamento di oggi
- [ ] Generazioni 4–6 aperte dopo ogni salita di versione
- [ ] Input enormi: tetti di righe e byte su ogni tabella e TSV (`MAX_ROWS = 2048`, `MAX_BYTES` a `ontology.py:13-14`)
- [ ] CRLF e BOM in `Wiki reference.md` e nei TSV
- [ ] Windows: percorsi brevi nei test (`tests/_shortpath.py`)
- [ ] Nessuna chiamata a modelli nella suite

---

## Comandi di validazione

### Analisi statica
```sh
ruff check .
mypy
```
ATTESO: nessun errore.

### Test per area
```sh
python -m unittest tests.test_coerenza tests.test_schema_mirato tests.test_semantica tests.test_vincoli -v
python -m unittest tests.test_tassonomia tests.test_ontologia_grafo tests.test_banco_tipi tests.test_contratti tests.test_piano_ingest -v
```
ATTESO: tutti verdi.

### Suite completa e installazione
```sh
python -m unittest discover -s tests -v
python installa.py --prova
python script/genera_api_doc.py --check
```
ATTESO: nessuna regressione; `doc/api.md` aggiornato.

### Grafo e KPI (vault d'esempio, poi vault reale)
```sh
python .graph/build_graph.py --check
python .graph/misura.py
python .graph/misura.py --solo-banco --banco-confronta <base fase 0>
python .graph/contratti.py kit/skills/*/SKILL.md --radice kit/vault --peso
python .graph/coerenza.py --risposte <cartella di misura.py --modello>   # solo vault reale, fuori CI
```
ATTESO: le soglie della fase.

### Browser
Solo se si fa la 3c o si cambia `/ontology` nella UI: `tests/dashboard_tassonomia_browser.py` come modello, a
1440×900 e 390×844.

### Verifica manuale
- [ ] Ingest di una fonte d'esempio con il contratto nuovo: il modello legge le fette, non tutto il file
- [ ] Domanda con un sinonimo: un fatto aggregato, nessun seme spurio
- [ ] Un vincolo violato compare una sola volta come domanda aperta

---

## Criteri di accettazione

- [ ] Fase 0: KPI definiti in doc/kpi-coerenza.md; basi salvate per il vault d'esempio e per il vault reale
- [ ] Fase 1: K4 in calo misurato; banco e K1–K3 invariati
- [ ] Fase 2: con le sezioni assenti domande e sintesi identiche; con le sezioni, comportamento dichiarato e testato
- [ ] P: regola di B3 rispettata (locali non giù, semi spuri invariati)
- [ ] Fase 3a: K1 su; go/no-go registrato in doc/17
- [ ] Fase 3b (se fatta): K1 su rispetto alla 3a; vocabolari riproducibili nel build
- [ ] Fase 4: nessun peggioramento
- [ ] Fase 5: golden stabile
- [ ] Ogni fase: suite, ruff, mypy, `genera_api_doc.py --check`, `installa.py --prova` verdi; doc/17, doc/16 (C, D, E),
      `Wiki reference.md` del kit, `ADATTA.md`, `CHANGELOG.md` aggiornati

## Checklist di completamento

- [ ] Codice nei pattern scoperti (parser lossless, `Issue`, `problem`, tabelle `onto_*`)
- [ ] Errori come codici `snake_case` con pagina e proprietà
- [ ] Output CLI con `--json` e exit 1 per problemi, niente `logging`
- [ ] Test `unittest`, un file per voce, mutazioni dichiarate
- [ ] Costanti nominate (`MAX_SCHEMA_TOKEN`, `RUOLI`, limiti dei TSV), niente numeri sparsi
- [ ] Nessuna dipendenza nuova nel kit
- [ ] Nessuna aggiunta fuori perimetro

## Rischi

| Rischio | Probabilità | Impatto | Mitigazione |
| --- | --- | --- | --- |
| Perdita di colonne o righe per il serializer | alta se si estendono le tabelle esistenti | alto | C4: sezioni separate conservate byte per byte; test di roundtrip e di rinomina |
| Domande riaperte con rinvii azzerati | media | medio | C7: segnale e chiave invariati; test con `domande.sqlite` esistente |
| KPI di coerenza rumoroso (risposte variabili) | alta | medio | `--giri ≥ 3`, sempre lo stesso modello, K3 deterministico come controllo; decisioni su differenze ripetute, non su un giro |
| Schema troppo ricco per il modello | media | medio | tetti di livello come avviso di `schema.py --tetto` e `--check` |
| Rumore dai sinonimi | media | medio | la pagina vince, collisioni rifiutate, solo `esatta` eredita, soglia di B3 |
| Vocabolari grandi nel build | bassa | medio | limiti per file, FTS solo su etichette e sinonimi, nessun byte nel contesto senza richiesta |
| Deriva della traduzione | media | basso | `Esattezza: vicina` quando l'equivalenza non è esatta; scelta del vault |
| Licenze | bassa | alto | chiave e licenza nella riga della fonte; share-alike rifiutate senza flag |
| Scope creep (XL) | alta | alto | go/no-go dopo la 3a; 3b, 3c e individui RDF separati |
| Dati reali nel repository | bassa | alto | in evidence solo aggregati |

## Note

- La proposta incollata aveva colonne troncate (per esempio le colonne di «Corrispondenze» e «Vincoli»). Le
  intestazioni delle tabelle in questo piano sono una ricostruzione da confermare in doc/17.
- Stime: fase 0 2–3 g, fase 1 3–4 g, fase 2 5–7 g, P 3–4 g, fase 3a 3–4 g, fase 3b 5–7 g, 3c 2–3 g, fase 4 4–6 g,
  fase 5 2–3 g. Totale 27–38 g con P e 3c; 20–28 g fino alla 3a più fasi 4 e 5, senza 3b e 3c.
- `BUILDER_VERSION`: 7 (fase 2), 8 (fase 3a, con le tabelle di 3b se si fa subito), 9 (fase 4); una salita per fase.
- Branch e vault confermati il 2026-11-02. I commit si fanno su `ICM_Integration`, uno per passo verificato;
  nessun push senza richiesta esplicita.
- Le misure con modello (K1, K2 sul vault ISP) si lanciano solo con il via esplicito dell'utente.

# Registro delle modifiche

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).
Il progetto non ha ancora release con tag: la storia è ricostruita dai commit
e raggruppata per traguardo; le voci nuove si aggiungono sotto «Non rilasciato».

## [Non rilasciato]

### Aggiunto

- Voce B2 del [piano 16](doc/16-tassonomia-ontologia-nel-grafo.md): le domande del banco hanno il campo facoltativo `tipo` (`locale` o `globale`); `misura.py` stampa il riepilogo e il saldo del confronto anche per tipo e marca le globali con `G`, `banco.py --verifica` rifiuta altri valori. Il banco d'esempio ha due domande globali; misura di partenza: globali 0/7 pagine attese. Il recall non cambia.
- Voce B1 del [piano 16](doc/16-tassonomia-ontologia-nel-grafo.md): tassonomia. «Tipi ammessi» accetta la colonna «Sottotipo di» (un sottotipo soddisfa i vincoli del padre nel builder, in `piano.py`, in `candidati.py` e nella preview; l'editor ha il campo) e la nuova sezione facoltativa `## Categorie` (`Categoria | Più ampia | Descrizione`) rende i tag un vocabolario controllato (`unknown_tag`, marcatori `entropia` e `sintesi` sempre ammessi). Nuove tabelle `categorie` ed `entity_tags`, `onto_tipi.padre`, `BUILDER_VERSION` 6; `GET /graph?category=` con le sottocategorie, `type_parents` e `categories` in `GET /ontology`, filtro «Categoria» e gerarchie nella dashboard. Recall, sintesi e domande invariati.
- Fase A del [piano 16](doc/16-tassonomia-ontologia-nel-grafo.md), dal confronto con «Taxonomy vs. ontology vs. knowledge graph» (Neo4j): il builder copia l'ontologia di `Wiki reference.md` nelle tabelle `onto_tipi`, `onto_relazioni`, `onto_vincoli` e `onto_metadata` di ogni grafo, così una query SQLite interroga lo schema insieme ai dati. `BUILDER_VERSION` passa a 5; le generazioni precedenti restano consultabili e `GET /ontology` dà la stessa risposta con e senza le tabelle. Fasi B–E (tassonomia, ruoli semantici, deduzione, export SKOS) solo proposte.
- `doc/presentazione/`: [guida completa](doc/presentazione/guida-teseo.md) (concetto, pattern LLM Wiki e rafforzamenti, motore, casistiche, collaborazione, controllo, ICM, lavorazioni, qualità, evoluzione, casi d'uso aziendali, percorso di adozione; 16 diagrammi Mermaid verificati) e due presentazioni con note per il relatore: teorica (19 slide, le idee, testi da 20 pt) e tecnica (50 slide, testi da 16 pt, schemi con etichette fuori dalle frecce); ogni testo è misurato con le metriche dei font perché stia nella sua casella.
- Revisione di sicurezza (ECC `security-review`) del codice del piano 14: `verifica` e `piano.py` usano espressioni regolari lineari con tetto di lunghezza al posto del `LINK` di `build_graph` e di `«([^»]+)»`, quadratiche (2,8 s con 20.000 «[», minuti con 200.000; il builder ha ancora la stessa esposizione sulle pagine, non toccata qui); `avvia` rifiuta una cartella `esecuzioni/` che sia un collegamento simbolico e gli altri comandi la ignorano; nessun `eval`, `exec`, `shell=True` né `innerHTML` nel codice nuovo.
- Voce B6 del [piano 14](doc/14-piano-icm.md): pannello «Lavorazioni» nella dashboard e rotta `GET /api/v1/vaults/{id}/lavorazioni`, di sola lettura (nessun parametro, nessun processo avviato, nessuna scrittura, tetti su lavorazioni, fasi e testi). `lavorazioni.py` si importa anche come pacchetto (`kit.graph`), come `build_graph`. Corretti due difetti trovati dai test di sicurezza: `elenco` seguiva una lavorazione che è un collegamento simbolico verso l'esterno e `stato` leggeva file fuori da `wiki/` o si rompeva con identificatori ostili o enormi nel registro dell'esecuzione. Provato nel browser a 1440×900 e 390×844 (28 controlli).
- Voce B5 del [piano 14](doc/14-piano-icm.md), **non come previsto**: il contratto dati non cambia. Lo snapshot percorre `DEFAULT_SHARED_PATHS` e rifiuta i tipi sconosciuti, e un `CONTEXT.md` condiviso è un'istruzione per il modello di tutti: la scelta di fiducia spetta al proprietario ([decisione](doc/15-condivisione-lavorazioni.md), con i punti da modificare e i criteri per riaprirla). Al suo posto `lavorazioni.py esporta NOME CARTELLA` e `nuova --modelli CARTELLA`, che avvisa che i contratti importati sono istruzioni da leggere prima di avviare.
- Voce A5 del [piano 14](doc/14-piano-icm.md): `kit/graph/correzioni.py` nei vault collaborativi riconosce le correzioni a mano (`Teseo-Skill: manuale`) a pagine che l'ultima volta aveva scritto `ingest` o `lint`, classifica i cambiamenti del frontmatter (relazioni, alias, tipo, fonti) e propone di rivedere `Wiki reference.md` o la skill quando una categoria ricorre almeno 3 volte su almeno 2 pagine; le correzioni isolate sono solo contate. Il lint lo esegue al passo 5b e riporta senza modificare. Il testo libero delle pagine non è classificato.
- Voce A4 del [piano 14](doc/14-piano-icm.md): lettura selettiva dello schema. `query` e `lacune` leggono solo le sezioni di `Wiki reference.md` indicate nel proprio Input (misurato con il nuovo `contratti.py --peso`: ~3.089 token invece di ~4.410, e ~839 per una `query` che non archivia); `ingest` e `lint` leggono tutto; le regole non negoziabili sono sempre caricate e in caso di dubbio si legge il file intero. Nuove funzioni `contratti.testo_sezione` e `contratti.peso`. Il gate previsto dal piano (10 domande con un client AI, nessuna regola violata rispetto alla lettura completa) non è stato eseguito.
- Voce A3 del [piano 14](doc/14-piano-icm.md): piano di ingest modificabile. La skill di ingest, per una fonte singola importante o su richiesta, scrive `lavorazioni/_ingest/<fonte>-piano.md`, lo controlla con il nuovo `kit/graph/piano.py` (fonte in `raw/`, pagine da creare/aggiornare, relazioni nel vocabolario con tipi ammessi, alias senza collisioni) e si ferma perché l'utente lo corregga; i passi 3–5 seguono il piano com'è sul disco. Il comportamento del modello con il piano non è provato con un client AI.
- Voce B4 del [piano 14](doc/14-piano-icm.md): `lavorazioni.py promuovi` copia l'output finale (`finale` in `config.md` o `--file`) in `raw/lavorazione-<nome>-<esecuzione>.md` con la provenienza, solo se supera `verifica` e la fase non è DA RIFARE; non sovrascrive mai `raw/` e ricorda di pubblicare il file prima dell'ingest nei vault collaborativi.
- Voce B3 del [piano 14](doc/14-piano-icm.md): `lavorazioni.py stato` segna DA RIFARE le fasi costruite su qualcosa che è poi cambiato (pagina raccolta modificata o rimossa, `config.md`, contratto, output a monte più recente) con i motivi; nuovo `verifica NOME --fase NN [--citazioni]` con controlli deterministici su link, fonti e segnaposto dell'output. I contratti dei modelli e la skill indicano il comando.
- Voce B2 del [piano 14](doc/14-piano-icm.md): modelli `report-periodico` e `scheda-argomento` in `kit/lavorazioni/` (copiati in `.graph/modelli/`), con contratti sotto le 80 righe, checkpoint sulle fasi creative e questionario con predefiniti; override dei parametri senza interpretazione YAML; `installa.py --prova` copre le lavorazioni; [guida](doc/lavorazioni.md).
- Voce B1 del [piano 14](doc/14-piano-icm.md): lavorazioni, pipeline ICM che leggono la wiki e producono documenti derivati senza scriverla. `kit/graph/lavorazioni.py` (`elenco`, `nuova`, `valida`, `avvia`, `stato`) con raccolta deterministica dal grafo (sottografo, tipi, data, domanda, massimo, override dei parametri) e impronta SHA-256 per pagina; quinta skill `obsidian-wiki-lavorazioni`; `lavorazioni/` esclusa da Git nei vault collaborativi (altrimenti un file non tracciato bloccherebbe `pre`) e dall'avviso delle pagine fuori da `wiki/`.
- Voce A2 del [piano 14](doc/14-piano-icm.md): le quattro skill (`kit/skills/*/SKILL.md`) hanno la forma contratto (Input, Processo, Checkpoint, Verifica, Output) e sono validate da `contratti.py` nei test; il testo esistente è invariato (sono state aggiunte sezioni e «Procedura» è diventata «Processo»). Il comportamento reale con un client AI non è stato provato.
- Integrazione ICM, voci A0 e A1 del [piano 14](doc/14-piano-icm.md) ([analisi](doc/analisi-icm-ecc.md)): `kit/graph/contratti.py` valida i contratti (sezioni Input / Processo / Checkpoint / Verifica / Output, file e sezioni citati, riferimenti in avanti, segnaposto, lunghezza; solo lettura, `--json`); `tests/test_istruzioni_coerenti.py` segnala quando le istruzioni duplicate per scelta divergono.
- Adozione esplicita dei vault legacy (`installa.py --adotta`, pannello dashboard) ed export diagnostico senza contenuti; crea, rinomina ed elimina pagine dalla dashboard (`/pages/preview|apply`, link riscritti, anteprima e journal); layout Barnes-Hut con costruzione a blocchi fino a 2000 nodi; `TESEO_SNAPSHOT_MAX_MIB`; test di uno scrittore esterno durante l'apply.
- Fase A di [doc/12](doc/12-piano-autenticazione-e-collaudo-avanzato.md): credential helper cercati in sistema, XDG e utente (anche chiavi per URL, formato di `gh auth setup-git`), nuovi errori `git_hostkey` e `git_not_found` con messaggi fissi e rimedio, `teseo_git.py diagnosi`, indicazione della modalità PR sui branch protetti.
- Apertura della pull request dalla dashboard con `gh` (`POST /sync/open-pr`); cache di 10 minuti dell'avviso di sessione; decisione proposta sull'apply automatico ([doc/13](doc/13-decisione-apply-automatico.md)).
- `script/collaudo_github.py`: collaudo con un repository GitHub reale e due cloni (9 scenari); credential helper di macOS, Linux e `gh` e variabili di proxy e certificati ora ammessi nei comandi Git ([rapporto](doc/evidence/step-11/collaudo-github.md)).
- Fasi 4–7 della roadmap collaborativa ([doc/10](doc/10-editor-grafo-e-autori.md)): autori delle note dalla storia Git
  (tabella `autori`, filtro per autore); relazione `causa` con `relazioni_dettaglio` (confidenza ed evidenza) e catena
  causale; editor del grafo nella dashboard (aggiungi/togli relazioni, alias, tag, tipo) con anteprima, apply journalizzato
  e pubblicazione `dashboard`; layout a forze con zoom, pan, colori per tipo e vicinato espandibile; avviso «N aggiornamenti
  remoti» a inizio sessione (`teseo_git.py avvisi`, hook SessionStart di Claude e Codex).
- Apply manuale e ricezione anche su Linux/macOS (rename nel backup + link esclusivo; rifiuto dei filesystem di rete).
- `copilot_timing_hook.py`: durata di ogni tool Copilot CLI in timeline (riga di progresso con i ms,
  senza toccare il contesto del modello) e log interrogabile in `.graph/timing.jsonl` con istante,
  tool, ms, esito e anteprima del risultato; mai bloccante. `installa.py` registra gli eventi
  `preToolUse`, `postToolUse` e `postToolUseFailure` in `.github/hooks/teseo.json`.

- Documentazione per contribuire: `LICENSE` (MIT), `CONTRIBUTING.md`, questo registro.
- `doc/architettura-motore.md`: riferimento tecnico del motore (componenti, schemi
  SQLite, pipeline di recall, contratti degli hook, modello dei turni).
- `doc/api.md`: riferimento API generato dai docstring con `script/genera_api_doc.py`;
  `tests/test_api_doc.py` ne verifica l'aggiornamento.
- Sintesi in inglese nel README per chi valuta il progetto.
- `doc/kpi-recall.md`: il recall sul banco come KPI della salute del vault.
- Ripiego sul testo a due giri (`recall.per_testo_a_cascata`): se il primo giro non trova
  pagine, un secondo giro con finestra e soglia più larghe porta al più 2 pagine. Sul
  vault di riferimento 88 → 102 pagine attese su 134, 0 domande peggiorate
  (`doc/analisi-retrieval-ecc.md`, `tests/test_recall_testo.py`).

## Storia (2026-10-19 → 2026-10-26)

### 2026-10-26 — Robustezza su Windows

- Corretto: nomi brevi per le cartelle snapshot e calcolo del budget dei percorsi
  Windows nella dashboard (`f00dd9d`).
- `.gitignore` esteso a cache, configurazioni locali e avanzi dei test (`35a9840`).

### 2026-10-25 — Ricezione automatica (passo 7)

- Aggiunto: rilevamento opt-in delle revisioni remote con ricevitore persistente,
  gate e sospensione dopo errori di autenticazione (`0027bd4`).
- Aggiunto: journal delle ricevute manuali con ripristino di file, indice e ref
  (`c4604d2`), e collegamento alla UI con revisione limitata del candidato (`1a6b4c5`).

### 2026-10-24 — Pubblicazione Git dei dati (passo 6)

- Aggiunto: checkpoint e integrazione in area isolata del repository dati (`835c970`).
- Aggiunto: validazione dei dati integrati e revisione causale delle note (`4872246`).
- Aggiunto: journal della pubblicazione, push con retry e recovery delle conferme
  (`2861532`), controlli di pubblicazione e guida al recovery nella UI (`34df910`).

### 2026-10-23 — Dashboard, ontologia e stato condiviso (passi 2–5)

- Aggiunto: journal del vault, lock e snapshot dei contenuti (`296eba9`);
  generazioni immutabili del grafo e backup SQLite consistenti (`c4df2c5`).
- Aggiunto: bootstrap su loopback e attach readonly del vault (`e5b8156`),
  API readonly coerenti per revisione (`d047e3b`) e workbench di consultazione (`65812f9`).
- Aggiunto: job di rebuild coordinati e distribuzione (`e23d24c`); preservazione dei
  byte dell'ontologia e validazione dei cataloghi dei tipi (`25e09e6`).
- Aggiunto: editor dell'ontologia con anteprima, valutazione d'impatto e migrazioni
  con recovery esplicito (`202c88f`, `a681c32`, `b48f0ef`).
- Aggiunto: coordinamento dei job ingest/lint con ricevute di fase e attribuzione
  delle scritture (`86a654c`, `e97faa4`, `7ad8ab7`, `9d8debd`).
- Aggiunto: eventi condivisi immutabili con validazione causale, migrazione selettiva
  delle risposte legacy e consolidamento per UUID con checkpoint (`10cf257`,
  `eab5d19`, `d1e8918`, `6fc0a9a`).

### 2026-10-22 — Fondamenta della collaborazione (passo 1)

- Aggiunto: contratti dati versionati e readonly (`01ba97e`).
- Corretto: il builder pubblica solo candidati SQLite validati (`2e16787`).

### 2026-10-20 — Tre client sullo stesso vault

- Aggiunto: configurazione locale per Claude Code, Codex e Copilot CLI con hook e
  skill nel vault (`5942886`).
- Documentazione: README ridisegnato con guida e diagrammi del flusso (`b0e6e6f`).

### 2026-10-19 — Prima versione del kit

- Aggiunto: vault wiki a grafo per Claude Code — ingest, query, lint, lacune,
  grafo SQLite con FTS5, recall e memoria delle domande (`5fea8ce`).
- `ADATTA.md` copiato nel vault come `.graph/ADATTA.md` (`b5fa572`).

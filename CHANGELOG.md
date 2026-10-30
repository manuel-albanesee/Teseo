# Registro delle modifiche

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).
Il progetto non ha ancora release con tag: la storia è ricostruita dai commit
e raggruppata per traguardo; le voci nuove si aggiungono sotto «Non rilasciato».

## [Non rilasciato]

### Aggiunto

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

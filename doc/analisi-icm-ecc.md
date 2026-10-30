# Analisi ECC: integrare l'Interpretable Context Methodology (ICM) in Teseo

Data: 2026-10-30. Fonti: repository [RinDig/Interpretable-Context-Methodology](https://github.com/RinDig/Interpretable-Context-Methodology)
(README, `CLAUDE.md`, `_core/CONVENTIONS.md`, workspace `workspace-builder`) e paper
[arXiv:2603.16021](https://arxiv.org/abs/2603.16021) (Van Clief, McDermott). Il testo integrale del paper non è stato
letto: arxiv.org e alphaxiv.org non sono raggiungibili dall'ambiente di analisi; le informazioni sul paper vengono
dall'abstract e da estratti indicizzati. Nessun codice runtime è stato modificato.

## Esito

**Integrabile in parte: come disciplina di scrittura delle istruzioni del vault (skill, file di livello 0, schema),
non come architettura di runtime.** Teseo rispetta già i principi di fondo di ICM (testo semplice come interfaccia,
Markdown come autorità, pipeline sequenziale ingest → lint → lacune con conferme umane, stato osservabile nei file e
in Git). La struttura a cartelle numerate `stages/NN-*/output/` e il routing statico del contesto non vanno adottati:
contrastano con contratti già implementati e il recall dal grafo fa meglio quel lavoro.

## Metodo

| Skill ECC | Uso |
|-----------|-----|
| `search-first` | adottare, estendere o costruire: confronto fra il workspace ICM così com'è e le sole convenzioni |
| `change-impact` | superficie d'impatto ricavata dal codice (builder, publisher, installatore, test), non dai nomi delle cartelle |
| `agent-architecture-audit` | livelli 1 (istruzioni di sistema) e 5 (recall attivo): duplicazioni, peso del contesto |
| `scientific-thinking-scholar-evaluation` | solidità delle prove del paper prima di usarlo per motivare modifiche |

Misure: token stimati come caratteri/4 sui file del kit; suite completa `python -m unittest discover -s tests`
(587 test, OK, 4 skip) come baseline prima di qualsiasi modifica.

## Corrispondenza fra i livelli

| Livello ICM | Ruolo | In Teseo | Token stimati |
|-------------|-------|----------|--------------:|
| 0 `CLAUDE.md` | dove sono | `CLAUDE.md`, `AGENTS.md`, `copilot-instructions.md` (uno per client) | 221 · 490 · 411 |
| 1 `CONTEXT.md` | dove vado | elenco delle skill nel livello 0 | – |
| 2 contratto di fase | che cosa faccio | `SKILL.md` di ingest, query, lint, lacune | 1.919 · 1.122 · 2.640 · 2.769 |
| 3 riferimenti | quali regole | `Wiki reference.md`, letto per intero | 4.450 |
| 4 artefatti | su che cosa lavoro | `raw/` (ingresso), `wiki/`, `index.md`, `log.md`; contesto del recall (~580–650 token medi) | variabile |

Un ingest parte da circa 6.600 token di istruzioni prima della fonte, dentro l'intervallo 2.000–8.000 che ICM indica
come obiettivo. Il margine di guadagno del caricamento selettivo è quindi limitato (sotto).

## Valutazione del paper (`scholar-evaluation`)

Rapporto tecnico/position paper sul pattern architetturale. Gli autori dichiarano fuori ambito il confronto fra modelli;
la maggiore coerenza delle fasi con contesto ristretto è un'osservazione informale, non un benchmark controllato; la
domanda se il caricamento selettivo conti meno con finestre più ampie resta aperta. Conseguenza: le idee di ICM sono
ipotesi da misurare sul banco di Teseo, non risultati da importare. Punteggio indicativo: metodologia 2/5, evidenza 2/5,
chiarezza e limiti dichiarati 4/5.

## Impatto sul codice (`change-impact`)

| Elemento ICM | Evidenza in Teseo | Esito |
|--------------|-------------------|-------|
| Cartelle `stages/NN/output/` nella wiki | `build_graph.py:180,197` accetta solo `wiki/*.md` piatto | **Escluso** |
| Artefatti intermedi pubblicati | `git_sync.py:484` (`_allowed`): solo manifest, Markdown, raw ed eventi dentro `shared_paths` | Escluso dalla pubblicazione; ammesso sotto `.teseo/local/` (escluso, `git_sync.py:601`) |
| `references/` per fase dentro le skill | `installa.py:284-287` copia solo `SKILL.md` di ciascuna skill | Richiederebbe di estendere installatore e test (`test_codex.py:129`, `test_copilot.py:231`) |
| «L'umano modifica l'output, la fase dopo lo riprende» | [13](13-decisione-apply-automatico.md): nessun apply automatico, scritture del servizio con `manual_paused` | Compatibile solo come checkpoint in chat, già usato dalle skill |
| Nomi `lowercase-with-hyphens` | Le pagine sono nomi di entità (`Anna Rossi.md`), id del grafo | **Escluso** per la wiki |
| Questionario `setup` e segnaposto `{{...}}` | `installa.py` e il segnaposto `<nome del vault>` in `Wiki reference.md` coprono già la configurazione | Non necessario |
| Routing statico del contesto (tabelle Input) | Il recall seleziona pagine per domanda, misurato in [analisi-retrieval-ecc](analisi-retrieval-ecc.md) | Escluso per le pagine; utile solo per lo schema |

## Rilievi sulle istruzioni (`agent-architecture-audit`)

1. **Fonti non canoniche (Pattern 5).** La regola «Vault collaborativo…» è ripetuta identica nei tre file di livello 0;
   il passo «Sincronizza» è ripetuto in ingest, lint e lacune; il blocco `**Client:**` è identico in ingest e lint,
   diverso in query e riformulato in lacune. Le copie servono (ogni client carica il proprio file, l'installatore
   distribuisce le skill una per una), ma nulla ne impedisce la deriva.
2. **Schema caricato per intero.** `Wiki reference.md` è il file più pesante del contesto. Le sezioni:
   Relazioni tipizzate ~2.080, Convenzioni delle pagine ~770, Manutenzione del vault ~770, Workflow ~380, Chiavi
   delle fonti ~170, Regole non negoziabili ~70. Una query che caricasse solo relazioni, convenzioni e regole
   risparmierebbe circa 1.300 token (~29% dello schema); l'ingest ne usa quasi tutto.
3. **Contratti impliciti.** Le skill mescolano routing e contenuto e non hanno la forma Input / Processo / Output;
   lacune supera le 123 righe. Checkpoint (domande all'utente) e audit (`build_graph.py --check`) esistono, ma sono
   sparsi nei passi invece che dichiarati.

## Proposte (una PR ciascuna, in ordine)

| # | Proposta | Rischio | Verifica |
|---|----------|---------|----------|
| 1 | **Contratti nelle skill**: sezioni `Input` (con le sezioni di `Wiki reference.md` da leggere), `Processo`, `Checkpoint`, `Audit`, `Output`, mantenendo frontmatter e passi | basso, solo testo | suite; banco con `misura.py --banco-confronta`; `skill-comply` ECC sulle skill riviste (richiede client autenticato) |
| 2 | **Guardia contro la deriva**: test che verifica identiche le copie volute (regola collaborativa, passo «Sincronizza» a meno del nome della skill) | basso | nuovo test nella suite |
| 3 | **Piano di ingest come superficie modificabile**: dopo la lettura della fonte la skill scrive `.teseo/local/ingest/<fonte>-piano.md` (pagine da creare/aggiornare, relazioni, alias, contraddizioni), chiede conferma, poi scrive la wiki | medio: cambia il flusso dell'ingest | prova sul vault d'esempio: errori di `build_graph.py --check` al primo giro e correzioni chieste dall'utente, con e senza piano |
| 4 | **Lettura selettiva dello schema** per query e lacune, solo se la proposta 1 non peggiora il banco | medio: rischio di regole saltate | gate di [analisi-retrieval-ecc](analisi-retrieval-ecc.md): 0 domande peggiorate, nessun errore sui casi `TESTO` |

Non proposti: cartelle di fase nel vault, rinomina delle pagine, sostituzione del recall con tabelle statiche,
adozione del `workspace-builder` o della skill comunitaria `icm-architect` (non letta).

## Limiti

- Paper valutato su abstract ed estratti, non sul testo integrale.
- Token stimati da caratteri/4, non dal tokenizer del modello.
- `skill-comply` e il banco con un client reale non sono stati eseguiti: le proposte 1, 3 e 4 restano ipotesi
  finché non passano quei gate.

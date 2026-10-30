# Analisi ECC: integrare l'Interpretable Context Methodology (ICM) in Teseo

Data: 2026-10-30. Fonti: repository [RinDig/Interpretable-Context-Methodology](https://github.com/RinDig/Interpretable-Context-Methodology)
(README, `CLAUDE.md`, `_core/CONVENTIONS.md`, workspace `workspace-builder`) e paper
[arXiv:2603.16021v2](https://arxiv.org/abs/2603.16021) (Van Clief, McDermott, 18 marzo 2026), letto per intero.
Nessun codice runtime è stato modificato.

## Esito

**Integrabile in parte: come disciplina di scrittura delle istruzioni del vault (skill, file di livello 0, schema)
e come ciclo di miglioramento delle fonti delle istruzioni, non come architettura di runtime.** Teseo rispetta già i
principi di fondo di ICM: testo semplice come interfaccia, Markdown come autorità, script locali per il lavoro
meccanico (`.graph/*.py`), pipeline sequenziale ingest → lint → lacune con conferme umane, stato osservabile nei file e
in Git. Le cartelle numerate `stages/NN-*/output/` e il routing statico del contesto non vanno adottati: contrastano
con contratti già implementati e il recall dal grafo fa meglio quel lavoro. Le direzioni future del paper (§6:
verifica fra fasi, tracciabilità, «correggere la fonte, non l'output») sono invece le parti più utili per Teseo, che
ha già i dati per realizzarle.

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

| Livello ICM | Obiettivo del paper | In Teseo | Token stimati |
|-------------|--------------------:|----------|--------------:|
| 0 `CLAUDE.md` | ~800 | `CLAUDE.md`, `AGENTS.md`, `copilot-instructions.md` (uno per client) | 221 · 490 · 411 |
| 1 `CONTEXT.md` | ~300 | elenco delle skill nel livello 0 | – |
| 2 contratto di fase | 200–500 | `SKILL.md` di ingest, query, lint, lacune | 1.919 · 1.122 · 2.640 · 2.769 |
| 3 riferimenti | 500–2.000 | `Wiki reference.md`, letto per intero | 4.450 |
| 4 artefatti | variabile | `raw/` (ingresso), `wiki/`, `index.md`, `log.md`; contesto del recall (~580–650 token medi) | variabile |

Il totale per fase resta nella fascia 2.000–8.000 indicata dal paper (un ingest parte da circa 6.600 token di
istruzioni prima della fonte), ma la ripartizione no: le skill superano di 2–5 volte il livello 2 e lo schema supera
di oltre il doppio il tetto del livello 3. Il paper confronta i ~5.000–5.600 token per fase con i ~42.000 di un prompt
monolitico; Teseo non è in quella situazione, quindi il guadagno atteso dal caricamento selettivo è limitato.

## Valutazione del paper (`scholar-evaluation`)

Rapporto tecnico sul pattern architetturale (CCS: HCI e software design), con fondamento ampio in letteratura
(Unix, pipe-and-filter, Make, compilatori multi-passo, mixed-initiative, «lost in the middle»).

| Dimensione | Voto | Motivo |
|------------|-----:|--------|
| Problema e contributo | 4 | ambito dichiarato: flussi sequenziali, ripetibili, con revisione umana |
| Letteratura | 4 | sintesi ampia; il legame qualità ↔ contesto ristretto è solo inferito da Liu et al. |
| Metodologia | 2 | nessuna raccolta dati formale; nessun confronto controllato ICM vs prompt monolitico |
| Evidenza | 2 | comunità su invito di 52 membri; 30 su 33 riportano la curva a U degli interventi (92% / 30% / 78%) per autodichiarazione in conversazione; una sola famiglia di modelli (Opus 4.6 e Sonnet 4.6) |
| Limiti dichiarati | 5 | §4.6 elenca selection ed enthusiasm bias, assenza di misure strumentate e di confronti fra modelli |

Conseguenza per Teseo: le idee di ICM sono ipotesi da misurare sul banco, non risultati da importare. Il paper
stesso lascia aperta la domanda se il caricamento selettivo conti meno con finestre di contesto ampie; restano validi
gli argomenti di interazione (osservabilità, modificabilità, punti di revisione), che Teseo già soddisfa.

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
| Strumenti limitati alla fase (§2.2) | Gli hook e gli script `.graph/` sono gli stessi per tutte le skill | Non necessario: pochi strumenti, già nominati per passo |

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

## Le direzioni future del paper (§6) e Teseo

| Proposta del paper | Stato in Teseo | Spazio di integrazione |
|--------------------|----------------|------------------------|
| Provenienza dell'output tramite identificatori (§6.2) | già presente e più fine: `fonti` per pagina, citazioni con timestamp `[mm:ss → mm:ss]`, chiavi censite e verificate da `build_graph.py --check`, `relazioni_dettaglio` con `evidenza` | nessuno: Teseo traccia fino alla fonte grezza, ICM no |
| Sezione `Verify` nel contratto: controllo della fase *n* contro le fasi precedenti (§6.2) | `--check` deterministico dopo ogni scrittura; il lint confronta pagine nuove e contraddizioni con il resto del vault | renderla esplicita nei contratti delle skill (proposta 1) |
| Compilazione incrementale: input dichiarati → output da rigenerare (§6.1) | il build del grafo è deterministico e completo; il lint propaga la fonte nuova | nessuno a breve: il build è già economico |
| Correggere la fonte, non l'output: correzioni ricorrenti → modifiche alle istruzioni (§6.3) | i commit portano i trailer `Teseo-Skill` e `Teseo-Agent` (`autosync.py:280`); le modifiche a mano si pubblicano con `--skill manuale --agente umano`; le risposte dell'autore entrano come `[nota-utente]` | **sì** (proposta 5): Teseo sa già distinguere le correzioni umane dalle scritture delle skill |

## Proposte (una PR ciascuna, in ordine)

Piano di implementazione: [14](14-piano-icm.md).

| # | Proposta | Rischio | Verifica |
|---|----------|---------|----------|
| 1 | **Contratti nelle skill**: sezioni `Input` (con le sezioni di `Wiki reference.md` da leggere), `Processo`, `Checkpoint`, `Verifica`, `Output`, mantenendo frontmatter e passi | basso, solo testo | suite; validatore dei contratti; prova end-to-end sul vault d'esempio; `skill-comply` ECC sulle skill riviste (richiede client autenticato). Il banco di `misura.py` misura il recall, che le skill non cambiano |
| 2 | **Guardia contro la deriva**: test che verifica identiche le copie volute (regola collaborativa, passo «Sincronizza» a meno del nome della skill) | basso | nuovo test nella suite |
| 3 | **Piano di ingest come superficie modificabile** (il «piano strutturale» del caso slide, §4.3): dopo la lettura della fonte la skill scrive `.teseo/local/ingest/<fonte>-piano.md` (pagine da creare/aggiornare, relazioni, alias, contraddizioni), chiede conferma, poi scrive la wiki | medio: cambia il flusso dell'ingest | prova sul vault d'esempio: errori di `build_graph.py --check` al primo giro e correzioni chieste dall'utente, con e senza piano |
| 4 | **Lettura selettiva dello schema** per query e lacune, solo se la proposta 1 non peggiora il banco | medio: rischio di regole saltate | insieme fisso di domande sul vault d'esempio: stesse pagine citate e nessuna regola violata rispetto alla lettura completa |
| 5 | **Correzioni manuali come segnale**: script in sola lettura che, nei vault collaborativi, raccoglie i commit `Teseo-Skill: manuale` su pagine scritte prima da una skill e i fatti `[nota-utente]` che correggono una fonte, li raggruppa per tipo (relazione, alias, frontmatter, testo) e propone al lint modifiche a `Wiki reference.md` o alle skill quando lo stesso tipo ricorre | medio: euristica di classificazione; la modifica resta una proposta da confermare | fixture Git con correzioni ripetute e isolate: segnala le prime, ignora le seconde; nessuna scrittura senza conferma |

Non proposti: cartelle di fase nel vault, rinomina delle pagine, sostituzione del recall con tabelle statiche,
adozione del `workspace-builder` o della skill comunitaria `icm-architect` (non letta), breakpoint nei file Markdown
(§6.2, dichiarati speculativi dagli autori).

## Limiti

- Token stimati da caratteri/4, non dal tokenizer del modello.
- `skill-comply` e il banco con un client reale non sono stati eseguiti: le proposte 1, 3, 4 e 5 restano ipotesi
  finché non passano quei gate.
- Le cifre del paper su comunità e interventi sono autodichiarate e non verificabili da qui.

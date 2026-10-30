# 14 — Piano: convenzioni ICM nelle istruzioni e pipeline di lavorazione della wiki

Stato: **proposta del 30 ottobre 2026, nulla implementato.** Parte dall'[analisi ECC dell'ICM](analisi-icm-ecc.md).
Due linee di lavoro: **A**, le istruzioni del vault (skill, file di livello 0, schema) riscritte con le convenzioni ICM;
**B**, un motore di *lavorazioni*: pipeline ICM configurabili che leggono la wiki e producono documenti derivati
(report, schede, slide), senza toccare `wiki/`. Ogni voce è consegnabile da sola su un branch `codex/<scopo>`, senza
nuove dipendenze (PyYAML c'è già), con stile compatto e commenti in italiano.

## Riepilogo

| # | Voce | Dipende da | Complessità |
| --- | --- | --- | --- |
| A0 | Formato canonico dei contratti e validatore `contratti.py` | – | S |
| A1 | Guardia contro la deriva delle istruzioni duplicate | – | S |
| A2 | Contratti nelle quattro skill | A0, A1 | M |
| A3 | Piano di ingest modificabile | A2, B1 | M |
| A4 | Lettura selettiva di `Wiki reference.md` | A2 | M |
| A5 | Correzioni manuali come segnale per schema e skill | A2 | L |
| B1 | Motore delle lavorazioni: struttura, `lavorazioni.py`, skill | A0 | L |
| B2 | Due modelli: `report-periodico`, `scheda-argomento` | B1 | M |
| B3 | Stato, obsolescenza e verifica fra fasi | B1 | M |
| B4 | Promozione dell'output a nuova fonte in `raw/` | B1 | S |
| B5 | Condivisione delle definizioni nel repository dati | B1 | L |
| B6 | Pannello delle lavorazioni nella dashboard (sola lettura) | B3 | M |

Ordine consigliato: A0 → A1 → A2, poi B1 → B2 → B3 → B4 (prima consegna utile), poi A3, A4, A5; B5 e B6 solo se
le lavorazioni vengono usate davvero.

## Formato canonico dei contratti (comune ad A e B)

Una sola forma per le skill e per le fasi delle lavorazioni (ICM: *stage contract*), definita una volta in
`kit/graph/contratti.py` e documentata qui:

```markdown
## Input
| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `Wiki reference.md` | «Relazioni tipizzate» | vocabolario ammesso |
| 4 | `{esecuzione}/01-raccolta/raccolta.md` | tutto | pagine selezionate |

## Processo
1. …

## Checkpoint          (facoltativo: obbligatorio nelle fasi creative)
| Dopo il passo | L'agente presenta | L'utente decide |

## Verifica
| Controllo | Comando o criterio | Esito atteso |

## Output
| Artefatto | Posizione | Formato |
```

Livello 3 = regole stabili, livello 4 = materiale di questa esecuzione, come nel paper. `Verifica` sostituisce
l'«Audit» di ICM e accoglie la proposta `Verify` del §6.2: confronto con le fasi precedenti.

---

## A0 — Validatore dei contratti

- **Cosa**: `contratti.py` legge un file Markdown e controlla: sezioni obbligatorie presenti e in ordine; ogni riga
  di `Input` punta a un file esistente (risolto rispetto al file o alla radice del vault) e, se indica una sezione,
  a un titolo che esiste davvero; nessun segnaposto `{{...}}` irrisolto; nelle lavorazioni nessun riferimento a una
  fase successiva (riferimenti a senso unico, ICM pattern 3). Lunghezze oltre 80 righe (contratto) o 200
  (riferimento): avviso, non errore. Uscita testuale e `--json`, codici 0/1 come `build_graph.py --check`.
- **File**: CREATE `kit/graph/contratti.py`, `tests/test_contratti.py`; UPDATE `doc/api.md` con
  `script/genera_api_doc.py` (verificato da `tests/test_api_doc.py`). L'installatore copia già ogni `kit/graph/*.py`
  (`installa.py:516`).
- **Rischi**: bassi; solo lettura.
- **Verifica**: fixture con sezione mancante, file inesistente, titolo inesistente, segnaposto, riferimento
  all'indietro: ciascuna produce l'errore atteso; un contratto valido passa.

## A1 — Guardia contro la deriva

- **Cosa**: test che fissa le copie volute: la riga «Vault collaborativo…» identica in `CLAUDE.md`, `AGENTS.md`,
  `copilot-instructions.md`; il passo «Sincronizza» identico in ingest, lint e lacune a meno di `--skill <nome>`;
  l'elenco delle skill identico nei tre file di livello 0. Chi cambia una copia deve cambiarle tutte.
- **File**: CREATE `tests/test_istruzioni_coerenti.py`.
- **Verifica**: il test passa sul kit attuale; fallisce se si modifica una sola copia.

## A2 — Contratti nelle quattro skill

- **Cosa**: ogni `SKILL.md` prende la forma canonica. Frontmatter (`name`, `description`) invariato; i passi
  numerati restano in `Processo`; checkpoint già presenti (domande all'utente, scelta lint/lacune) diventano tabella;
  `build_graph.py --check` e i codici di uscita di `teseo_git.py` diventano `Verifica`. `Input` elenca le sezioni di
  `Wiki reference.md` effettivamente usate dalla skill. Il blocco client, ripetuto, resta (lo protegge A1).
- **File**: UPDATE `kit/skills/*/SKILL.md`; `tests/test_contratti.py` valida le quattro skill.
- **Rischi**: medi: una riformulazione può cambiare il comportamento del modello. Mitigazione: nessuna regola
  aggiunta o tolta, solo spostata; diff rivisto riga per riga.
- **Verifica**: `contratti.py` pulito sulle skill; suite completa; prova end-to-end sul vault d'esempio con un client
  (ingest di `raw/manuale-rilascio.md`, poi lint): stessi errori di `--check` al primo giro e stesse pagine toccate
  rispetto al kit attuale. `skill-comply` ECC sulle skill riviste quando un client autenticato è disponibile. Il banco
  di `misura.py` non serve qui: misura il recall, che le skill non cambiano.
- **Complessità**: M.

## A3 — Piano di ingest modificabile

- **Cosa**: per fonti singole importanti (o su richiesta) l'ingest si divide in due fasi. Fase 1: lettura della
  fonte e scrittura di `lavorazioni/_ingest/<fonte>-piano.md` (pagine da creare e aggiornare, relazioni, alias,
  contraddizioni con pagine esistenti, citazioni previste). Checkpoint: l'utente modifica il piano, anche in Obsidian.
  Fase 2: scrittura della wiki seguendo il piano così com'è sul disco. Per i batch il piano si salta.
- **File**: UPDATE `kit/skills/obsidian-wiki-ingest/SKILL.md`; usa la cartella e le regole Git di B1.
- **Rischi**: medi: un passo in più. Si attiva solo con un checkpoint esplicito.
- **Verifica**: prova sul vault d'esempio con e senza piano: errori di `--check` al primo giro e correzioni chieste
  dall'utente dopo l'ingest; un piano modificato a mano (pagina tolta) viene rispettato.

## A4 — Lettura selettiva dello schema

- **Cosa**: query e lacune leggono solo le sezioni di `Wiki reference.md` indicate nel proprio `Input` (stima:
  circa 1.300 token in meno su 4.450 per la query). Ingest e lint continuano a leggerlo tutto.
  `controlla_vault` (`installa.py:333`) avvisa già se manca «## Relazioni tipizzate»; A0 avvisa se una sezione citata
  non esiste più.
- **File**: UPDATE `kit/skills/obsidian-wiki-query/SKILL.md`, `kit/skills/obsidian-wiki-fill-gaps/SKILL.md`; UPDATE
  `kit/vault/CLAUDE.md`, `AGENTS.md`, `copilot-instructions.md` («leggi per primo» diventa «leggi le sezioni indicate
  dalla skill»).
- **Rischi**: medi: regole saltate perché fuori dalle sezioni scelte. Mitigazione: «Regole non negoziabili» sempre in
  `Input`.
- **Verifica**: insieme fisso di 10 domande sul vault d'esempio: stesse pagine citate e nessuna violazione delle
  regole rispetto alla lettura completa. Se peggiora anche una domanda, la voce non si consegna.

## A5 — Correzioni manuali come segnale

- **Cosa**: `correzioni.py`, sola lettura, nei vault collaborativi. Scorre i commit con trailer
  `Teseo-Skill: manuale` (`autosync.py:280`) sulle pagine `wiki/*.md` la cui versione precedente era stata scritta da
  ingest o lint; classifica ogni modifica (relazione aggiunta o tolta, alias, `tipo`, `fonti`, testo); raggruppa per
  categoria e chiave. Una categoria che ricorre almeno 3 volte su almeno 2 pagine diventa una proposta
  («le relazioni `usa` vengono tolte a mano 4 volte: rivedere la definizione in Wiki reference»). Il lint la mostra
  in un checkpoint; la modifica a `Wiki reference.md` o alla skill resta dell'utente. È il ciclo «correggere la fonte,
  non l'output» del §6.3 del paper.
- **File**: CREATE `kit/graph/correzioni.py`, `tests/test_correzioni.py` (repository Git di fixture con trailer);
  UPDATE `kit/skills/obsidian-wiki-lint/SKILL.md` (passo e checkpoint). Riusa il parsing dei trailer di
  `kit/dashboard/authors.py`, importato come fa `teseo_git.py`.
- **Rischi**: euristica di classificazione rumorosa sul testo libero. Mitigazione: prima versione solo sul
  frontmatter, che è strutturato; il testo dopo, se serve.
- **Verifica**: fixture con correzioni ripetute (segnalate) e isolate (ignorate); vault senza Git o senza autosync:
  messaggio chiaro, uscita 0; nessuna scrittura.
- **Complessità**: L.

---

## B — Lavorazioni: pipeline ICM sulla wiki

Una *lavorazione* è una pipeline ICM ripetibile che prende pagine della wiki e produce un documento derivato. La
wiki resta la conoscenza; le lavorazioni sono il lavoro che se ne ricava. Il flusso va in un solo verso: le
lavorazioni leggono `wiki/` e non la scrivono mai; un output rientra nella wiki solo come nuova fonte in `raw/`
seguita da un ingest (B4).

### Struttura nel vault

```text
lavorazioni/
  report-periodico/
    CONTEXT.md                 livello 1: scopo, fasi, come si avvia
    config.md                  livello 3: configurazione («la fabbrica»): frontmatter YAML + sezioni in prosa
    setup/questionario.md      domande per compilare config.md (trigger «imposta»)
    riferimenti/               livello 3 comune alle fasi
    fasi/
      01-raccolta/CONTEXT.md   fase deterministica, eseguita dallo script
      02-sintesi/CONTEXT.md    contratto (forma canonica) + riferimenti/ propri
      03-revisione/CONTEXT.md
    esecuzioni/                livello 4, escluso da Git
      2026-10-30-1/
        esecuzione.json        parametri, impronte di config/contratti/pagine, HEAD Git
        01-raccolta/raccolta.md
        02-sintesi/sintesi.md
        03-revisione/report.md
```

Differenza voluta da ICM: invece di un solo `output/` per fase, una cartella per esecuzione. Le esecuzioni restano
confrontabili e ogni output è riconducibile alle pagine e alle istruzioni da cui nasce. La cartella è visibile, non
nascosta: Obsidian la mostra e gli output con `[[link]]` sono navigabili e modificabili lì.

### Configurabilità, su tre livelli

1. **Fabbrica** (una volta): `config.md`. Il frontmatter dice che cosa selezionare e con quali parametri; le sezioni
   in prosa (tono, formato, destinatari) sono il livello 3 delle fasi. Compilata con il questionario, come
   nell'`setup` di ICM; `valida` rifiuta segnaposto irrisolti.

   ```yaml
   selezione:
     collegate_a: "[[Rilascio in produzione]]"   # sottografo da una pagina
     profondita: 1
     tipi: [processo, sistema]
     relazioni: [usa, richiede, referente]
     modificate_da: 7g                           # da log.md o dalla storia Git
     domanda: null                               # in alternativa: selezione con il recall
     massimo: 40
   parametri:
     destinatari: team operativo
   ```
2. **Esecuzione**: `avvia <nome> --param periodo=14g` sovrascrive un parametro solo per quella esecuzione e lo
   registra in `esecuzione.json`.
3. **Struttura**: aggiungere, togliere o riordinare fasi = cartelle; `valida` ricontrolla la catena. Una lavorazione
   nuova si crea copiando un modello (`nuova <nome> --da <modello>`) o una lavorazione esistente, come fanno i
   praticanti descritti nel paper (§4.5).

### Perché la raccolta è uno script e non il modello

La fase 01 la esegue `lavorazioni.py`, non l'agente. Seleziona le pagine dal grafo (`graph.sqlite` in sola
lettura) e scrive `raccolta.md`: per ogni pagina, contenuto, fatti del grafo e impronta SHA-256. Tre motivi:

- **Memoria pulita**: `learn_hook.py` collega alla domanda in corso ogni lettura di `wiki/`; un agente che legge 40
  pagine per «esegui la fase 2» insegnerebbe alla memoria associazioni false. Le fasi successive leggono solo
  `raccolta.md`, che non è in `wiki/`.
- **Provenienza**: le impronte fissano la revisione delle pagine usate (§6.2 del paper).
- **Obsolescenza**: se una pagina cambia dopo la raccolta, `stato` lo vede (B3, compilazione incrementale §6.1).

Il recall automatico arriva comunque a ogni prompt: la skill dice di ignorare il blocco `<teseo-context>` durante
le fasi, salvo che il contratto lo chieda in `Input`.

## B1 — Motore delle lavorazioni

- **Cosa**:
  - `lavorazioni.py` con i comandi `elenco`, `nuova`, `valida` (via `contratti.py`), `avvia` (crea l'esecuzione e
    svolge la raccolta) e `stato`. `stato` disegna la pipeline in ASCII come il trigger `status` di ICM.
  - Una quinta skill, `obsidian-wiki-lavorazioni`, con i trigger «esegui la lavorazione X», «stato», «imposta». Per
    ogni fase in attesa la skill:
    1. legge il `CONTEXT.md` della fase;
    2. carica solo le righe di `Input`;
    3. scrive l'output;
    4. esegue la `Verifica`;
    5. si ferma ai checkpoint.

    Non scrive mai in `wiki/` né in `raw/`.
- **File**:
  - CREATE `kit/graph/lavorazioni.py`, `kit/skills/obsidian-wiki-lavorazioni/SKILL.md`, `tests/test_lavorazioni.py`.
  - UPDATE `installa.py`:
    - copia dei modelli da `kit/lavorazioni/` in `.graph/modelli/`;
    - `lavorazioni` escluso dall'avviso di `controlla_vault` (`installa.py:335`);
    - `lavorazioni/*/esecuzioni/` e `lavorazioni/_ingest/` nelle esclusioni Git (`LOCALI`, `installa.py:357`).
  - UPDATE i tre file di livello 0 e il README (cinque skill, non quattro).
  - UPDATE i test che contano le skill (`test_codex.py:64,129,215`, `test_copilot.py:231`) e `doc/api.md`.
- **Vincolo Git**: `GitRepository.clean()` conta anche i file non tracciati (`git_sync.py:464`), e un file non
  tracciato blocca `pre` con `autosync_unpublished`. In B1 l'intera cartella `lavorazioni/` è quindi esclusa da Git
  nei vault collaborativi: le lavorazioni sono personali finché B5 non le rende condivisibili.
- **Rischi**: medi.
  - La skill in più allunga le descrizioni caricate dai client, ma resta un solo `SKILL.md`, compatibile con
    l'installatore attuale.
  - La selezione per `modificate_da` dipende da `log.md` o da Git: senza nessuno dei due, il criterio viene rifiutato
    con un messaggio chiaro.
- **Verifica**:
  - Unit test:
    - `valida` trova input rotti, riferimenti all'indietro e segnaposto;
    - la raccolta è deterministica (stessa selezione e stesse impronte a parità di vault);
    - `avvia` non legge né scrive fuori da `lavorazioni/`;
    - in un vault collaborativo di fixture, `pre` non è bloccato da esecuzioni presenti.
  - `installa.py --prova` esteso con `valida`, `avvia` e `stato` su un modello (senza modello AI).
- **Complessità**: L.

## B2 — Modelli inclusi

- **`report-periodico`**:
  - 01 raccolta: pagine modificate nel periodo, più le vicine;
  - 02 sintesi: bozza con citazioni `[[Pagina]]`;
  - 03 revisione: verifica che ogni affermazione sia citata e che i punti aperti siano segnalati.
- **`scheda-argomento`**:
  - 01 raccolta: sottografo di una pagina;
  - 02 scaletta, con checkpoint: è il punto in cui correggere costa meno (§4.3 del paper);
  - 03 stesura;
  - 04 verifica fra fasi: la stesura contro la scaletta e la raccolta.
- **File**: CREATE `kit/lavorazioni/report-periodico/…`, `kit/lavorazioni/scheda-argomento/…`, con contratti sotto le
  80 righe e riferimenti sotto le 200.
- **Verifica**: `valida` pulito su entrambi i modelli; un'esecuzione completa sul vault d'esempio con un client,
  con output, verifiche e checkpoint registrati in `doc/evidence/`.

## B3 — Stato, obsolescenza e verifica fra fasi

- **Cosa**:
  - `stato` segna una fase **da rifare** se, dopo il suo output, sono cambiati una pagina della raccolta, `config.md`,
    il suo contratto o l'output di una fase precedente. Il confronto avviene con le impronte di `esecuzione.json`.
  - `verifica <nome> --fase NN` esegue i controlli deterministici dichiarati nella sezione `Verifica`:
    - ogni `[[link]]` dell'output è nella raccolta o esiste in `wiki/`;
    - le chiavi di fonte citate sono censite;
    - nessun segnaposto;
    - opzionalmente, ogni paragrafo ha almeno una citazione.
  - I controlli semantici (coerenza con le fasi precedenti) restano all'agente, guidati dalla tabella.
- **Verifica**:
  - una pagina modificata dopo la raccolta rende da rifare le fasi 01 e successive;
  - un contratto modificato rende da rifare solo quella fase e le successive;
  - un link inventato nell'output fa fallire `verifica`.
- **Complessità**: M.

## B4 — Promozione a fonte

- **Cosa**: `promuovi <nome> [--esecuzione ID]` copia l'output finale in `raw/lavorazione-<nome>-<data>.md` con
  un'intestazione di provenienza (esecuzione, pagine e impronte). Crea solo file nuovi: rifiuta un percorso esistente
  (`raw/` è immutabile, nuove fonti ammesse). Poi propone l'ingest. Così un report rientra nella wiki con citazioni
  verificabili, senza scritture dirette in `wiki/`.
- **Verifica**: il secondo `promuovi` sullo stesso nome e data fallisce senza toccare nulla; il file è censibile in
  «Chiavi delle fonti».

## B5 — Definizioni condivise (facoltativo)

- **Cosa**: rendere pubblicabili nel repository dati le definizioni (`CONTEXT.md`, `config.md`, `riferimenti/`),
  non le esecuzioni. Servono:
  - un nuovo `PathKind` in `classify_path` (`contracts.py:261`), oggi `UNKNOWN` per tutto ciò che è fuori da
    `wiki/` e `raw/`;
  - l'estensione dell'allowlist di `shared_paths` nel manifest;
  - il controllo che i dati ricevuti restino testo e non diventino istruzioni eseguibili.

  È il gate 6 del [README](README.md): i dati ricevuti non attivano script o hook. Un `CONTEXT.md` ricevuto è un
  prompt: va trattato come dato, con revisione prima del primo uso.
- **Rischi**: alti: cambia il contratto dati del passo [1](01-contratto-dati-operazioni.md) e introduce istruzioni
  condivise. Richiede di aggiornare prima il contratto e i test di pubblicazione.
- **Complessità**: L.

## B6 — Pannello nella dashboard (facoltativo)

Pannello in sola lettura: lavorazioni, ultima esecuzione, fasi completate, in attesa o da rifare (da `stato --json`),
link agli output. L'avvio delle fasi resta nella chat del client, come per ingest e lint (passo
[4](04-coordinamento-ingest-lint.md)): nessun nuovo tipo di operazione finché i client non sono verificati.

## Fuori piano

- Cartelle di fase dentro `wiki/` e rinomina delle pagine: incompatibili con il grafo (`build_graph.py:180,197`).
- Scrittura diretta delle lavorazioni in `wiki/`: tutto passa da `raw/` e ingest.
- Diramazioni automatiche fra fasi: il paper stesso le esclude (§5.2); decide l'utente fra una fase e l'altra.
- Breakpoint nei file Markdown (§6.2): speculativi.

## Rollout e rollback

Le voci A sono testo e test: il rollback è un revert. B1–B4 aggiungono file e cartelle nuove senza cambiare dati
esistenti: disinstallare la skill e cancellare `lavorazioni/` riporta allo stato attuale. B5 cambia il contratto dati
e segue le regole di [README](README.md) per le migrazioni: versione del manifest, compatibilità, nessuna
retrocessione forzata.

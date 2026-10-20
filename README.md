# Teseo

Un vault Obsidian scritto e tenuto in ordine da Claude Code, Codex o Copilot CLI a partire dai tuoi documenti, con una mappa dei
collegamenti tra le pagine. La mappa è il filo: a ogni domanda indica all'assistente quali pagine servono e come sono
collegate, anche quando la risposta passa da quattro pagine e la domanda ne nomina una sola.

Il metodo parte dall'idea «LLM Wiki» di Andrej Karpathy: fonti originali in `raw/`, pagine distillate in `wiki/`,
regole in `Wiki reference.md`. Teseo aggiunge il grafo (`.graph/`), gli hook che lo mettono nel contesto a ogni
domanda, la memoria delle domande, le domande aperte per l'autore, le pagine di sintesi scritte dal lint e una
misura che dice se ogni modifica migliora o peggiora il recupero.

## Requisiti

- Claude Code, Codex (app o CLI con hook nativi) oppure GitHub Copilot CLI con `userPromptTransformed`
- Python 3.9 o successivo, con `pip install pyyaml` (SQLite e FTS5 sono già nella libreria standard)
- Obsidian, facoltativo: le pagine sono file Markdown

## Provare senza toccare nulla

```bash
git clone https://github.com/manuel-albanesee/Teseo.git
cd Teseo
python installa.py --prova
```

Installa il kit in una cartella temporanea con un piccolo vault d'esempio, lancia i controlli e cancella tutto.
Deve finire con `tutto OK`.

## Installare in un vault nuovo

```bash
python installa.py "C:/percorso/MioVault"
```

Crea la struttura (`raw/`, `wiki/`, `index.md`, `log.md`, `Wiki reference.md`), copia gli script in `.graph/`
e configura **tutti e tre i client dentro il vault**, senza opzioni aggiuntive:

- Claude Code: `CLAUDE.md`, `.claude/settings.json` e le quattro skill in `.claude/skills/`.
- Codex: `AGENTS.md`, `.codex/hooks.json`, `.graph/codex.json` e le quattro skill in `.agents/skills/`.
- Copilot CLI: `.github/copilot-instructions.md`, `.github/hooks/teseo.json` e le quattro skill in `.github/skills/`.

Poi apri il client nella cartella del vault, metti un documento in `raw/` e scrivi
«ingerisci raw/nome-file». Puoi preparare i file anche dei client non installati.

Con `--esempio` aggiunge anche il vault d'esempio, da togliere dopo averlo guardato.

Per configurare soltanto un client:

```powershell
python installa.py "C:/percorso/MioVault" --client codex
python installa.py "C:/percorso/MioVault" --client claude
python installa.py "C:/percorso/MioVault" --client copilot
```

Codex riceve `AGENTS.md`, le quattro skill in `.agents/skills/`, gli hook nativi in `.codex/hooks.json`
e la configurazione dei modelli in `.graph/codex.json`. Claude conserva `.claude/settings.json` e le proprie skill.
L'opzione esplicita `--skill utente` installa invece le skill in `~/.claude/skills/`, `~/.agents/skills/` o `~/.copilot/skills/`,
secondo i client selezionati. Il comando senza opzioni installa tutto nel vault.

## Installare in un vault già in uso

```bash
python installa.py "C:/percorso/VaultEsistente"
```

Non tocca le pagine né le fonti. Aggiunge gli script, unisce i suoi hook a quelli già presenti (con una copia di
sicurezza di `settings.json`) e crea i file di regole solo se mancano. Alla fine dice cosa manca perché il grafo veda
le pagine: di solito spostarle in `wiki/` senza sottocartelle e sistemare le proprietà del frontmatter.
I passi sono in [ADATTA.md](ADATTA.md), che l'installatore copia anche nel vault come `.graph/ADATTA.md`: aperto
Claude Code nella cartella del vault, basta chiedere «Adatta questo vault al kit Teseo seguendo .graph/ADATTA.md, un
passo alla volta, chiedendomi conferma prima di spostare o rinominare file».

## Aggiornare

```bash
cd Teseo
git pull
python installa.py "C:/percorso/MioVault" --aggiorna
```

Senza `--aggiorna` uno script già presente e diverso dal kit non si tocca. Con `--aggiorna` il vecchio va in
`.graph_backup/<data-ora>/` e i dati di dominio (le domande di prova di `misura.py`, `PAROLE_COMUNI`…) vanno
riportati da lì. I database (`graph.sqlite`, `memoria.sqlite`, `domande.sqlite`) non si toccano mai.

## Opzioni

| Opzione | Effetto |
| --- | --- |
| `--client claude` | configura soltanto Claude Code |
| `--client codex` | configura Codex senza richiedere Claude Code |
| `--client copilot` | configura soltanto GitHub Copilot CLI |
| `--client tutti` | configura Claude, Codex e Copilot CLI nello stesso vault (predefinito) |
| `--client entrambi` | selezione compatibile con le versioni precedenti: Claude e Codex |
| `--skill utente` | installazione globale esplicita, nella cartella del client selezionato |
| `--skill vault` | skill locali in `.claude/skills/`, `.agents/skills/`, `.github/skills/` secondo i client (predefinito) |
| `--skill no` | skill non installate |
| `--solo-integrazione` | aggiunge il supporto client a Teseo già installato, senza aggiornare script di dominio, pagine o database |
| `--aggiorna` | sostituisce script e skill diversi dal kit, con copia di sicurezza |
| `--esempio` | aggiunge il vault d'esempio (solo con `wiki/` vuota) |
| `--prova` | prova completa in una cartella temporanea |

## Aggiungere Codex a un vault Teseo esistente

```powershell
python installa.py "C:/Obsidian_Wiki/ISP" --client codex --skill vault --solo-integrazione
```

Questa modalità aggiunge soltanto gli adattatori Codex, gli hook, la configurazione, le skill e `AGENTS.md` se
manca. Gli script personalizzati del grafo e i database non vengono aggiornati. Senza `--aggiorna` anche le
skill e gli adattatori già presenti ma diversi vengono lasciati; con `--aggiorna` sono salvati prima nel backup.
I modelli personalizzati in `.graph/codex.json` sono sempre conservati. `AGENTS.md` esistente non è sovrascritto:
in quel caso integra manualmente le indicazioni di `kit/vault/AGENTS.md`.

### Hook Codex e attivazione

Teseo usa gli eventi nativi `SessionStart`, `UserPromptSubmit`, `PostToolUse` e `Stop`:
avvio con le regole del vault, recall prima della risposta, registrazione delle letture, consolidamento della
memoria a fine turno. Il recall richiama lo stesso motore Python di Claude, senza avviare Claude o un altro modello.
Gli errori producono un avviso e indicazioni per cercare nelle pagine; non bloccano la conversazione.

Codex richiede che il progetto e le definizioni degli hook siano revisionati e autorizzati. Riapri il progetto,
usa `/hooks` nella CLI (o il controllo hook del client, se presente) e controlla i quattro comandi verso
`.graph/codex_hook.py`. L'installatore non modifica il trust e non usa opzioni che lo saltano. Dopo una modifica
agli hook Codex può chiedere una nuova revisione. Se una versione del client non supporta gli hook, le skill
restano utilizzabili con recall esplicito.
Riferimento: [hook Codex, eventi e trust](https://learn.chatgpt.com/docs/hooks).

Per le letture con percorso strutturato (`Read` o un tool `read_file`/`read_text_file`), `PostToolUse` registra
solo gli esiti riusciti. Non deduce letture da `rg`, `glob` o comandi di shell generici. In Codex usa invece:

```powershell
python .graph/leggi.py --turno TOKEN_FORNITO_DALL_HOOK "wiki/Nome pagina.md"
```

Il lettore stampa la pagina e registra la lettura. Il token separa sessione e turno; gli eventi che dichiarano
un `agent_id` vengono ignorati. Senza `--turno` il comando legge soltanto. Gli handle durano sette giorni e
non contengono il testo delle domande; la memoria conserva il proprio ciclo di archiviazione.

### Modelli Codex

| Ruolo | Codex predefinito | Ruolo corrispondente in Claude |
| --- | --- | --- |
| Ricerca e lavoro sul vault | `gpt-6.1-sol` | Opus |
| Analisi profonda, scelta esplicita | `gpt-6-astra` | Opus |
| Domande puntuali con contesto affidabile | `gpt-6-luna` | Haiku |

Sono ruoli operativi, non una promessa di prestazioni equivalenti. Gli identificativi si possono cambiare in
`.graph/codex.json` secondo i modelli disponibili all'account. Gli hook suggeriscono un ruolo, ma la chat continua
con il modello scelto dall'utente: il protocollo hook non offre un cambio del modello attivo.

Per una query autonoma il comando seguente sceglie davvero il modello prima di avviare `codex exec`:

```powershell
python .graph/chiedi_codex.py "chi è il referente di RTC?"
python .graph/chiedi_codex.py "@astra confronta i processi di rilascio"
python .graph/chiedi_codex.py --ricerca astra "spiega il processo di rilascio"
python .graph/chiedi_codex.py --piano "chi è il referente di RTC?"
```

Serve Codex CLI nel PATH, autenticata e con accesso ai modelli configurati. Le domande puntuali vanno a Luna;
quelle ampie, senza agganci affidabili o sul sistema vanno a Sol (oppure Astra con `--ricerca astra`).
`@sol` e `@astra` forzano il ruolo di ricerca. Se Luna fallisce o richiede più ricerca, si prova una volta il
modello di ricerca. Un errore di quest'ultimo termina il comando: nessun ciclo di tentativi illimitato.
Il figlio usa il sandbox `read-only`, nessuna richiesta di approvazione, sessione effimera e hook disabilitati
per evitare ricorsione. Non raccoglie letture dal transcript né inventa associazioni dalle citazioni della risposta.
`--piano` mostra la scelta senza chiamare modelli, consumare domande aperte o scrivere memoria; può ricostruire
il grafo derivato se necessario. Ingest, lint e lacune restano flussi della chat con le quattro skill.

## Aggiungere Copilot CLI a un vault Teseo esistente

```powershell
python installa.py "C:/percorso/MioVault" --client copilot --solo-integrazione
```

Installa gli adattatori e i file `.github/` senza aggiornare il motore personalizzato del grafo.
`--aggiorna --solo-integrazione` aggiorna soltanto gli adattatori selezionati e le skill, con backup.
Le istruzioni esistenti sono conservate: integra quelle del modello se erano già personalizzate.

Gli hook nativi preparano il recall a `userPromptSubmitted`, lo aggiungono al testo destinato al modello
a `userPromptTransformed`, registrano le letture `view` riuscite e consolidano la memoria a fine turno.
Il testo trasformato dal runtime è conservato; il modello rimane quello scelto nella sessione Copilot.
Se il recall fallisce, l'adattatore aggiunge indicazioni per cercare e verificare nelle pagine.

Copilot importa anche gli hook `.claude/settings*.json`: l'installatore migra gli handler Teseo verso
`claude_hook.py`, che riconosce il payload Copilot e non avvia il router Claude. Elimina i doppioni Teseo
dal file locale dopo averli registrati nel file condiviso, conservando gli altri handler e i permessi.
Le configurazioni cambiate hanno una copia di sicurezza accanto al file originale.

Riapri Copilot nella cartella del vault e verifica le configurazioni con `/env`; vale il normale consenso
del workspace. File, account e permessi globali non vengono modificati. Il formato è stato confrontato
con Copilot CLI 1.0.83 e la [documentazione degli hook](https://docs.github.com/en/copilot/reference/hooks-reference).
I test locali esercitano i callback senza chiamare modelli o servizi di rete; le versioni prive di
`userPromptTransformed` richiedono recall esplicito tramite la skill query.

## Verifiche locali

```powershell
python installa.py --prova
python -m unittest discover -s tests -v
```

Le verifiche non chiamano modelli: controllano l’installazione dei tre client, la convivenza degli hook,
il recall, il routing, la memoria separata per turno e la conservazione dei dati del vault.

## Cosa contiene

```text
installa.py          l'installatore
ADATTA.md            come adattare un vault già in uso (copiato nel vault in .graph/ADATTA.md)
kit/graph/           gli script di .graph/: grafo, recupero, hook, memoria, domande aperte, sintesi, misura
                     (banco.py e candidati.py sono facoltativi: servono a migliorare il grafo)
kit/skills/          le 4 skill: obsidian-wiki-ingest, -query, -lint, -fill-gaps
kit/vault/           i modelli di Wiki reference.md, index.md, log.md, CLAUDE.md e gli hook
kit/esempio/         il vault d'esempio usato da --prova e da --esempio
```

## Comandi di tutti i giorni

Dalla cartella del vault. L’assistente li usa attraverso le skill; servono anche per guardare dentro.

```text
python .graph/build_graph.py --check     ricostruisce la mappa e segnala i problemi
python .graph/recall.py "domanda"        i fatti che il vault metterebbe nel contesto
python .graph/misura.py                  le domande di prova: non deve mai peggiorare
python .graph/domande.py                 le domande aperte per l'autore
python .graph/sintesi.py                 le domande a cui il vault sa rispondere senza una pagina
python .graph/memoria.py --turni         pagine date dal grafo e pagine lette da Claude, turno per turno
```

Il ciclo di lavoro è **ingest → lint → lacune**: «ingerisci …», «lancia il lint», «colmiamo le lacune».

<div align="center">

# Teseo

**Trova la strada nel labirinto dei tuoi documenti.**

Una wiki Obsidian costruita dai tuoi documenti, con fonti verificabili, grafo delle relazioni e memoria delle domande.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#requisiti)
[![Markdown + SQLite](https://img.shields.io/badge/Markdown%20%2B%20SQLite-file%20locali-0F766E)](#dentro-il-vault)
[![Claude · Codex · Copilot](https://img.shields.io/badge/AI-Claude%20%C2%B7%20Codex%20%C2%B7%20Copilot-7C3AED)](#client-supportati)
[![Licenza MIT](https://img.shields.io/badge/Licenza-MIT-yellow)](LICENSE)

[Installazione](#installazione-rapida) · [Primo utilizzo](#primo-utilizzo) · [Come funziona](#come-funziona) · [Domande frequenti](#domande-frequenti) · [Contribuire](#contribuire)

</div>

---

Nel progetto, **Teseo è l'assistente** che esplora il labirinto dei documenti. Il **grafo è il filo di Arianna**
che lo orienta tra le pagine e le loro relazioni.

Teseo trasforma trascrizioni, specifiche e appunti in pagine collegate. Quando fai una domanda, il grafo aiuta
l'assistente a trovare le pagine utili, anche quando la risposta attraversa più documenti. L'assistente legge
le pagine e risponde citando le fonti; contraddizioni e informazioni mancanti restano visibili.

Funziona con **Claude Code, Codex e GitHub Copilot CLI**. Puoi usarne uno solo oppure alternarli sullo stesso vault.
Obsidian è facoltativo: i contenuti sono normali file Markdown.

<details>
<summary><strong>English summary</strong></summary>

Teseo turns an Obsidian vault (or any folder of Markdown notes) into a source-backed wiki:
raw documents in `raw/` are distilled into linked pages in `wiki/`, a local SQLite graph
(FTS5 included) records typed relations between pages, and pre/post hooks inject the
relevant facts into Claude Code, Codex or GitHub Copilot CLI before each answer — and
learn afterwards which pages were actually read. Everything runs locally; the only
Python dependency is PyYAML. Docs and code comments are in Italian; the main entry
points are the [quick install](#installazione-rapida), the [contributing guide](CONTRIBUTING.md),
the [engine architecture](doc/architettura-motore.md) and the [API reference](doc/api.md).
Licensed under the [MIT License](LICENSE).

</details>

## Perché Teseo

| Capacità | Cosa ottieni |
| --- | --- |
| **Wiki dalle fonti** | Note per concetto, persona e processo, aggiornate quando aggiungi un documento. |
| **Relazioni esplicite** | Collegamenti come `usa`, `richiede` e `referente`, per ricostruire una risposta attraverso più pagine. |
| **Recall a ogni domanda** | Gli hook portano nel contesto del modello i fatti collegati e le pagine da verificare. |
| **Memoria delle letture** | Le pagine effettivamente lette aiutano a recuperare risposte a domande simili. |
| **Lacune da risolvere** | Referenti mancanti, contraddizioni e punti aperti diventano domande per l'autore. |
| **Controlli ripetibili** | Verifiche di link, relazioni, fonti, sintesi e recupero delle pagine attese. |

```mermaid
flowchart LR
    F["Fonti originali<br/>raw/"] -->|Ingest| W["Wiki con fonti<br/>wiki/"]
    W -->|Frontmatter e link| G["Grafo locale<br/>SQLite"]
    G -->|Recall| A["Claude · Codex · Copilot"]
    A -->|Legge e verifica| W
    A --> R["Risposta con citazioni"]
```

## Installazione rapida

### Requisiti

- **Git** e **Python 3.10+**, con SQLite FTS5 disponibile nella distribuzione Python.
- **Un client AI installato e autenticato**: Claude Code, Codex oppure GitHub Copilot CLI.
- **Obsidian**, se vuoi navigare la wiki dalla sua interfaccia.

L'unica dipendenza Python aggiuntiva è **PyYAML**. Il grafo usa SQLite: non devi avviare un server di database.
Le chiamate al modello usano il client e l'account che hai configurato.

### 1. Scarica il kit

Apri un terminale ed esegui:

```sh
git clone https://github.com/manuel-albanesee/Teseo.git
cd Teseo
```

### 2. Prepara Python e prova il kit

Scegli i comandi per il tuo sistema e continua nello stesso terminale. L'ambiente virtuale tiene le dipendenze
del kit separate dagli altri progetti Python.

<details open>
<summary><strong>Windows · PowerShell</strong></summary>

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r kit/vault/requirements.txt
python installa.py --prova
```

Se sul tuo PC Python si avvia con `py`, usa `py -3 -m venv .venv` nella prima riga.

</details>

<details>
<summary><strong>macOS / Linux · Bash o Zsh</strong></summary>

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r kit/vault/requirements.txt
python installa.py --prova
```

</details>

La prova installa un vault d'esempio in una cartella temporanea, esegue i controlli e la cancella.
**Il risultato atteso è `tutto OK`.** Non chiama modelli e non richiede di configurare un vault personale.

### 3. Installa nel tuo vault

Sostituisci il percorso con quello della tua cartella Obsidian. Puoi indicare una cartella nuova: verrà creata.

**Windows:**

```powershell
python installa.py "C:/Obsidian/MioVault"
```

**macOS / Linux:**

```sh
python installa.py "$HOME/Documents/MioVault"
```

Il comando senza opzioni prepara **tutti e tre i client dentro il vault**, incluse le quattro skill per ciascuno.
Puoi preparare i file anche dei client che non hai installato. Per sceglierne uno solo:

```sh
python installa.py "PERCORSO_DEL_VAULT" --client claude
python installa.py "PERCORSO_DEL_VAULT" --client codex
python installa.py "PERCORSO_DEL_VAULT" --client copilot
```

**Hai già delle note?** L'installatore conserva le pagine e le fonti esistenti. Per farle riconoscere al grafo,
segui [Adattare un vault già in uso](ADATTA.md): le pagine della wiki devono essere in `wiki/*.md`, senza sottocartelle.

### 4. Apri il vault nel client

Apri come progetto **la cartella del vault**. Per usare una CLI, spostati in quella cartella dal terminale
con l'ambiente Python attivo e avvia `claude`, `codex` oppure `copilot`.

| Client | Passaggio iniziale |
| --- | --- |
| **Claude Code** | Accetta il normale consenso del progetto e verifica il caricamento degli hook locali. |
| **Codex** | Riapri il progetto, usa `/hooks` nella CLI e revisiona i quattro comandi verso `.graph/codex_hook.py`. |
| **Copilot CLI** | Accetta il normale consenso del workspace. `/env` mostra gli hook; `/instructions` le istruzioni; `copilot skill list` elenca le skill. |

I file di configurazione preparano l'integrazione; l'esecuzione degli hook dipende anche dalla versione del client
e dal suo consenso al progetto. L'installatore non modifica account, permessi o trust globali.

## Primo utilizzo

Apri il vault anche in Obsidian, se lo usi, e copia una fonte in `raw/`, per esempio `raw/riunione-progetto.md`.
Nella chat del client puoi scrivere direttamente:

| Obiettivo | Scrivi all'assistente |
| --- | --- |
| Aggiungere una fonte | `Ingerisci raw/riunione-progetto.md` |
| Cercare una risposta | `Quali sono i prerequisiti del rilascio e chi è il referente? Cita le pagine.` |
| Controllare la wiki | `Lancia il lint del vault` |
| Completare ciò che manca | `Colmiamo le lacune, una domanda alla volta` |

L'assistente usa le skill `obsidian-wiki-ingest`, `obsidian-wiki-query`, `obsidian-wiki-lint` e
`obsidian-wiki-fill-gaps`. Dopo l'ingest, il ciclo consigliato è **lint → lacune**.

Per esplorare prima un esempio completo, installa in una **cartella nuova dedicata**:

```sh
python installa.py "PERCORSO_DI_UN_VAULT_DEMO" --esempio
```

Poi chiedi: **«Devo fare un rilascio in produzione: cosa mi serve e chi me lo dà?»**
Il vault d'esempio collega Rilascio in produzione, Console di rilascio, Incident settimanale e Anna Rossi.
Contiene anche una contraddizione sul giorno del rilascio, che deve restare esplicita nella risposta.

## Come funziona

### Dalla domanda alla risposta

Gli hook richiamano il motore Python prima della risposta. Il **recall** recupera le relazioni del grafo e,
quando utile, le pagine ricordate da domande simili. Se non trova agganci, può cercare nel testo delle pagine.
Questi risultati indicano dove leggere: l'assistente verifica sempre i fatti nei documenti della wiki.

```mermaid
sequenceDiagram
    actor U as Tu
    participant A as Client AI
    participant T as Teseo
    participant V as Wiki e grafo
    U->>A: Domanda sul vault
    A->>T: Hook prima della risposta
    T->>V: Recupera relazioni e pagine pertinenti
    V-->>T: Fatti collegati e percorsi
    T->>T: Consulta la memoria delle domande
    T-->>A: Contesto e pagine da verificare
    A->>V: Legge le pagine
    V-->>A: Contenuto, fonti e avvertenze
    A-->>U: Risposta con citazioni
    A->>T: Letture confermate e fine turno
    T->>T: Consolida la memoria quando applicabile
```

La memoria apprende associazioni tra domande sul contenuto e pagine lette quando il grafo non ha riconosciuto
la domanda. Un risultato di `rg`, `grep` o `glob` non prova che una pagina sia stata letta.
Se il recall fallisce, l'assistente riceve indicazioni per cercare e verificare nelle pagine.

### Dalle fonti a una wiki che migliora

```mermaid
flowchart TD
    F["Nuova fonte in raw/"] --> I["Ingest<br/>Distilla e collega le pagine"]
    I --> W["Wiki aggiornata"]
    W --> L["Lint<br/>Controlla coerenza, relazioni e sintesi"]
    L --> D{"Mancano informazioni?"}
    D -->|Sì| Q["Lacune<br/>Una domanda alla volta all'autore"]
    Q -->|Risposte documentate| W
    D -->|No| C["Controlli del grafo"]
    C --> R["Query<br/>Risposte dalle pagine verificate"]
    W -.->|Interroga quando vuoi| R
```

Il lint può scrivere pagine di sintesi quando la risposta è già distribuita in più note. Quando manca un fatto,
il sistema lo chiede all'autore. Le fonti originali in `raw/` restano immutabili.

## Client supportati

Tutti i percorsi della tabella sono relativi alla cartella del vault.

| Client | Istruzioni | Hook | Skill |
| --- | --- | --- | --- |
| Claude Code | `CLAUDE.md` | `.claude/settings.json` | `.claude/skills/` |
| Codex | `AGENTS.md` | `.codex/hooks.json` | `.agents/skills/` |
| Copilot CLI | `.github/copilot-instructions.md` | `.github/hooks/teseo.json` | `.github/skills/` |

<details>
<summary><strong>Claude Code: recall e routing Opus / Haiku</strong></summary>

Gli eventi `SessionStart`, `UserPromptSubmit`, `PostToolUse` e `Stop` passano attraverso `claude_hook.py`.
Il motore storico può affidare a Haiku le domande puntuali con contesto affidabile in una sessione Opus;
le domande ampie, le modifiche e i casi incerti restano a Opus. Il prefisso `@opus` evita il passaggio a Haiku.
Il wrapper lascia gli eventi importati da Copilot al suo adattatore dedicato.

</details>

<details>
<summary><strong>Codex: attivazione, memoria e ruoli Sol / Astra / Luna</strong></summary>

Gli eventi nativi sono `SessionStart`, `UserPromptSubmit`, `PostToolUse` e `Stop`.
Codex richiede la revisione degli hook: dopo averli modificati può chiedere una nuova autorizzazione.
Gli hook aggiungono il contesto e suggeriscono un ruolo; **non cambiano il modello della chat e non avviano altri modelli**.

| Ruolo in `.graph/codex.json` | Modello predefinito |
| --- | --- |
| Ricerca e lavoro sul vault | `gpt-6.1-sol` |
| Analisi profonda | `gpt-6-astra` |
| Domande puntuali con contesto affidabile | `gpt-6-luna` |

Gli identificativi sono configurabili in base ai modelli disponibili al tuo account.
Per le letture da shell che devono insegnare alla memoria, usa il token fornito dall'hook:

```sh
python .graph/leggi.py --turno TOKEN_FORNITO_DALL_HOOK "wiki/Nome pagina.md"
```

Senza token il comando legge soltanto. I token separano sessioni e turni, durano sette giorni e non contengono
il testo delle domande. Gli eventi che dichiarano un `agent_id` sono ignorati.

Per una query autonoma che sceglie effettivamente il modello, serve Codex CLI autenticata:

```sh
python .graph/chiedi_codex.py "chi è il referente del rilascio?"
python .graph/chiedi_codex.py "@astra confronta i processi di rilascio"
python .graph/chiedi_codex.py --ricerca astra "spiega il processo di rilascio"
python .graph/chiedi_codex.py --piano "chi è il referente del rilascio?"
```

`@sol` e `@astra` forzano il ruolo di ricerca. Se Luna fallisce o richiede ricerca, il comando prova una volta
il modello di ricerca. Il processo usa un sandbox di sola lettura, una sessione effimera e hook disabilitati
per evitare ricorsione. Ingest, lint e lacune si eseguono nella chat.
`--piano` mostra la scelta senza chiamare modelli o scrivere memoria; può ricostruire il grafo derivato.

</details>

<details>
<summary><strong>Copilot CLI: prompt, letture e compatibilità con Claude</strong></summary>

`userPromptSubmitted` prepara il recall; `userPromptTransformed` lo aggiunge al testo destinato al modello,
conservando il contenuto già trasformato dal runtime. `postToolUse` registra le letture `view` riuscite;
`agentStop` e `sessionEnd` chiudono il turno e la sessione. `sessionStart` fornisce le regole iniziali.
Risponde il modello attivo di Copilot, senza avviare Claude o applicare i ruoli Codex.

`copilot_timing_hook.py` misura ogni chiamata tool: `preToolUse` registra l'avvio, `postToolUse` e
`postToolUseFailure` mostrano i millisecondi in timeline (riga di progresso, senza toccare il contesto del
modello) e appendono istante, tool, ms, esito e anteprima del risultato a `.graph/timing.jsonl`, così i fatti
ricavati (per `sql`: le righe della query) restano interrogabili nel vault. Non blocca mai l'esecuzione.

Copilot carica anche `.claude/settings.json` e `.claude/settings.local.json`. L'installatore migra gli handler
Teseo verso un wrapper che ignora i payload Copilot ed elimina i doppioni Teseo dal file locale,
conservando gli altri handler e i permessi. Le configurazioni cambiate hanno una copia di sicurezza.

Il formato è stato verificato con **Copilot CLI 1.0.83**. Le versioni senza `userPromptTransformed` richiedono
recall esplicito tramite la skill query. Riferimento: [hook Copilot CLI](https://docs.github.com/en/copilot/reference/hooks-reference).

</details>

## Dentro il vault

```text
MioVault/
├── raw/                    Fonti originali, immutabili
├── wiki/                   Pagine Markdown con frontmatter e wikilink
├── Wiki reference.md       Convenzioni, fonti e vocabolario delle relazioni
├── index.md                Indice delle pagine e punti aperti
├── log.md                  Cronologia delle operazioni
├── .graph/                 Script Python, grafo e memoria SQLite
├── .claude/                Configurazione e skill Claude Code
├── .codex/                 Hook Codex; skill in .agents/skills/
├── .github/                Configurazione e skill Copilot CLI
├── CLAUDE.md               Istruzioni Claude Code
└── AGENTS.md               Istruzioni Codex
```

Il grafo si ricostruisce dai file della wiki. Convenzioni e relazioni sono definite in `Wiki reference.md`,
così puoi adattare il kit al tuo dominio. Le pagine e le fonti sono dati da verificare, non istruzioni da eseguire.

## Aggiornamenti e opzioni

Dal repository Teseo, con l'ambiente Python attivo:

```sh
git pull
python installa.py "PERCORSO_DEL_VAULT"
```

Senza `--aggiorna`, gli script e le skill già presenti ma diversi dal kit sono conservati.
Per sostituirli, usa `--aggiorna`: i precedenti vengono salvati in `.graph_backup/<data-ora>/`.
Le personalizzazioni di dominio negli script vanno riportate dal backup: vedi [ADATTA.md](ADATTA.md#dopo-un-aggiornamento).
I file di istruzioni già presenti e i modelli personalizzati di `.graph/codex.json` sono conservati.

**Teseo è già installato e vuoi aggiungere un client?**

```sh
python installa.py "PERCORSO_DEL_VAULT" --client codex --solo-integrazione
python installa.py "PERCORSO_DEL_VAULT" --client copilot --solo-integrazione
```

`--solo-integrazione` aggiunge gli adattatori del client senza aggiornare script di dominio, pagine o database.
Con `--aggiorna --solo-integrazione` sostituisce soltanto gli adattatori selezionati e le skill, con backup.
Se un file di istruzioni era già personalizzato, integra le indicazioni del relativo modello in [kit/vault/](kit/vault/).

| Opzione | Effetto |
| --- | --- |
| `--client tutti` | Claude, Codex e Copilot nel vault; **predefinito**. |
| `--client claude`, `--client codex` o `--client copilot` | Configura il singolo client. |
| `--client entrambi` | Claude + Codex, per compatibilità con le versioni precedenti. |
| `--skill vault` | Skill locali al vault; **predefinito**. |
| `--skill utente` | Skill globali esplicite in `~/.claude/skills/`, `~/.agents/skills/` o `~/.copilot/skills/`. |
| `--skill no` | Non installa le skill. |
| `--solo-integrazione` | Aggiunge un client a un vault con Teseo già installato. |
| `--aggiorna` | Sostituisce script e skill diversi, con backup. |
| `--dashboard` | Inizializza un vault nuovo nel formato v1 per la dashboard; non converte vault legacy. |
| `--esempio` | Aggiunge il vault d'esempio, se `wiki/` non contiene pagine Markdown al primo livello. |
| `--prova` | Esegue la prova completa in una cartella temporanea, poi la elimina. |

## Collaborare su un vault (pull e push automatici)

Per lavorare in più persone su uno stesso vault, installa con `--collabora` e l'URL di un repository GitHub **dati**, distinto da questo kit:

```sh
python installa.py "PERCORSO_DEL_VAULT" --collabora https://github.com/organizzazione/vault-dati.git
```

Cosa succede, in base alla situazione:

| Situazione | Risultato |
| --- | --- |
| Cartella con le tue note e repository remoto **vuoto** | Mostra i file che verranno condivisi e quelli che restano solo sul tuo disco, chiede conferma, crea il repository dati e fa il primo push |
| Cartella **vuota** e repository remoto già popolato (un collega l'ha creato) | Lo clona, installa il kit e attiva la collaborazione |
| Il repository remoto non esiste ancora | Crealo su GitHub, oppure aggiungi `--crea-remote` (richiede `gh auth login`; chiede conferma) |

Il comando è ripetibile. Per saltare la domanda di conferma (l'anteprima si stampa comunque) usa `--si`; il branch condiviso si sceglie con `--branch` (predefinito `main`). Servono `git config --global user.name` e `user.email`: sono i nomi che compaiono nella storia del repository.

Da quel momento le skill `obsidian-wiki-ingest`, `obsidian-wiki-lint` e `obsidian-wiki-fill-gaps` fanno da sole:

- **all'inizio** `python .graph/teseo_git.py pre`: scarica gli aggiornamenti dei colleghi e ricostruisce il grafo;
- **alla fine** `python .graph/teseo_git.py post`: controlla il grafo e pubblica un commit col tuo nome, l'agente (`claude`, `codex`, `copilot`) e la skill usata (`Teseo-Agent`, `Teseo-Skill`).

Le modifiche fatte a mano, per esempio in Obsidian, si pubblicano con `python .graph/teseo_git.py post --skill manuale --agente umano`. Se la rete manca il commit resta in locale e si riprende con `python .graph/teseo_git.py riprendi`.

Cosa **non** si automatizza: due persone che modificano la **stessa nota**, o note collegate tra loro, fermano la pubblicazione. Il vault vivo resta intatto e si risolve dalla dashboard (**Pubblicazione Git dei dati → Risolvi**). Le aggiunte concorrenti a `log.md` e `index.md` si uniscono da sole. Restano sul tuo disco script, configurazioni dei client e fonti non testuali (PDF e simili). Per i vault esistenti aggiorna anche le skill: `python installa.py "PERCORSO_DEL_VAULT" --aggiorna`. Decisioni e limiti nel [documento 9](doc/09-autosync-collaborativo.md).

## Dashboard locale

Per un **vault nuovo in una cartella vuota**, abilita esplicitamente il formato
con generazioni del grafo e journal locale:

```powershell
python installa.py "C:/Obsidian/NuovoVault" --dashboard
python "C:/Obsidian/NuovoVault/.graph/teseo_dashboard.py" --vault "C:/Obsidian/NuovoVault"
```

Apri il collegamento completo stampato dal launcher. La UI offre grafo e lista,
filtri, dettaglio, ontologia e diagnostica. **Ricostruisci grafo** avvia un job
esplicito: note, fonti e DB personali restano invariati. L'esito indica quando
premere **Aggiorna vista**. **Arresta servizio** o Ctrl+C chiudono il listener e
attendono i worker; chiudere solo la scheda lascia il processo attivo.

Nei vault compatibili sono disponibili anche cicli ingest/lint con ricevute e
apply manuale, risposte condivise con migrazione selettiva e **Pubblicazione Git
dei dati**. Il repository dati è distinto da questo kit: revisiona la preview,
configura branch e visibilità prima del ciclo, poi pubblica un UUID validato.
Credenziali delegate a Git locale; note correlate e conflitti richiedono revisione.
La modalità PR propone un branch: apertura e merge restano manuali. Senza `--collabora`
nessuna pubblicazione o applicazione è automatica; con `--collabora` pull e push partono dalle skill (vedi sopra).
Contratti, recupero e limiti nel [passo 6](doc/06-pubblicazione-github.md).

**Ricevi aggiornamenti dal gruppo** aggiunge rilevamento remoto opt-in, pausa
persistente e controllo immediato. Il processo continua a controllare con la
scheda chiusa; prepara un candidato isolato e lascia invariato il vault.
Per adottarlo sospendi editor e hook, revisiona OID e digest, poi conferma
l'applicazione manuale. Il checkpoint ricostruisce grafo e stato condiviso;
**Aggiorna vista** carica la nuova generazione. Nessun ingest/lint AI viene
avviato dal controllo remoto. In caso di interruzione conserva journal e copie
locali e usa il recovery esplicito; modifiche esterne possono bloccarlo.
Apply automatico disabilitato: i buffer editor non salvati non sono rilevabili.
Dettagli, API e limiti nel [passo 7](doc/07-ricezione-automatica.md).

Il launcher viene distribuito anche dall'installazione ordinaria. Nei vault
legacy l'attach verifica cartella e compatibilità, ma consultazione del grafo
versionato e rebuild via servizio richiedono un manifest compatibile: non esiste
ancora una procedura di adozione automatica. `--dashboard` rifiuta un legacy
non vuoto. Per aggiornare il runtime di un vault già compatibile usare
`python installa.py "PERCORSO_DEL_VAULT" --aggiorna`, con servizio arrestato;
i file sostituiti sono conservati in `.graph_backup/`.

Per ricordare i collegamenti, scegli un file locale nel perimetro ignorato da Git:

```powershell
python "C:/Obsidian/NuovoVault/.graph/teseo_dashboard.py" --vault "C:/Obsidian/NuovoVault" --registry "C:/Obsidian/NuovoVault/.teseo/local/dashboard-vaults.json"
```

La directory del registro deve già esistere. Nei riavvii con lo stesso `--registry`
puoi omettere `--vault`. Il file conserva solo percorsi e identità; sessione e
CSRF restano effimeri. Senza opzione, l'elenco termina col processo. Un secondo
servizio sullo stesso registro viene rifiutato. I job restano nel journal del
vault; dopo un'interruzione richiedono verifica e una nuova richiesta esplicita,
senza replay automatico. Dettagli e limiti nel [piano dashboard](doc/02-dashboard-consultazione.md).

## Domande frequenti

**Devo installare tutti e tre i client?** No. Ne basta uno, autenticato. Il default prepara le configurazioni
locali di tutti e tre per poter passare da un client all'altro.

**Serve Obsidian aperto?** No. Il kit lavora sui file Markdown e sui database SQLite del vault.

**I documenti restano sul mio computer?** File e database del kit sono locali. I contenuti letti dall'assistente
possono essere inviati al provider del modello secondo il funzionamento e la configurazione del client AI.

**Il grafo non trova una risposta: è un errore?** Può mancare un alias, una relazione o il fatto stesso.
L'assistente cerca nelle pagine, segnala ciò che manca e, quando applicabile, la memoria associa la domanda alle letture.

**Non arriva il recall automatico.** Verifica il progetto aperto, il consenso agli hook e la versione del client.
La skill query descrive anche il recall esplicito: resta utilizzabile se il client non supporta gli hook.

**PowerShell blocca l'attivazione dell'ambiente virtuale.** Puoi usare il Prompt dei comandi nella cartella Teseo
ed eseguire `.venv\Scripts\activate.bat`, poi continuare con gli stessi comandi `python`.

**`misura.py` fallisce nel mio vault.** Il banco predefinito si riferisce alle pagine d'esempio.
Adatta le domande e le pagine attese al tuo dominio seguendo [ADATTA.md](ADATTA.md#6-le-domande-di-prova).

## Contribuire

Per segnalare un problema o proporre una funzione, apri una [issue](https://github.com/manuel-albanesee/Teseo/issues).
Per una correzione, proponi una pull request con il comportamento atteso e i controlli eseguiti.
Ambiente di sviluppo, controlli obbligatori e convenzioni sono in [CONTRIBUTING.md](CONTRIBUTING.md);
le modifiche consegnate si registrano in [CHANGELOG.md](CHANGELOG.md). Il progetto è
rilasciato con [licenza MIT](LICENSE).

Dal repository, con le dipendenze installate:

```sh
python installa.py --prova
python -m unittest discover -s tests -v
```

Questi controlli non chiamano modelli: verificano installazione, convivenza degli hook, recall, routing,
memoria e conservazione dei dati. Per esplorare il codice:

| Percorso | Contenuto |
| --- | --- |
| [installa.py](installa.py) | Installazione, aggiornamenti e configurazione dei client. |
| [kit/graph/](kit/graph/) | Grafo, recall, hook, memoria, domande aperte e misure. |
| [kit/skills/](kit/skills/) | Le quattro operazioni della wiki. |
| [kit/vault/](kit/vault/) | Modelli delle convenzioni e delle configurazioni. |
| [kit/esempio/](kit/esempio/) | Vault dimostrativo e banco di prova. |
| [tests/](tests/) | Test di regressione delle integrazioni. |
| [doc/architettura-motore.md](doc/architettura-motore.md) | Riferimento tecnico del motore: schemi SQLite, pipeline di recall, contratti degli hook. |
| [doc/kpi-recall.md](doc/kpi-recall.md) | Il recall sul banco come KPI della salute del vault: metriche, baseline, strategie di miglioramento. |
| [doc/api.md](doc/api.md) | Riferimento API generato dai docstring (`script/genera_api_doc.py`). |
| [doc/](doc/) | Piano ed evidenze della dashboard e della collaborazione. |

<details>
<summary><strong>Comandi utili dalla cartella del vault</strong></summary>

| Comando | Uso |
| --- | --- |
| `python .graph/build_graph.py --check` | Valida e ricostruisce solo se valido; in caso di errore conserva il grafo precedente. |
| `python .graph/backup_personal.py` | Backup consistente di memoria/domande in `.teseo/local/backups/`, per vault con manifest compatibile. |
| `python .graph/teseo_dashboard.py --vault "C:/Obsidian/MioVault"` | Avvia consultazione e rebuild derivati espliciti su loopback; `--no-browser` stampa il collegamento senza aprire il browser. |
| `python .graph/recall.py "domanda"` | Mostra i fatti collegati dal grafo. |
| `python .graph/misura.py` | Misura il recupero sulle domande configurate per il vault. |
| `python .graph/domande.py` | Elenca le domande aperte per l'autore. |
| `python .graph/sintesi.py` | Trova risposte distribuite tra più pagine, candidate alla sintesi. |
| `python .graph/memoria.py --turni` | Confronta pagine suggerite e pagine lette, turno per turno. |

Nei vault con `.teseo/project.json` compatibile, il builder usa generazioni
immutabili e i lettori risolvono `.teseo/local/graph-current.json`. Il file
`.graph/graph.sqlite` resta il percorso legacy; può essere assente nella nuova
modalità. L'installatore non crea il manifest e non migra automaticamente i vault.

</details>

## Origine del progetto

Teseo parte dal pattern [LLM Wiki di Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
fonti immutabili, pagine distillate e convenzioni esplicite. Aggiunge il grafo come filo di Arianna, il recall automatico,
la memoria delle domande e un ciclo di manutenzione verificabile.

[Torna all'inizio](#teseo)

# Teseo

Un vault Obsidian scritto e tenuto in ordine da Claude Code a partire dai tuoi documenti, con una mappa dei
collegamenti tra le pagine. La mappa è il filo: a ogni domanda dice a Claude quali pagine servono e come sono
collegate, anche quando la risposta passa da quattro pagine e la domanda ne nomina una sola.

Il metodo parte dall'idea «LLM Wiki» di Andrej Karpathy: fonti originali in `raw/`, pagine distillate in `wiki/`,
regole in `Wiki reference.md`. Teseo aggiunge il grafo (`.graph/`), gli hook che lo mettono nel contesto a ogni
domanda, la memoria delle domande, le domande aperte per l'autore, le pagine di sintesi scritte dal lint e una
misura che dice se ogni modifica migliora o peggiora il recupero.

## Requisiti

- [Claude Code](https://claude.com/claude-code)
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

Crea la struttura (`raw/`, `wiki/`, `index.md`, `log.md`, `Wiki reference.md`, `CLAUDE.md`), copia gli script in
`.graph/`, registra gli hook in `.claude/settings.json` e installa le 4 skill in `~/.claude/skills/`. Poi apri
Claude Code nella cartella del vault, metti un documento in `raw/` e scrivi «ingerisci raw/nome-file».

Con `--esempio` aggiunge anche il vault d'esempio, da togliere dopo averlo guardato.

## Installare in un vault già in uso

```bash
python installa.py "C:/percorso/VaultEsistente"
```

Non tocca le pagine né le fonti. Aggiunge gli script, unisce i suoi hook a quelli già presenti (con una copia di
sicurezza di `settings.json`) e crea i file di regole solo se mancano. Alla fine dice cosa manca perché il grafo veda
le pagine: di solito spostarle in `wiki/` senza sottocartelle e sistemare le proprietà del frontmatter.
I passi sono in [ADATTA.md](ADATTA.md), scritto anche per farlo eseguire a Claude.

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
| `--skill utente` | skill in `~/.claude/skills/`, valide per tutti i vault (predefinito) |
| `--skill vault` | skill in `<vault>/.claude/skills/`, solo per quel vault |
| `--skill no` | skill non installate |
| `--aggiorna` | sostituisce script e skill diversi dal kit, con copia di sicurezza |
| `--esempio` | aggiunge il vault d'esempio (solo con `wiki/` vuota) |
| `--prova` | prova completa in una cartella temporanea |

## Cosa contiene

```text
installa.py          l'installatore
ADATTA.md            come adattare un vault già in uso
kit/graph/           gli script di .graph/: grafo, recupero, hook, memoria, domande aperte, sintesi, misura
                     (banco.py e candidati.py sono facoltativi: servono a migliorare il grafo)
kit/skills/          le 4 skill: obsidian-wiki-ingest, -query, -lint, -fill-gaps
kit/vault/           i modelli di Wiki reference.md, index.md, log.md, CLAUDE.md e gli hook
kit/esempio/         il vault d'esempio usato da --prova e da --esempio
```

## Comandi di tutti i giorni

Dalla cartella del vault. Claude li lancia da solo; servono per guardare dentro.

```text
python .graph/build_graph.py --check     ricostruisce la mappa e segnala i problemi
python .graph/recall.py "domanda"        i fatti che il vault metterebbe nel contesto
python .graph/misura.py                  le domande di prova: non deve mai peggiorare
python .graph/domande.py                 le domande aperte per l'autore
python .graph/sintesi.py                 le domande a cui il vault sa rispondere senza una pagina
python .graph/memoria.py --turni         pagine date dal grafo e pagine lette da Claude, turno per turno
```

Il ciclo di lavoro è **ingest → lint → lacune**: «ingerisci …», «lancia il lint», «colmiamo le lacune».

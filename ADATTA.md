# Adattare un vault già in uso

`installa.py` aggiunge il sistema senza toccare le pagine. Perché il grafo le veda e le colleghi servono alcuni
adattamenti, che dipendono da come è fatto il vault. Questa guida è scritta sia per te sia per Claude Code: puoi
aprire Claude nella cartella del vault e scrivere

> Adatta questo vault al kit Teseo seguendo .graph/ADATTA.md, un passo alla volta, chiedendomi conferma prima di spostare o rinominare file.

Ogni passo si chiude con `python .graph/build_graph.py --check`: l'obiettivo è arrivare a «nessun problema».

## 1. Mettere al sicuro il vault

Prima di tutto un commit di Git o una copia della cartella. I passi 2 e 4 spostano file e cambiano intestazioni.

## 2. Le pagine in `wiki/`, senza sottocartelle

Il grafo legge solo i file `wiki/*.md`. `installa.py` dice quante pagine stanno fuori (in radice o in altre
cartelle) e quante in sottocartelle di `wiki/`.

- Le **pagine di sapere** (sistemi, processi, persone, concetti, episodi) vanno in `wiki/`, tutte allo stesso livello.
  Spostale da Obsidian, che aggiorna i link; i `[[wikilink]]` per nome funzionano comunque, perché il nome del
  file non cambia. Due pagine con lo stesso nome in cartelle diverse vanno rinominate prima.
- I **documenti originali** (trascrizioni, PDF, mail, appunti grezzi) vanno in `raw/`. Lì non si modificano più: sono
  le fonti che le pagine citano.
- Quello che non è né l'uno né l'altro (diari, bozze, modelli di Obsidian) può restare dov'è: il grafo lo ignora.

Le cartelle servivano a raggruppare? Il raggruppamento passa nel frontmatter: `parte_di: "[[Area]]"` o `tags`.

## 3. Le regole: `Wiki reference.md` e `index.md`

`installa.py` crea `Wiki reference.md` e `index.md` solo se mancano. Se il vault ha già un file di convenzioni con
un altro nome, conviene tenere `Wiki reference.md` (gli script leggono quel nome) e copiarci le regole esistenti.
Gli script leggono tre tabelle:

- **`## Relazioni tipizzate`** in `Wiki reference.md`: il vocabolario delle relazioni. Il modello del kit ne ha nove;
  aggiungi una riga per ogni relazione che il vault usa davvero (vedi passo 4).
- **`## Chiavi delle fonti`** in `Wiki reference.md`: una riga per fonte, con la chiave tra backtick nella prima
  colonna (`` | `call-2026-09-10` | raw/call-2026-09-10.md | … | ``). Le pagine citano le fonti con quella chiave.
- **`## Pagine`** in `index.md`: righe `| [[Pagina]] | descrizione |`. La descrizione finisce nel contesto che Claude
  riceve. Facoltativa, ma utile. Nello stesso file, `## Punti aperti nel vault` raccoglie le questioni aperte.

## 4. Le intestazioni delle pagine (frontmatter)

Cinque proprietà hanno un ruolo fisso: `tipo`, `tags`, `fonti`, `aggiornato`, `aliases`. **Ogni altra proprietà è
trattata come una relazione** e deve contenere link tra virgolette (`usa: "[[Console]]"`). Il controllo segnala:

| Segnalazione | Cosa fare |
| --- | --- |
| `proprietà 'created' senza link` | Proprietà di servizio di Obsidian o dei plugin (`created`, `status`, `date`…). Se il vault ne usa poche e sempre le stesse, aggiungile a `NON_RELAZIONI` in `.graph/build_graph.py`; altrimenti spostale in `tags` o toglile. |
| `relazione 'related' fuori vocabolario` | Una proprietà con link che non è nel vocabolario. Se dice davvero *come* due pagine sono legate, rinominala con una relazione del vocabolario (`usa`, `parte_di`, `riguarda`…) o aggiungi la sua riga alla tabella del passo 3. Se dice solo «collegato», toglila: il link nel testo basta. |
| `tipi non ammessi dal vocabolario` | Il `tipo` di una delle due pagine non è tra quelli ammessi da quella relazione: correggi il tipo o la relazione. |
| `fonte '…' usata ma non censita` | Aggiungi la chiave alla tabella delle fonti. |

Ogni pagina dovrebbe avere un `tipo` (`sistema`, `processo`, `progetto`, `persona`, `concetto`, `episodio`…):
`sistema`, `processo` e `progetto` senza `referente` diventano domande aperte, le catene partono da processi e sistemi.

## 5. Le relazioni tipizzate

Qui il grafo comincia a servire. Le relazioni si dichiarano solo se la pagina le afferma nel testo. È il lavoro
della skill di lint, a lotti:

> Lancia il lint sulle pagine di wiki/ che iniziano per A–F: aggiungi le relazioni tipizzate e gli alias che il testo afferma, senza toccare altro.

Partire dai processi e dai sistemi più usati, con `usa`, `richiede`, `parte_di` e `referente`: sono quelle che
fanno funzionare le domande a catena.

## 6. Le domande di prova

In `.graph/misura.py` sostituisci i dati del vault d'esempio con i tuoi: `DOMANDE` (10 domande vere, almeno 3-4 a
catena), `ATTESE`, `ROUTING`, `NEGATIVI`, `TESTO`. Finché non lo fai, `python .graph/misura.py` fallisce: cerca le
pagine dell'esempio. In `.graph/recall.py` e `.graph/build_graph.py` aggiorna `PAROLE_COMUNI` / `PAROLE_COMUNI_NOMI`
con i nomi di pagina che sono anche parole comuni.

## 7. Verifica

```text
python .graph/build_graph.py --check     nessun problema
python .graph/misura.py                  tutte le pagine attese, exit 0
python .graph/domande.py                 le domande aperte del vault
```

Poi apri Claude Code nella cartella e fai una domanda che nomina una pagina: sotto la risposta deve comparire la riga
`grafo: N fatti da …`.

## Dopo un aggiornamento

`python installa.py <vault> --aggiorna` sostituisce gli script diversi dal kit e salva i vecchi in
`.graph_backup/<data-ora>/`. Le modifiche dei passi 4 e 6 (`NON_RELAZIONI`, `PAROLE_COMUNI`, i dati di
`misura.py`, `NON_TERMINI` e `CON_REFERENTE` in `domande.py`) vanno riportate a mano dal backup.

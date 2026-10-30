---
name: obsidian-wiki-query
description: Interroga un vault Obsidian gestito come "LLM Wiki" (pattern Karpathy) sintetizzando una risposta con citazioni alle pagine del vault, e offre di archiviare la risposta come nuova pagina. Usa quando l'utente fa una domanda che va cercata/risposta usando le note di un vault Obsidian esistente.
---

# Obsidian Wiki — Query

Implementa l'operazione **Query** del pattern "LLM Wiki" di Andrej Karpathy
(fonte: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## Input

Livello 3 = regole stabili del vault, livello 4 = materiale di questa esecuzione. I passi rimandati sono quelli di «Processo».

| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `Wiki reference.md` | «Regole non negoziabili», «Convenzioni delle pagine» | sempre: cosa non toccare e come citare le fonti |
| 3 | `Wiki reference.md` | «Relazioni tipizzate», «Chiavi delle fonti» | solo se archivi la risposta come pagina (passo 6): frontmatter, relazioni, alias, fonti |
| 4 | `index.md` | tutto | pagine rilevanti che il grafo non ha dato (passo 2) |
| 4 | recall del grafo | blocco «Dal grafo della wiki…» o esito di `recall.py` | dove guardare; ogni fatto va verificato sulla pagina (passi 1 e 3) |
| 4 | `wiki/*.md` | pagine indicate dal recall e dall'index | fonte della risposta (passo 3) |

## Processo

**Client:** in Copilot CLI leggi `.github/copilot-instructions.md`: gli hook `.github/hooks/teseo.json` aggiungono il recall al prompt del modello e registrano le letture `view` riuscite. Usa il modello attivo della sessione; i ruoli Sol/Astra/Luna riguardano solo Codex. In Codex leggi anche `AGENTS.md`. Gli hook nativi sono in `.codex/hooks.json`; se hanno già fornito il recall, usa quel contesto. Per le letture da shell usa `.graph/leggi.py` con il token di turno fornito dall'hook, così la memoria registra le pagine effettivamente aperte. In PowerShell adatta gli esempi POSIX (`/dev/null`, `&&`) alla shell disponibile, mantenendo il controllo dei codici di uscita. Il routing effettivo Luna/Sol/Astra è disponibile nel comando autonomo `.graph/chiedi_codex.py`; nella chat risponde il modello attivo.

1. **Interroga il grafo**, se il vault ne ha uno (es. `.graph/build_graph.py` e `.graph/recall.py`). Ricostruiscilo e passa la domanda così come l'ha scritta l'utente:
   `python .graph/build_graph.py > /dev/null && python .graph/recall.py "<domanda>"`
   La ricostruzione dura meno di un secondo e garantisce che il grafo rispecchi le pagine. L'output elenca le pagine riconosciute nella domanda (per nome o alias) e i fatti collegati: relazioni tipizzate (`referente`, `usa`, `parte_di`, …) e pagine menzionate. Se non stampa nulla, la domanda non contiene nomi di pagina né alias: prosegui dall'index.
   Se il vault ha un hook che inietta il grafo a ogni prompt (es. `.graph/recall_hook.py`) e il contesto contiene già i fatti per questa domanda («Dal grafo della wiki…»), non rilanciare il recall: usa quei fatti. Se l'hook ha segnalato «nessuna pagina riconosciuta», prosegui dall'index.
2. **Parti dall'index** del vault (es. `index.md` o la nota indice/MOC) per individuare le pagine rilevanti che il grafo non ha dato, invece di rifare una ricerca esplorativa da zero sul filesystem.
3. **Leggi le pagine rilevanti** (quelle suggerite dal grafo e dall'index) e, se serve, segui i `[[wikilink]]` per raccogliere il contesto collegato. Il grafo indica dove guardare, ma non è la fonte della risposta: ogni fatto preso dal grafo va verificato sulla pagina, che può contenere un `⚠️ da verificare`, una data o una precisazione («nella call», «al 2021») che la relazione da sola non mostra.
4. **Sintetizza una risposta con citazioni** — cita le pagine/note del vault da cui deriva ogni affermazione (non solo la fonte raw originale). Se la domanda tocca dati contraddittori tra note diverse, segnalalo esplicitamente invece di appiattire la contraddizione.
5. **Scegli il formato adatto alla domanda**: nota markdown, tabella di confronto, deck di slide (Marp), grafico, ecc. — non forzare sempre un formato unico.
6. **Offri di archiviare la risposta nel vault** come nuova pagina se ha valore duraturo (una risposta buona non deve sparire nella chat history). Se l'utente conferma, crea la pagina seguendo le convenzioni del vault, collegala con `[[wikilink]]` alle pagine correlate, e aggiorna l'index. Se il vault ha il grafo, dichiara nel frontmatter relazioni e alias come per un ingest e chiudi con `python .graph/build_graph.py --check` senza problemi.
7. Se l'archiviazione avviene, **appendi un'entry al log** (es. `log.md`):
   `## [AAAA-MM-GG] query | <oggetto>`

## Checkpoint

| Dopo il passo | L'agente presenta | L'utente decide |
| --- | --- | --- |
| 5 | risposta con citazioni, nel formato adatto alla domanda | se archiviarla nel vault come pagina nuova (passo 6) |

## Verifica

| Controllo | Comando | Esito atteso |
| --- | --- | --- |
| Ogni affermazione cita una pagina del vault (passo 4) | rilettura della risposta | nessuna affermazione senza `[[Pagina]]` |
| Grafo dopo l'archiviazione (passo 6) | `python .graph/build_graph.py --check` | nessun problema |

## Output

| Artefatto | Posizione | Formato |
| --- | --- | --- |
| Risposta | chat | testo con citazioni alle pagine, contraddizioni segnalate |
| Pagina archiviata (solo su conferma) | `wiki/<Titolo>.md` e riga in `index.md` | convenzioni del vault; relazioni e alias nel frontmatter |
| Voce di log (solo se archivia) | `log.md` | intestazione `## [AAAA-MM-GG] query` con l'oggetto |

## Note operative

- Lo schema si legge per sezioni, come dice l'Input. Se ti serve una regola che non è nelle sezioni caricate, o hai un dubbio, leggi `Wiki reference.md` per intero: prevale sempre su questa skill.
- Non modificare le pagine esistenti per rispondere a una query — solo eventualmente aggiungerne una nuova, su conferma dell'utente. Ricostruire `graph.sqlite` non conta come modifica: è un file derivato dalle pagine.
- Se il grafo non trova la pagina giusta, o riporta fatti fuori tema, dillo nel riepilogo (es. «il recall non ha riconosciuto X»): sono i casi che servono a migliorare alias e `recall.py`.
- Se l'index non copre a sufficienza il vault (vault molto grande) e nel vault esiste uno strumento di ricerca dedicato (es. `qmd` o script locale), preferiscilo a una scansione manuale di tutti i file.

---
name: obsidian-wiki-ingest
description: Ingerisce una fonte grezza (trascrizione, PDF, articolo, appunti) in un vault Obsidian gestito come "LLM Wiki" (pattern Karpathy) — distilla in note atomiche densamente interlinkate, aggiorna index e log. Usa quando l'utente chiede di "ingerire", "aggiungere al vault/wiki", "processare questo materiale nel vault Obsidian" o simili riferiti a un vault Obsidian esistente.
---

# Obsidian Wiki — Ingest

Implementa l'operazione **Ingest** del pattern "LLM Wiki" di Andrej Karpathy
(fonte: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Il vault è un repo di file markdown a 3 livelli:
- **Raw sources** — materiale grezzo, immutabile (trascrizioni, PDF, appunti). Non modificare mai.
- **La wiki** — pagine markdown generate e possedute interamente dall'LLM.
- **Lo schema** — un file indice/convenzioni nel vault (es. `Wiki reference.md` o `CLAUDE.md`) che descrive struttura, convenzioni e workflow. Leggilo sempre per primo se esiste.

## Procedura

**Client:** in Copilot CLI leggi `.github/copilot-instructions.md`: gli hook `.github/hooks/teseo.json` aggiungono il recall al prompt del modello e registrano le letture `view` riuscite. Usa il modello attivo della sessione; i ruoli Sol/Astra/Luna riguardano solo Codex. In Codex leggi anche `AGENTS.md`. Gli hook nativi sono in `.codex/hooks.json`; se hanno già fornito il recall, usa quel contesto. Per le letture da shell usa `.graph/leggi.py` con il token di turno fornito dall'hook, così la memoria registra le pagine effettivamente aperte. In PowerShell adatta gli esempi POSIX (`/dev/null`, `&&`) alla shell disponibile, mantenendo il controllo dei codici di uscita.

0. **Sincronizza.** Se esiste `.graph/teseo_git.py` (vault collaborativo): `python .graph/teseo_git.py pre --skill ingest --agente <claude|codex|copilot>` (il client che stai usando). Exit 0: prosegui e riporta all'utente quanto ricevuto (campo `message`). Exit 2: **fermati senza toccare il vault** e riporta il messaggio: serve un'azione dell'utente (modifiche non pubblicate, storie divergenti, pubblicazione da risolvere nella dashboard). Exit 3: la rete manca; prosegui e avvisa che la pubblicazione avverrà dopo. Se lo script non c'è o risponde «Autosync non attivo», salta il passo. Non eseguire mai `git` a mano nel vault.

1. **Localizza il vault e lo schema.** Se non è ovvio dal contesto, chiedi o cerca il file indice/convenzioni (spesso in root del vault). Non riscrivere le convenzioni esistenti senza motivo: seguile.
2. **Leggi la fonte grezza** per intero (o a blocchi se molto lunga). Se disponibile, usa i timestamp/riferimenti originali (es. `[mm:ss → mm:ss]`) per poterli citare nelle note.
3. **Distilla, non trascrivere.** Ogni nota è **atomica**, in stile enciclopedico, un concetto/entità per nota — non un riassunto lineare né una copia verbatim della fonte. Collega densamente con `[[wikilink]]` alle note esistenti e a quelle nuove.
4. **Aggiorna la wiki esistente**, non solo crea pagine nuove: una singola fonte tocca tipicamente 10-15 pagine (nuove entità, aggiornamento di pagine concetto, note su dove la nuova fonte contraddice o rafforza claim precedenti).
5. **Dichiara relazioni e alias nel frontmatter**, se lo schema definisce un vocabolario di relazioni tipizzate (es. sezione «Relazioni tipizzate» in `Wiki reference.md`). Per ogni pagina creata o toccata:
   - aggiungi le relazioni del vocabolario che la pagina **afferma nel testo** (es. `referente`, `usa`, `parte_di`), sulla pagina da cui parte la freccia e con i link tra virgolette: `usa: ["[[RTC]]", "[[Change Console]]"]`. Rispetta i tipi ammessi da/a. Niente relazioni incerte o marcate `⚠️ da verificare`: resta il solo wikilink nel testo;
   - aggiungi in `aliases` gli altri nomi con cui l'entità compare nella fonte (sigle, forme «Cognome Nome», nomi di file o di codice). Mai alias ambigui o non verificati;
   - se la fonte corregge o smentisce una relazione già dichiarata, aggiorna il frontmatter insieme al testo.
   - `causa` (se nel vocabolario) solo se la fonte afferma il nesso causale con parole sue («perché», «a causa di», «ha provocato»), mai per semplice sequenza o correlazione; se la fonte dà il grado di certezza o la frase, aggiungi `relazioni_dettaglio` sulla pagina della causa (`confidenza`: alta/media/bassa, `evidenza`: frase breve).
6. **Ricostruisci il grafo**, se il vault ne ha uno (es. `.graph/build_graph.py`): `python .graph/build_graph.py --check`. Correggi tutti i problemi segnalati (link non risolti, relazioni fuori vocabolario, tipi non ammessi, alias duplicati, fonti non censite) e rilancia finché non restano problemi. Non chiudere l'ingest con il grafo disallineato.
7. **Aggiorna l'index** (es. `index.md` o la nota indice del vault) con le nuove pagine: link + riassunto in una riga + eventuali metadati (data, fonte).
8. **Appendi un'entry al log** (es. `log.md`) con prefisso parsabile e coerente, tipicamente:
   `## [AAAA-MM-GG] ingest | <oggetto>`
   Se c'è il grafo, includi le relazioni e gli alias aggiunti e l'esito del `--check`.
9. **Pubblica.** Con `--check` pulito e il log scritto, se esiste `.graph/teseo_git.py`: `python .graph/teseo_git.py post --skill ingest --agente <claude|codex|copilot>`. Exit 0: riporta l'esito (`message`: commit pubblicato, oppure nulla da pubblicare). Exit 3: la rete manca e il commit è conservato; dillo e ricorda `python .graph/teseo_git.py riprendi`. Exit 2: pubblicazione bloccata (conflitto sulla stessa nota, grafo non valido, file fuori policy): riporta il messaggio e indica la dashboard (Pubblicazione Git → Risolvi), senza tentare altro con Git. Con «Autosync non attivo» non fare nulla.
10. **Riporta un riepilogo** all'utente: quante note create/aggiornate, relazioni e alias aggiunti, eventuali contraddizioni trovate con contenuto preesistente nel vault.
11. **Proponi il seguito.** Se il vault ha le domande aperte (es. `.graph/domande.py --json`), conta quelle che riguardano le pagine create o aggiornate (campo `pagine`) e riportale nel riepilogo per segnale. Poi chiedi all'utente come proseguire (con `AskUserQuestion` se disponibile), consigliando **lint e poi lacune, uno dopo l'altro**:
    - **Lint, poi lacune (consigliato)** — prima `obsidian-wiki-lint`, che propaga la fonte nuova, registra le contraddizioni come punti aperti, scrive le pagine per entropia e scarta le domande che il vault non sa chiudere; poi `obsidian-wiki-fill-gaps`, che porta all'utente l'elenco completo e aggiornato. Nell'ordine inverso l'utente risponderebbe a domande che il lint avrebbe chiuso da solo, e mancherebbero quelle che il lint scopre;
    - **Solo lint** — se l'utente non ha tempo per le domande ora;
    - **Solo lacune** — se la fonte era piccola e l'utente vuole chiudere subito le domande che ha aperto;
    - **Più tardi** — ricorda che senza lint le pagine nuove non producono pagine per entropia e le contraddizioni con il resto del vault restano non registrate.
    Se il vault non ha le domande aperte, proponi solo il lint.

## Note operative

- Preferisci restare coinvolti passo-passo su fonti singole importanti (l'utente legge i riassunti e guida cosa enfatizzare); per batch di più fonti a bassa supervisione, procedi e riporta un riepilogo finale.
- Per lavori corposi usa il modello di ricerca del client: Opus in Claude Code; Sol o Astra in Codex, secondo la configurazione del vault. Eventuali agenti in background seguono l'autorizzazione dell'utente e le capacità del client: questa skill non autorizza automaticamente una delega o un cambio di modello.
- Non modificare mai i raw sources.

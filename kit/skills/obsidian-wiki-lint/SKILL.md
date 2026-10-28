---
name: obsidian-wiki-lint
description: Esegue un health-check periodico ("lint") su un vault Obsidian gestito come "LLM Wiki" (pattern Karpathy) — cerca contraddizioni tra pagine, claim superati, pagine orfane, concetti senza pagina propria, cross-reference mancanti. Usa quando l'utente chiede di "lintare", "controllare la salute/coerenza", "fare un audit" del vault/wiki Obsidian.
---

# Obsidian Wiki — Lint

Implementa l'operazione **Lint** del pattern "LLM Wiki" di Andrej Karpathy
(fonte: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## Cosa cercare

- **Contraddizioni tra pagine**: stesso fatto/entità con valori diversi in note diverse (es. date, numeri, soglie) senza che nessuna nota le riconcili.
- **Claim superati (stale)**: affermazioni smentite o superate da fonti più recenti già ingerite ma non ancora propagate alle pagine vecchie.
- **Pagine orfane**: pagine senza link in entrata (nessuna altra nota le referenzia con `[[wikilink]]`).
- **Concetti/entità menzionati ma senza pagina propria**: candidati per una nuova nota atomica.
- **Cross-reference mancanti**: due pagine chiaramente collegate che non si linkano a vicenda.
- **Gap di dati**: buchi informativi colmabili con una ricerca web o chiedendo all'utente una nuova fonte da ingerire.

Se il vault ha un grafo tipizzato (es. `.graph/` con `build_graph.py` e `graph.sqlite`, vocabolario delle relazioni nello schema), controlla anche:

- **Problemi meccanici del grafo**: quelli segnalati da `python .graph/build_graph.py --check` (link non risolti, relazioni fuori vocabolario, tipi non ammessi, alias duplicati, fonti non censite).
- **Relazioni non sostenute dal testo**: una relazione nel frontmatter che la pagina non afferma più, o che contraddice il testo (es. un `referente` che il testo dice cambiato, una relazione verso qualcosa ora marcato `⚠️ da verificare`).
- **Relazioni mancanti**: il testo afferma chiaramente una relazione del vocabolario (chi è il referente, quale strumento si usa, di cosa è parte) ma il frontmatter non la dichiara. Priorità a processi e sistemi senza alcuna relazione tipizzata.
- **Alias mancanti**: sigle, nomi di codice o forme «Cognome Nome» con cui una pagina compare nelle altre pagine o nelle fonti, ma che non sono nei suoi `aliases`.

## Procedura

**Client:** in Copilot CLI leggi `.github/copilot-instructions.md`: gli hook `.github/hooks/teseo.json` aggiungono il recall al prompt del modello e registrano le letture `view` riuscite. Usa il modello attivo della sessione; i ruoli Sol/Astra/Luna riguardano solo Codex. In Codex leggi anche `AGENTS.md`. Gli hook nativi sono in `.codex/hooks.json`; se hanno già fornito il recall, usa quel contesto. Per le letture da shell usa `.graph/leggi.py` con il token di turno fornito dall'hook, così la memoria registra le pagine effettivamente aperte. In PowerShell adatta gli esempi POSIX (`/dev/null`, `&&`) alla shell disponibile, mantenendo il controllo dei codici di uscita.

0. **Sincronizza.** Se esiste `.graph/teseo_git.py` (vault collaborativo): `python .graph/teseo_git.py pre --skill lint --agente <claude|codex|copilot>` (il client che stai usando). Exit 0: prosegui e riporta all'utente quanto ricevuto (campo `message`). Exit 2: **fermati senza toccare il vault** e riporta il messaggio: serve un'azione dell'utente (modifiche non pubblicate, storie divergenti, pubblicazione da risolvere nella dashboard). Exit 3: la rete manca; prosegui e avvisa che la pubblicazione avverrà dopo. Se lo script non c'è o risponde «Autosync non attivo», salta il passo. Non eseguire mai `git` a mano nel vault.

1. Parti dall'**index** per avere la mappa completa delle pagine; se il vault ha un tool di grafo/ricerca (es. Obsidian graph view, `qmd`), usalo per individuare orfane e cluster deboli. Se c'è `.graph/build_graph.py`, lancia per primo `python .graph/build_graph.py --check`. Poi interroga `graph.sqlite` (tabelle `entities`, `relations`, `aliases`): orfane = pagine senza archi `menziona` in entrata; pagine senza relazioni tipizzate = pagine che non compaiono come `source_id` con un `type` diverso da `menziona` e `documentato_in`.
   Se il vault archivia risposte dell'autore, parti da quelle da consolidare: per ognuna verifica che le pagine indicate la riportino come `[nota-utente]` e cerca nelle altre pagine i punti che la ripetono superata o la contraddicono. Correggi le ripetizioni ovvie, riporta le contraddizioni sostanziali come al punto 3. Nei cicli della dashboard leggi `SHARED_ANSWERS.json` della copia isolata: usa soltanto gli UUID presenti nello snapshot e non accedere ai DB personali. Alla fine dichiara esplicitamente ogni UUID elaborato con `teseo_receipt.py --request <mandato> --outcome succeeded --consolida-id UUID --operazione UUID`; in alternativa `domande.py --consolida-id UUID --operazione UUID --request <mandato>`. Il servizio verifica note/fonti e prepara gli eventi nello stesso candidato; una risposta sopraggiunta resta pendente. `--consolida` massivo è disabilitato. Le risposte legacy restano nei DB originali: esportarle selettivamente dalla preview prima di elaborarle nel nuovo protocollo.
2. Scansiona sistematicamente le pagine (o l'area indicata dall'utente, se il lint è parziale) confrontando i claim tra loro.
3. **Non correggere silenziosamente** contraddizioni sostanziali (es. fatti legali, numerici, di business) senza riportarle: elencale come punti aperti/da verificare, con riferimento alle pagine coinvolte. Correggi invece refusi, link rotti e piccole inconsistenze di formato direttamente. Vale anche per il grafo: i problemi del `--check` si correggono direttamente; relazioni e alias mancanti si aggiungono se la pagina li afferma senza ambiguità; una relazione che contraddice il testo va riportata, non cancellata in silenzio. Se hai toccato frontmatter o link, rilancia `build_graph.py --check` finché non restano problemi.
4. Se lo schema del vault prevede un registro dei punti aperti (es. "Registro dei punti aperti"), aggiungilo o aggiornalo lì; altrimenti proponi di crearne uno.
5. **Entropia del vault** — solo se il vault ha gli script (es. `.graph/sintesi.py`, `.graph/domande.py`); le convenzioni del vault (es. `Wiki reference.md`) prevalgono su questo passo. Obiettivo: ogni domanda a cui il vault sa già rispondere diventa una pagina; solo quelle a cui non sa rispondere arrivano all'utente.
   - **Domande con risposta nei dati** (`python .graph/sintesi.py --json`): rispondile **tutte**, senza chiedere conferma, una alla volta e ricalcolando l'elenco dopo ogni pagina, perché una pagina ampia ne copre anche di più piccole. Ripeti finché lo script non stampa più nulla. Per ciascuna:
     1. leggi **tutte** le pagine elencate in `pagine`. Se la risposta non c'è per intero, non scrivere: `python .graph/sintesi.py --scarta "<domanda>" --motivo "<cosa manca>"`, e la domanda passa tra quelle aperte per l'utente;
     2. altrimenti scrivi la pagina nuova secondo le convenzioni del vault per le pagine generate per entropia: tag `entropia`, avviso **«Informazioni generate da entropia del vault»** in testa con la domanda (`Risponde a: «…»`), titolo come concetto e non come domanda, `[[wikilink]]` a **ogni** pagina della risposta (per un termine: il termine come titolo o alias), ogni affermazione con la fonte originale presa dalla pagina da cui viene, contraddizioni tra pagine dichiarate e non appianate, **nessun fatto nuovo**. Aggiungila all'index;
     3. `python .graph/build_graph.py --check` senza problemi, poi ricalcola le candidate.
   - Alla fine `python .graph/sintesi.py --verifica` deve dare exit 0: avviso, `riguarda`, domanda coperta, nessuna fonte estranea alle pagine linkate. Correggi le pagine generate finché non passa. Se il vault ha una misura del recall (es. `.graph/misura.py`), rilanciala: non deve peggiorare.
   - Le pagine esistenti non si toccano: se una pagina generata rivela un errore in un'altra, è un punto aperto.
   - **Domande aperte** (`python .graph/domande.py`): punti aperti, `⚠️ da verificare`, referenti mancanti, domande scartate. Sono le uniche da rivolgere all'utente: non rispondere al posto suo. Se lo script ha `--da-decidere`, elenca nel riepilogo le domande già rinviate 3 volte: vanno decise, perché il recall le mostra solo quando si parla delle loro pagine.
6. **Appendi un'entry al log** (es. `log.md`):
   `## [AAAA-MM-GG] lint | <ambito>`
7. **Pubblica.** Con `--check` pulito e il log scritto, se esiste `.graph/teseo_git.py`: `python .graph/teseo_git.py post --skill lint --agente <claude|codex|copilot>`. Exit 0: riporta l'esito (`message`: commit pubblicato, oppure nulla da pubblicare). Exit 3: la rete manca e il commit è conservato; dillo e ricorda `python .graph/teseo_git.py riprendi`. Exit 2: pubblicazione bloccata (conflitto sulla stessa nota, grafo non valido, file fuori policy): riporta il messaggio e indica la dashboard (Pubblicazione Git → Risolvi), senza tentare altro con Git. Con «Autosync non attivo» non fare nulla.
8. **Riporta un riepilogo** all'utente: numero di note, contraddizioni/nuovi punti aperti trovati, orfane, link rotti e, se c'è il grafo, esito del `--check` e relazioni/alias aggiunti o segnalati; se c'è il passo 5, le pagine generate per entropia (con le domande che coprono), l'esito di `--verifica`, e le domande aperte per l'utente, a cominciare da quelle scartate in questo lint e da quelle da decidere. Se restano domande aperte, proponi di smaltirle con la skill `obsidian-wiki-fill-gaps`, che le pone una alla volta e scrive le risposte nel vault.

## Note operative

- Per un lint corposo usa il modello di ricerca del client: Opus in Claude Code; Sol o Astra in Codex, secondo la configurazione del vault. Eventuali agenti in background seguono l'autorizzazione dell'utente e le capacità del client: questa skill non autorizza automaticamente una delega o un cambio di modello.
- Il lint è per costruzione un'operazione di lettura/segnalazione, non di riscrittura massiva: se emergono correzioni ampie, proponile e chiedi conferma prima di applicarle su larga scala. Le pagine generate per entropia del passo 5 sono l'unica scrittura ammessa senza conferma: aggiungono e non modificano, portano l'avviso, e `--verifica` le controlla.

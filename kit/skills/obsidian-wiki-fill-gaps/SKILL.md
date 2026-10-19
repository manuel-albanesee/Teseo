---
name: obsidian-wiki-fill-gaps
description: Colma le lacune di un vault Obsidian gestito come "LLM Wiki" (pattern Karpathy) facendo all'autore le domande aperte una alla volta — quelle salvate dal vault (punti aperti, ⚠️ da verificare, referenti mancanti, domande scartate dal lint) e le lacune di struttura del grafo — scrivendo ogni risposta nelle pagine come [nota-utente], archiviandola e consolidandola, finché le domande non sono smaltite. Usa quando l'utente chiede di "colmare le lacune", "rispondere alle domande aperte", "smaltire le domande del vault", "chiudere i punti aperti" o simili riferiti a un vault Obsidian esistente.
---

# Obsidian Wiki — Fill gaps

Completa le operazioni Ingest, Query e Lint del pattern "LLM Wiki" di Andrej Karpathy
(fonte: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) con la parte che solo una persona può fare:
rispondere a ciò che le fonti non dicono. Il vault sa già quali domande non sa chiudere; questa skill le pone
all'autore **una alla volta**, scrive la risposta nelle pagine e ne tiene traccia, finché l'elenco non è vuoto o
l'autore si ferma.

Non serve un ingest per le risposte: le scrive direttamente il modello nelle pagine, con la chiave di fonte che il
vault riserva alle precisazioni dell'autore (es. `[nota-utente]`). Serve invece un **lint**, che le propaga al
resto del vault e al grafo.

## Prerequisiti

- Leggi per primo lo schema del vault (es. `Wiki reference.md` o `CLAUDE.md`): chiave per le note dell'autore,
  convenzioni di frontmatter, vocabolario delle relazioni, dove stanno i punti aperti. Le convenzioni del vault
  prevalgono su questa skill.
- Se il vault ha `.graph/domande.py` con l'opzione `--json`, usalo come fonte delle domande (procedura sotto).
  Se non ce l'ha, ricava le lacune a mano: voci della sezione dei punti aperti nell'index, righe con
  `⚠️ da verificare`, sistemi e processi senza referente. In quel caso non c'è archivio né rinvio: annota le
  risposte nel log.

## Procedura

1. **Prepara l'elenco.** Dalla radice del vault:
   `python .graph/build_graph.py > /dev/null && python .graph/domande.py --json --strutturali`
   Ogni voce ha `chiave`, `segnale`, `testo`, `pagine` e `rinvii`. L'ordine è già quello giusto: prima le domande
   rinviate 3 volte (vanno decise), poi le scartate dal lint, i punti aperti, le verifiche, i referenti mancanti e
   infine le lacune di struttura (`relazioni`), raggruppate per pagina. Le domande rinviate e non scadute non ci sono.
   Di' all'autore quante sono, per segnale, e chiedi se vuole partire dall'inizio o da un'area (una pagina, un
   sistema, un segnale): in quel caso filtra l'elenco per `pagine` o `segnale`.

2. **Una domanda alla volta.** Per la prima domanda dell'elenco:
   1. leggi le pagine in `pagine` (e, per un punto aperto, la voce nell'index) per sapere cosa dice già il vault;
   2. poni la domanda in modo concreto, non come la stampa lo script: cosa dice oggi il vault, con la pagina
      citata, cosa manca, e che tipo di risposta serve (un nome, un valore, una scelta tra due fonti in
      contraddizione). Indica a che punto sei, es. «domanda 4 di 87 · verifica · [[Clone di banca]]»;
   3. ricorda in una riga le alternative: «non lo so / più avanti» (rinvio di 30 giorni), «salta», «basta così».
   Non fare più di una domanda per messaggio e non rispondere al posto dell'autore: se il vault o le fonti in
   `raw/` contengono già la risposta, dillo e proponi di chiuderla da lì, citando la fonte.

3. **Gestisci la risposta.**
   - **Risposta nel merito** → passo 4.
   - **«Non lo so», «più avanti», «devo chiedere»** → `python .graph/domande.py --rinvia "<chiave>"` e riporta
     l'esito, che indica la scadenza e il numero di rinvii. Al terzo rinvio lo script rifiuta: spiega che la domanda
     va decisa (risposta, oppure correzione della pagina perché la lacuna non sussista più).
     Le lacune `relazioni` non si archiviano e non si rinviano: si saltano.
   - **«Salta»** → passa alla successiva senza rinvio: resta aperta e tornerà.
   - **«Non vale più», «la contraddizione è superata»** → è una risposta: registrala come tale al passo 4
     (es. il punto aperto si chiude come superato, con la nota dell'autore).
   - **«Basta così»** → vai al passo 6.

4. **Scrivi la risposta nel vault.** Riporta ciò che l'autore ha detto, senza aggiungere né dedurre, citandolo con
   la chiave delle note dell'autore (es. `[nota-utente]`), aggiungendo la chiave a `fonti` e aggiornando
   `aggiornato` nel frontmatter.
   **Mai nelle pagine generate per entropia** (tag `entropia`, avviso «Informazioni generate da entropia del
   vault»): anche se la domanda le elenca in `pagine`, la risposta va nella pagina da cui quel fatto viene, cioè una
   di quelle linkate nella pagina generata. Il lint riscrive la pagina generata e `sintesi.py --verifica` la controlla.
   Per segnale:
   - `verifica`: correggi la riga e togli il marcatore `⚠️ da verificare` (o barralo con la dicitura di risoluzione
     prevista dal vault);
   - `punto`: aggiorna le pagine coinvolte e togli la voce dalla sezione dei punti aperti dell'index (o spostala
     tra i risolti, se il vault ha una sezione così). Una contraddizione tra fonti non si cancella: la pagina dice
     quale vale secondo l'autore e perché;
   - `referente`: aggiungi `referente: "[[Persona]]"` al frontmatter e una frase nel testo. Se la persona non ha una
     pagina, creala minima (`tipo: persona`, ruolo, pagine di cui è referente) e aggiungila all'index;
   - `scartata`: scrivi il dato mancante nella pagina in cui deve stare. La pagina che risponde alla domanda la
     scriverà il lint (passo 5 del lint, entropia), non tu;
   - `relazioni`: dichiara solo le relazioni che l'autore ha affermato esplicitamente, nel vocabolario del vault e
     con i tipi ammessi, e scrivile anche nel testo.
   Se la risposta contraddice un'altra pagina, non correggerla in silenzio: segnalalo all'autore e, se conferma,
   correggi anche quella.
   Poi **archivia la risposta**, con le parole dell'autore:
   `python .graph/domande.py --risposta "<chiave>" --testo "<risposta>" --pagine "<Pagina A> · <Pagina B>"`
   (anche per le lacune `relazioni`, con la chiave dell'elenco: `relazioni|<Pagina>|`). L'archivio resta anche dopo che la domanda si è
   chiusa, ed è da lì che il lint sa quali risposte consolidare.

5. **Consolida subito, in piccolo.** Dopo ogni risposta:
   1. `python .graph/build_graph.py --check`: correggi ogni problema e rilancia finché non ne restano;
   2. cerca nel vault (`grep` sul vecchio valore, sul nome corretto, sulla persona) le altre pagine che dicono la
      stessa cosa: se la ripetono sbagliata o incompleta, è il punto 4 per quelle pagine, con conferma dell'autore
      se la correzione non è ovvia;
   3. rilancia `python .graph/domande.py --json --strutturali` e verifica che la domanda non ci sia più (una
      `scartata` sparisce subito; una `relazioni` solo se hai dichiarato relazioni). Se c'è ancora, la pagina non
      è stata corretta come il calcolo si aspetta: sistemala. Spesso una risposta ne chiude anche altre: riparti
      dal nuovo elenco, non da quello vecchio;
   4. torna al passo 2.

6. **Chiudi la sessione.**
   - Appendi un'entry al log (es. `log.md`): `## [AAAA-MM-GG] lacune | <ambito>`, con le domande chiuse (chiave e
     pagina), le rinviate, le pagine toccate e create.
   Scrivi l'entry anche se la sessione si interrompe senza «basta così» (l'autore cambia argomento o chiude): il
   log è l'unico diario delle risposte oltre alla tabella `risposte`.
   - Riporta all'autore: domande chiuse, rinviate, saltate, rimaste per segnale, pagine toccate, e le pagine generate
     per entropia che ripetono un fatto ora superato (le riscrive il lint).
   - **Il lint completo va eseguito**, e dillo esplicitamente: il consolidamento del passo 5 è locale, mentre il
     lint ricalcola le pagine per entropia (le domande scartate ora risolvibili diventano pagine), verifica le
     relazioni sostenute dal testo, propaga le risposte (`python .graph/domande.py --risposte`) e alla fine le segna
     come consolidate. Proponi di lanciarlo subito con la skill `obsidian-wiki-lint`; se l'autore preferisce dopo,
     ricorda che le risposte restano «da consolidare» finché un lint non le chiude.

## Note operative

- La risposta dell'autore prevale sulle fonti quando le corregge, ma non le cancella: la pagina tiene la
  contraddizione e dice quale vale. Non inventare nomi, codici o date che l'autore non ha dato.
- Le pagine generate per entropia non si toccano nemmeno nel passo 5, quando si cercano le altre pagine con lo stesso
  fatto: se una la ripete superata, lo segnala il riepilogo del passo 6 e la riscrive il lint.
- Una sessione lunga (decine di domande) va bene: è il caso d'uso. Non lanciare questa skill in background, perché
  ogni passo aspetta l'autore.
- Le domande che arrivano dall'hook durante l'uso normale del vault sono le stesse: una risposta data lì segue gli
  stessi passi 4 e 5.

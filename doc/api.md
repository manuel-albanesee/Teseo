# Riferimento API del kit

Generato da `script/genera_api_doc.py` a partire dai docstring dei moduli: non modificare a mano.
Dopo una modifica al codice esegui `python script/genera_api_doc.py` e verifica con `--check`.
Sono elencate le funzioni e le classi pubbliche (nome senza `_` iniziale) con la prima riga del
loro docstring; il docstring del modulo è riportato per esteso perché documenta il contratto.

Per la mappa dei componenti, gli schemi SQLite e i contratti degli hook vedi
[architettura-motore.md](architettura-motore.md).

## `installa.py`

Installa il kit Teseo in un vault Obsidian, nuovo o già in uso, senza toccare le pagine.

Cosa fa:
  - .graph/          copia gli script; uno script già presente e diverso dal kit si lascia com'è,
                     salvo --aggiorna (copia di sicurezza in .graph_backup/<data-ora>/, poi sostituito).
                     I database .sqlite e modello.json non si toccano mai.
  - --client claude|codex|copilot|entrambi|tutti (predefinito tutti).
  - .claude/settings.json   aggiunge i 4 hook a quelli che ci sono già (copia di sicurezza settings.json.bak-<data-ora>);
                     un hook già registrato (stesso script) non si duplica.
  - .codex/hooks.json       hook nativi Codex (non autorizzati automaticamente), AGENTS.md e ruoli Sol/Astra/Luna.
  - .github/               istruzioni, skill e hook nativi Copilot CLI, locali al vault.
  - Wiki reference.md, index.md, log.md, CLAUDE.md/AGENTS.md, raw/, wiki/   solo se mancano.
  - skill            .claude/skills per Claude, .agents/skills per Codex, .github/skills per Copilot; nel vault per default,
                     utente solo con --skill utente;
                     una skill già presente e diversa si lascia, salvo --aggiorna.
Alla fine controlla PyYAML e FTS5, lancia build_graph.py --check e, su un vault già in uso, dice cosa adattare
(.graph/ADATTA.md, copiato insieme agli script).

Uso:
  python installa.py <vault> [--client claude|codex|copilot|entrambi|tutti] [--skill utente|vault|no] [--aggiorna] [--esempio]
  python installa.py <vault> --client codex --skill vault --solo-integrazione
  python installa.py <vault> --collabora https://github.com/<org>/<repo>.git [--crea-remote] [--branch main] [--si]
                    repository dati condiviso e autosync: crea il repository (anteprima dei file condivisi e conferma,
                    primo push) oppure, se il remoto è già popolato e <vault> è vuoto, lo clona; poi le skill fanno
                    pull all'inizio (.graph/teseo_git.py pre) e commit+push alla fine (post). Ripetibile.
  python installa.py --prova        installa in una cartella temporanea con il vault d'esempio, verifica e cancella

| Classe | Descrizione |
| --- | --- |
| `Rapporto` | — |

| Funzione | Descrizione |
| --- | --- |
| `adesso()` | — |
| `copia_file(sorgente, dest, aggiorna, backup_dir, rapporto, nome)` | Copia sorgente in dest. Uguale: niente; diverso: lasciato, o con --aggiorna salvato in backup_dir e sostituito. |
| `unisci_hook(vault, rapporto)` | Migra solo gli handler Teseo: Copilot importa anche le impostazioni Claude. |
| `clienti(client)` | — |
| `ripulisci_hook_claude_locali(vault, rapporto)` | Gli handler Teseo sono già nel file condiviso; conserva quelli dell'utente. |
| `unisci_hook_copilot(vault, rapporto)` | Configurazione nativa Copilot CLI v1; nessuna modifica al consenso utente. |
| `unisci_hook_codex(vault, rapporto)` | File nativo Codex; conserva gli hook estranei e richiede trust normale. |
| `installa_skill(modo, vault, aggiorna, rapporto, client='claude')` | — |
| `copia_esempio(vault, rapporto)` | — |
| `controlla_ambiente(rapporto, client='claude')` | — |
| `controlla_vault(vault, rapporto)` | Cosa manca a un vault già in uso perché il grafo lo veda bene. Solo lettura. |
| `collabora_clona(vault, opzioni, rapporto)` | Vault vuoto o nuovo e repository dati già popolato: lo clona al posto di crearne uno. True se clonato. |
| `collabora_imposta(vault, opzioni, clonato, rapporto)` | Repository dati e autosync: clone già fatto, aggancio a un .git esistente, oppure creazione con primo push. |
| `esegui(vault, *argomenti)` | — |
| `installa(vault, skill='vault', aggiorna=False, esempio=False, client='tutti', solo_integrazione=False, dashboard=False, collabora=None)` | collabora: None, oppure dict(url, branch, visibilita, crea_remote, si, locale) per repository dati e autosync. |
| `prova(client='tutti', dashboard=False)` | Installazione di prova con il vault d'esempio in una cartella temporanea: niente esce da lì. |
| `main()` | — |

## `kit/graph/avvisi.py`

Avvisi a inizio sessione per i vault collaborativi: aggiornamenti remoti non ancora ricevuti.

Solo `teseo_git.py avvisi` (un fetch): nessun pull e nessuna scrittura su note, grafo o stato dell'autosync.
Offline, tempo scaduto o qualunque guasto non disturbano l'avvio della sessione (si restituisce None).

| Funzione | Descrizione |
| --- | --- |
| `remoti(vault, timeout=TIMEOUT)` | Frase da mostrare all'utente se il remoto ha aggiornamenti (o storie divergenti), altrimenti None. |

## `kit/graph/backup_personal.py`

Backup consistente dei DB personali di un vault con manifest compatibile.

| Funzione | Descrizione |
| --- | --- |
| `main()` | — |

## `kit/graph/banco.py`

Materiale e controllo del banco di misura del recall: le domande che il vault deve saper trovare.

Il banco (.graph/banco.json) è una lista di {"domanda", "attese", "origine", "note"}: la domanda, le pagine che il
recall deve portare, da dove viene (sintesi, hub, isolata, atteso_ko, manuale) e perché. misura.py lo misura nella
sezione BANCO, che è informativa e non fa uscire con 1. Le domande le scrive chi usa il banco: questo script non ne crea.
  --semi      scrive .graph/banco_semi.json, il materiale da cui scrivere le domande:
              (a) le domande di sintesi.py --tutte con le pagine della risposta: dall'uscita JSON di sintesi.py,
                  o, se non si ottiene, importando la sua candidate();
              (b) i 15 hub più citati con menziona che non hanno relazioni tipizzate in entrata;
              (c) le pagine isolate nel grafo tipizzato: nessuna relazione tipizzata in entrata né in uscita.
              Per ogni pagina: id, tipo, descrizione, alias, i 10 vicini più collegati e il percorso del file.
  --verifica  controlla banco.json. ERRORE (exit 1): pagina attesa inesistente, domanda doppia, voce malformata.
              AVVISO (exit 0): la domanda usa metà delle parole del titolo di una pagina attesa, e il test sarebbe
              banale. Conta solo il titolo, cioè il nome della pagina, non gli alias; non vale per atteso_ko.

Uso:
  python .graph/banco.py --semi
  python .graph/banco.py --verifica

| Funzione | Descrizione |
| --- | --- |
| `connetti(percorso)` | — |
| `relazioni_tipizzate(db)` | (sorgente, destinazione, tipo) delle relazioni tipizzate: tutte tranne menziona e documentato_in. |
| `hub(db, pagine, tipizzate)` | Le pagine più citate con menziona (in entrata) che non hanno relazioni tipizzate in entrata. |
| `isolate(pagine, tipizzate)` | Le pagine senza relazioni tipizzate né in entrata né in uscita. |
| `indice_vicini(db, pagine)` | {pagina: {vicino: [relazioni]}} fra pagine di wiki/ (le fonti non sono vicini). «usa →»: la pagina linka il |
| `vicini_di(indice, pagina)` | I N_VICINI vicini più collegati: prima quelli con relazioni tipizzate, poi per numero di relazioni. |
| `domande_sintesi(db_path)` | Le candidate di sintesi.py --tutte: dalla sua uscita JSON; se non si ottiene, da sintesi.candidate(). |
| `scrivi_semi(db_path, db, out)` | Scrive banco_semi.json: le domande di sintesi, gli hub e le pagine isolate, con le pagine descritte. |
| `eco_del_titolo(domanda, pagina)` | True se la domanda ha almeno metà delle radici del titolo della pagina (recall.radici). |
| `verifica(db, percorso)` | Problemi di banco.json: [(livello, testo)], con livello ERRORE o AVVISO. |
| `main()` | — |

## `kit/graph/build_graph.py`

Costruisce il grafo dal vault. Deterministico: nessun LLM.

Con manifest progetto compatibile pubblica generazioni in .teseo/local/graphs/;
nei vault legacy mantiene .graph/graph.sqlite. Nessuna adozione implicita.

Nodi: ogni pagina di wiki/ (id = nome del file) e ogni chiave citata in `fonti`.
Archi:
  - proprietà del frontmatter con valori "[[link]]"  → relazione tipizzata (tipo = nome proprietà)
  - [[link]] nel corpo della pagina                  → `menziona`
  - chiavi in `fonti`                                → `documentato_in`
Alias: proprietà `aliases` del frontmatter.
Attributi d'arco: `relazioni_dettaglio` è una mappa `"[[Y]]": {confidenza: alta|media|bassa, evidenza: testo}` e vale per
l'arco `causa` della pagina verso Y, che deve essere dichiarato; finisce nella tabella `relation_attributes`.
Testo: tabella FTS5 `testo` (id pagina, titolo, corpo senza frontmatter) per il ripiego di recall.per_testo, quando
il grafo non riconosce nessuna pagina. Il corpo è intero, blocchi di codice compresi (nomi di tabelle e comandi stanno
spesso in backtick: sono ciò che si cerca). Ci sono anche le pagine `entropia`: sono riassunti, ma escluderle qui
renderebbe la scelta irreversibile senza ricostruire; le esclude il recall (il tag è in entities.tags).
Tokenizer `unicode61 remove_diacritics 2`: senza accenti e maiuscole, `_` `-` `.` separano le parole.
Le colonne `radici_titolo` e `radici_corpo` hanno lo stesso testo già ridotto a radici (ridotto: norm + stemmer.stem
parola per parola): FTS5 non può usare uno stemmer Python come tokenizer, quindi lo si applica prima, all'indicizzazione
e (in recall.py) alla query. «rilasciare» e «rilascio» hanno la stessa radice e si trovano; titolo e corpo restano
interi per gli identificatori (FattureRicevute) e le frasi esatte.
Varianti grafiche dei nomi (tabella `varianti`, generata): per ogni nome di pagina e alias la forma spezzata
(ServiceDesk → «Service Desk», Web2Print → «Web 2 Print») e, per i nomi a più parole, quella attaccata («Modulo fatture» →
«ModuloFatture»), così «service desk» trova ServiceDesk. Una variante che coincide con un nome, un alias o una variante
di un'altra pagina si scarta (varianti_nomi).
Autori (tabella `autori`): non li legge il builder, che lavora su copie senza .git; li inserisce chi lo chiama con
snapshot["autori"] (dashboard/graph_service.rebuild, da dashboard/authors.collect). Vuota se non c'è storia Git.
Vocabolario delle relazioni: tabella "## Relazioni tipizzate" in Wiki reference.md (se presente).

Uso:
  python .graph/build_graph.py            ricostruisce graph.sqlite
  python .graph/build_graph.py --check    valida e ricostruisce solo se valido (exit 1 per problemi)
Anche senza --check un grafo invalido non sostituisce quello precedente.
Una pagina con frontmatter YAML non valido non si salta: il build si ferma con un errore che ne dice il nome
(ValueError da leggi; da riga di comando «errore: ...», exit 1).

| Classe | Descrizione |
| --- | --- |
| `GraphValidationError` | — |

| Funzione | Descrizione |
| --- | --- |
| `norm(s)` | — |
| `ridotto(testo)` | Il testo normalizzato (norm) con ogni parola ridotta alla radice (stemmer.stem): «rilasciare il rilascio» → |
| `varianti_nomi(nomi)` | [(id pagina, variante)] dai nomi di pagina e dagli alias `nomi` = [(id, nome)]: forma spezzata e attaccata. |
| `bersaglio(raw)` | — |
| `valori(v)` | — |
| `leggi(path)` | — |
| `leggi_testo(testo, nome)` | Parser condiviso per file e documenti di una generazione readonly. |
| `leggi_vocabolario(ref)` | — |
| `tipo_ammesso(ammessi, tipo, tipo_altro)` | — |
| `parse_snapshot(vault)` | Legge i sorgenti in memoria senza scrivere il DB. |
| `parse_documents(documents)` | Stessi controlli del builder su documenti già acquisiti, senza filesystem. |
| `validate_snapshot(snapshot)` | Diagnostica deterministica dei dati già letti, senza pubblicazione. |
| `build_candidate(snapshot, out)` | Candidato unico nello stesso filesystem, connessione chiusa prima del return. |
| `publish_generation(candidate, out)` | Compatibilità graph.sqlite: valida SQLite e sostituisce solo a DB chiuso. |
| `costruisci(vault, out)` | — |
| `main()` | — |

## `kit/graph/candidati.py`

Candidati per migliorare il grafo: report in sola lettura, nessuna pagina viene modificata.

Tre sezioni, deterministiche (nessun LLM), per chi rivede il vault o per un agente che classifica:
  termini    parole di una domanda del banco (banco.json) presenti nel corpo della pagina attesa ma non nel suo titolo
             né nei suoi alias: un alias le porterebbe il recall a partire da quella pagina. Solo le domande con pagine
             attese mancanti o senza semi dal grafo (banco_base.json). Un bigramma vale se le sue due parole stanno nella
             stessa frase.
  alias      sigle tra parentesi («Console di Rilascio (CDR)») e forme ridotte del titolo («monitor» per DBMonitor,
             parti di CamelCase), presenti nel corpo di una pagina che linka quella del titolo. Solo le pagine con meno
             di POCHI_ALIAS alias.
  relazioni  coppie A→B con un [[wikilink]] in A e nessuna relazione tipizzata fra le due, ammissibile per i tipi secondo
             la tabella «Relazioni tipizzate» di Wiki reference. Prima le coppie verso gli hub, poi le reciproche.
Per ogni candidato: df (in quante pagine compare, da `testo`), AMBIGUO se df > SOGLIA_AMBIGUO, CONFLITTO se coincide con
il titolo o un alias di un'altra pagina, PAROLE_COMUNI se è una parola comune, e la frase del file in cui compare.
Le pagine `entropia` (riassunti generati da sintesi.py) non sono né bersagli né sorgenti.

Uso:
  python .graph/candidati.py                       report markdown in .graph/candidati.md
  python .graph/candidati.py --json                dati in .graph/candidati.json (per l'agente che classifica)
  python .graph/candidati.py --sezione alias --limite 80 --out FILE

| Funzione | Descrizione |
| --- | --- |
| `radici_di(testo)` | Radici (stemmer di recall) delle parole di un testo: le stesse delle colonne `radici_*` di `testo`. |
| `frasi(corpo)` | Span (inizio, fine) delle frasi di un corpo: una riga, spezzata dopo . ! ? e spazio. Sono sottostringhe esatte |
| `frase_in(spans, pos)` | Lo span della frase che contiene `pos`, o None. |
| `breve(testo, centro=0)` | Il testo, o una finestra di MAX_FRASE caratteri attorno a `centro`, con … dove taglia. |
| `centro_di(testo, radici_cercate)` | Posizione in `testo` della prima parola che ha una di queste radici (0 se nessuna). |
| `termini_domanda(domanda)` | {radici: chiave}: le parole piene della domanda (fuori STOPWORD_ITA, senza numeri) e le coppie di parole piene |
| `nome_prima(corpo, pos)` | Il nome che precede una parentesi in `pos`, sulla stessa riga: «La Console di Rilascio (CDR)» → «Console di |
| `forma_valida(f)` | Un alias plausibile: 1-MAX_FORMA parole, che inizia con una maiuscola o una cifra (non «vedi sotto»). |
| `forme_ridotte(titolo)` | Forme ridotte di un titolo: l'ultima parola piena (dopo aver spezzato i CamelCase: DBMonitor → «Monitor») e le |
| `leggi_json(percorso, avvisi)` | — |
| `carica(qui)` | Tutto ciò che serve alle sezioni, letto in sola lettura: il grafo (mode=ro), le pagine, il vocabolario e il banco. |
| `df_di(d, radici)` | In quante pagine del vault (titolo e corpo, da `testo`) compaiono tutte queste radici. |
| `frase_con(d, P, rad)` | (testo, centro) della prima frase del corpo di P che contiene tutte le radici `rad`, o None. |
| `frase_di(d, S, pos)` | La frase di S che contiene la posizione `pos`, o None. |
| `sezione_termini(d)` | Parole delle domande del banco presenti nel corpo della pagina attesa, non nel suo titolo né nei suoi alias. |
| `sezione_alias(d)` | Sigle tra parentesi e forme ridotte del titolo, per pagine con meno di POCHI_ALIAS alias. |
| `frase_link(d, A, B)` | (testo, centro) della prima frase di A che contiene [[B]] o [[B|…]] fuori dal codice, o None. |
| `sezione_relazioni(d)` | Coppie A→B con un menziona e nessuna relazione tipizzata fra A e B, per cui Wiki reference ammetterebbe una. |
| `bandiere(*coppie)` | Le etichette (nome, vero/falso) che valgono: « · AMBIGUO » e simili. |
| `unita(s, cands)` | Le voci del report: per gli alias una per forma (le pagine che la condividono stanno nella stessa voce), |
| `righe_termini(cands, limite)` | — |
| `righe_alias(voci)` | Una voce per forma: le pagine che la condividono sono tutte elencate. |
| `righe_relazioni(cands, hubs, limite)` | — |
| `markdown(d, r, sezioni, limite)` | — |
| `json_out(d, r, sezioni)` | — |
| `main()` | — |

## `kit/graph/chiedi_codex.py`

Query autonoma Teseo: Luna per domande puntuali, Sol/Astra per ricerca.

Il modello si sceglie PRIMA di avviare codex exec, non dall'interno di un hook.
Richiede Codex CLI autenticata. --piano verifica il routing senza chiamare modelli.

| Funzione | Descrizione |
| --- | --- |
| `comando(executable, model, output)` | — |
| `esegui(executable, model, prompt, context, timeout=240)` | — |
| `main()` | — |

## `kit/graph/claude_hook.py`

Adattatore Claude: ignora gli eventi Copilot che importano .claude/settings.json.

Copilot documenta timestamp nel proprio payload (anche nel formato compatibile
PascalCase); Claude documenta transcript_path e nessun timestamp comune.
Non si cambia il motore Claude personalizzato: lo si invoca solo nel suo runtime.

| Funzione | Descrizione |
| --- | --- |
| `main()` | — |

## `kit/graph/codex_hook.py`

Hook nativi Codex: recall condiviso con Claude e memoria isolata per turno.

Non avvia modelli e non cambia il modello della chat. Il routing eseguibile è in
chiedi_codex.py. Nessuna lettura del transcript (formato non stabile) e nessuna
deduzione di file letti dai comandi della shell: per quelli usare leggi.py.

| Funzione | Descrizione |
| --- | --- |
| `modelli()` | — |
| `sessione(evento)` | Separa sessioni e turni: non associare letture concorrenti a un altro prompt. |
| `contesto(evento, timeout=30)` | Esegue solo il recall Python già installato, mai modello_hook/claude. |
| `instrada(prompt, context, models=None)` | Riusa la decisione del router storico, non il suo esecutore Claude. |
| `registra_letture(sid, paths)` | — |
| `letture_esplicite(evento)` | Solo tool di lettura con percorso strutturato e risultato riuscito. |
| `gestisci(evento)` | — |
| `salva_sessione(evento)` | — |
| `main()` | — |

## `kit/graph/copilot_hook.py`

Hook Copilot CLI: recall nel prompt trasformato e memoria delle letture view.

userPromptSubmitted calcola soltanto il contesto; il suo output non è consumato
dalla CLI. userPromptTransformed aggiunge il recall senza alterare il testo già
trasformato dal runtime. Nessun modello esterno o transcript viene interrogato.

| Funzione | Descrizione |
| --- | --- |
| `stato_path(sid)` | — |
| `carica(path)` | — |
| `salva(path, state)` | — |
| `chiudi(state)` | — |
| `prepara(event, path)` | — |
| `gestisci(name, event)` | — |
| `main()` | — |

## `kit/graph/copilot_timing_hook.py`

Hook Copilot CLI: misura la durata dei tool e la rende visibile in timeline.

preToolUse registra l'istante di avvio di ogni chiamata; postToolUse e
postToolUseFailure calcolano i millisecondi impiegati, emettono una riga di
progresso nella timeline della CLI ({"type": "progress"}, senza toccare il
contesto del modello) e appendono il dettaglio in .graph/timing.jsonl:
istante, tool, ms, esito, argomenti e anteprima del risultato, cioè i fatti
ricavati (per sql: le righe della query). Il log resta nel vault e si può
rileggere o filtrare in seguito.

Il payload non ha un id di chiamata: la correlazione pre/post avviene per
sessionId + toolName con una pila FIFO in .graph/timing-stato/<sessione>.json.
Non blocca mai: preToolUse è fail-closed, quindi ogni errore degrada a {}
senza impedire l'esecuzione del tool.

| Funzione | Descrizione |
| --- | --- |
| `stato_path(sid: object)` | — |
| `carica(path: Path)` | — |
| `salva(path: Path, stato: dict)` | — |
| `testo(valore: object, limite: int)` | — |
| `registra_avvio(evento: dict)` | — |
| `registra_fine(evento: dict, ok: bool)` | — |
| `gestisci(nome: str, evento: dict)` | — |
| `main()` | — |

## `kit/graph/domande.py`

Domande aperte del vault: quelle a cui il vault non sa rispondere, e che vanno rivolte all'autore.

Le domande a cui il vault risponde già, mettendo insieme più pagine, non sono qui: le elenca sintesi.py e
diventano pagine di sintesi durante il lint. Qui restano quattro segnali, calcolati senza LLM:
  punto      voce di "## Punti aperti nel vault" in index.md che linka la pagina
  verifica   riga della pagina con il marcatore ⚠️ "da verificare" ancora applicato
  referente  sistema, processo o progetto senza relazione `referente` e non parte di altro
             (se il testo lo dice, il lint aggiunge la relazione e la domanda sparisce)
  scartata   domanda di sintesi.py che il lint non ha potuto chiudere con i dati del vault (`--scarta`)
Le pagine generate per entropia (tag `entropia`) non contano: ripetono i ⚠️ delle pagine da cui vengono.

recall_hook.py ne mette al massimo MAX nel contesto, solo per le pagine riconosciute nel prompt,
e mai due volte la stessa nella stessa sessione (tabella `poste` in domande.sqlite).
Con GRAFO_SENZA_DOMANDE=1 (lo imposta misura.py) non si calcolano.

Ogni domanda rilevata è archiviata nella tabella `aperte` di domande.sqlite, con stato e date. Il calcolo dalle
pagine comanda: una domanda che il calcolo non rileva più passa a `chiusa` (non sparisce), una che riappare si
riapre. La chiave è segnale + pagina + prime parole del testo, non il testo intero: ritoccare la riga non la
trasforma in una domanda nuova. Punti aperti e domande scartate non hanno la pagina nella chiave: sono una domanda
sola anche quando linkano più pagine, e un rinvio le nasconde ovunque. Un rinvio (--rinvia) nasconde la domanda per
GIORNI_RINVIO giorni; dopo MAX_RINVII rinvii non si rinvia più, la domanda esce con l'avviso «rinviata N volte» e il
lint la riporta all'autore (--da-decidere), perché il recall la mostrerebbe solo parlando delle sue pagine.

Uso:
  python .graph/domande.py                 tutte le domande aperte del vault, per segnale
  python .graph/domande.py "Rilascio"        le domande per le pagine riconosciute nel testo
  python .graph/domande.py --stato         tutte le domande archiviate, per stato (aperta, rinviata, chiusa)
  python .graph/domande.py --rinvia TESTO  rinvia di 30 giorni la domanda con chiave TESTO, o l'unica che lo contiene
  python .graph/domande.py --da-decidere   le domande rinviate 3 volte, da portare all'autore nel lint
  python .graph/domande.py --json [--strutturali]   le domande aperte in JSON, per la skill delle lacune
  python .graph/domande.py --risposta CHIAVE --testo "..." [--pagine "A · B"]   archivia la risposta dell'autore
  python .graph/domande.py --risposte      risposte legacy pendenti; export selettivo prima del consolidamento UUID

| Funzione | Descrizione |
| --- | --- |
| `pulisci(testo, lunghezza=170)` | — |
| `punti_aperti(vault)` | — |
| `pagine_fonte(vault)` | Le pagine di wiki/ tranne quelle generate per entropia, che non sono fonte di domande. |
| `termini(db, vault)` | Identificatori senza pagina né alias, citati in 3+ pagine di 3+ aree: [(termini, pagine)]. |
| `apri(path=QUI / 'domande.sqlite')` | — |
| `stabile(testo)` | Le prime parole del testo, senza maiuscole, accenti e punteggiatura. |
| `rileva(db, vault)` | {pagina: [(segnale, testo, chiave)]}, in ordine di segnale. La chiave è segnale|pagina|parte stabile, |
| `calcola(db, vault)` | {pagina: [(segnale, testo)]}, in ordine di segnale. |
| `oggi()` | — |
| `sincronizza(archivio, rilevate)` | Allinea la tabella `aperte` a ciò che il calcolo rileva ora. Il calcolo comanda. |
| `rinvia(archivio, cerca)` | Rinvia di GIORNI_RINVIO giorni la domanda non chiusa con chiave `cerca`, o l'unica che lo contiene |
| `vicine(db, pagine)` | Le pagine del prompt, poi i vicini per relazione tipizzata, poi le altre parti dello stesso tutto. |
| `per_pagine(db, vault, pagine, sessione='', archivio=None, massimo=MAX)` | Al più `massimo` domande, a turno sulle pagine (vedi vicine), saltando quelle già poste nella sessione. |
| `formatta(scelte)` | — |
| `strutturali(db, vault)` | Lacune di struttura, non archiviate in `aperte` né proposte dal recall: sistemi, processi e progetti |
| `da_porre(db, vault, archivio)` | Le domande aperte e non rinviate, nell'ordine in cui la skill delle lacune le pone: prima quelle da |
| `registra(archivio, chiave, risposta, pagine='', domanda=None)` | Archivia la risposta dell'autore (tabella `risposte`): resta anche dopo che la domanda si è chiusa. |
| `da_decidere(archivio)` | Le domande non chiuse già rinviate MAX_RINVII volte: il lint le porta all'autore, perché il recall |
| `main()` | — |

## `kit/graph/graph_db.py`

Apertura readonly e revisione fissata per connessione, anche nel kit installato.

| Classe | Descrizione |
| --- | --- |
| `GraphDatabaseError` | — |
| `GraphReference` | — |
| `GraphConnection` | Attributi content_revision e graph_generation fissati all'apertura. |

| Funzione | Descrizione |
| --- | --- |
| `graph_reference(path)` | — |
| `resolve_graph(path)` | — |
| `connect_graph(path, reference=None)` | — |

## `kit/graph/learn_hook.py`

Hook PostToolUse (Read) e Stop: collega alla domanda in sospeso le pagine di wiki/ lette, e a fine turno le archivia.

La domanda la mette in sospeso recall_hook.py quando il grafo non la riconosce; il ciclo è descritto in memoria.py.
Log dei turni (memoria.py): ogni Read di una pagina di wiki/ è collegata anche all'ultimo turno della sessione
(tabella letture_turno), sempre, con o senza domanda in sospeso: `memoria.py --turni` confronta così le pagine iniettate
da recall_hook.py con quelle che il modello ha poi aperto. Un errore nel log non fa fallire l'annotazione per la memoria.
Registrato in .claude/settings.json; si prova a mano con:
  echo '{"hook_event_name": "PostToolUse", "session_id": "prova", "tool_input": {"file_path": "wiki/Rilascio in produzione.md"}}' | python .graph/learn_hook.py
  echo '{"hook_event_name": "Stop", "session_id": "prova"}' | python .graph/learn_hook.py

| Funzione | Descrizione |
| --- | --- |
| `pagina_wiki(vault, file_path)` | — |
| `main()` | — |

## `kit/graph/leggi.py`

Legge pagine wiki da shell e registra solo letture riuscite nel turno Codex.

Uso: python .graph/leggi.py --turno <token dall'hook> "wiki/Pagina.md"
Senza --turno legge soltanto. Non esegue il testo delle pagine.

| Funzione | Descrizione |
| --- | --- |
| `leggi(paths, token=None)` | — |
| `main()` | — |

## `kit/graph/memoria.py`

Memoria delle domande che il grafo non riconosce, e delle pagine lette per rispondere.

Il grafo si ricostruisce da zero dalla wiki, quindi quello che si impara sta in un file a parte, memoria.sqlite.
Ciclo, legato al session_id che Claude Code passa a ogni hook:
  UserPromptSubmit  nessun punto di partenza nel grafo e il prompt è una domanda sul contenuto → resta in sospeso
                    (recall_hook.py). Non lo sono (e_domanda): comandi /..., richieste di modifica (SCRITTURA di recall.py:
                    ingerisci, lint, aggiorna...; ma «come si aggiorna X?» è una domanda), domande sul sistema (META), conferme e conversazione (CONFERME):
                    leggono pagine, ma per eseguire un lavoro, e insegnerebbero associazioni sbagliate
  PostToolUse Read  ogni pagina di wiki/ letta mentre una domanda è in sospeso le viene collegata (learn_hook.py)
  Stop              domanda e pagine lette passano nell'archivio; senza letture la domanda si scarta
Conta solo Read, non Grep: Grep restituisce decine di file, le pagine aperte sono quelle che servivano.
A una domanda simile a una già vista (almeno 2 radici in comune, Dice ≥ 0.5) le pagine collegate
diventano punti di partenza del recall. Nel grafo non entra nulla da sé: le domande ricorrenti si elencano
qui sotto e, se l'associazione è giusta, si promuovono a mano ad `aliases` della pagina.

Log locale dei turni (non insegna nulla al recall: serve a misurarlo sull'uso vero). A OGNI prompt recall_hook.py scrive
una riga in `turni` (anche senza semi, salvo GRAFO_SENZA_MEMORIA=1): il testo scritto (tagliato a MAX_TESTO), i semi con la
loro origine (nome: citata per nome o alias; titolo: parole del titolo vicine; memoria: letta per domande simili;
testo: ripiego FTS), le pagine iniettate nei fatti e il routing se disponibile (oggi NULL). learn_hook.py collega ogni
Read di una pagina di wiki/ all'ultimo turno della sessione (`letture_turno`), sempre, anche senza domanda in sospeso:
il confronto fra pagine iniettate e pagine lette dice quando il recall ha portato pagine inutili («iniettata non letta»)
o ne ha mancate («letta non iniettata»: il modello ha dovuto cercare da sé). I turni più vecchi di GIORNI_TURNI giorni
si cancellano a ogni apri(). Il log è un di più: un errore nel log non rompe mai gli hook.

Uso:
  python .graph/memoria.py              domande apprese, con le pagine lette e quante volte
  python .graph/memoria.py "domanda"    pagine che la memoria porterebbe a questa domanda
  python .graph/memoria.py --turni [N]  ultimi N turni (10 se omesso): semi con origine, pagine iniettate, pagine lette;
                                        marca «iniettata non letta» e «letta non iniettata»
  python .graph/memoria.py --dimentica "testo"   toglie una domanda appresa e le sue pagine (testo esatto o sottostringa unica)

| Funzione | Descrizione |
| --- | --- |
| `apri(path)` | — |
| `adesso()` | — |
| `e_domanda(testo)` | True se il prompt sembra una domanda sul contenuto: non un comando /..., una domanda sul sistema (META), |
| `e_domanda_senza_conferma(n, scritto_strip)` | Il vaglio di e_domanda su un testo normalizzato senza l'apertura di conferma. |
| `sospendi(mem, sessione, domanda)` | Mette la domanda in attesa delle letture, se è una domanda (e_domanda); chiude prima quella rimasta aperta. |
| `annota(mem, sessione, pagina)` | — |
| `chiudi(mem, sessione)` | Archivia la domanda in sospeso con le pagine lette; restituisce le pagine (vuoto = scartata). |
| `registra_turno(mem, sessione, testo, semi, iniettate, routing=None)` | Scrive una riga nel log dei turni; `semi` = [(pagina, origine)], `iniettate` = [pagina]. Restituisce l'id. |
| `leggi_turno(mem, sessione, pagina)` | Collega la pagina letta all'ultimo turno della sessione (sempre: non serve una domanda in sospeso). |
| `turni_recenti(mem, n)` | Gli ultimi n turni, dal più vecchio: [(id, sessione, quando, testo, semi, iniettate, routing, lette)]. |
| `ricorda(mem, domanda, esistenti)` | Pagine lette per domande simili: [(pagina, domanda simile)], solo pagine ancora presenti nel grafo. |
| `dimentica(mem, testo)` | Toglie dall'archivio una domanda e le sue pagine lette; corrispondenza esatta, o unica per sottostringa |
| `main()` | — |

## `kit/graph/misura.py`

Misura il grafo su domande reali fatte al vault: il recall porta le pagine giuste, e con quanto contesto?

Senza opzioni misura solo recall.py: deterministico, in meno di un secondo, da rilanciare dopo ogni modifica.
Con --modello lancia `claude -p` due volte per domanda nel vault, a parità di modello e senza thinking:
  ricerca  il modello cerca da sé con Read/Grep/Glob (Bash e skill disattivati, quindi niente recall.py)
  grafo    stesse regole, più l'hook recall_hook.py che inietta i fatti prima del turno
Con --hook, in più, ogni domanda passa dal percorso di modello_hook.py: contesto come recall_hook.py, pagine
pre-caricate, REGOLE_HAIKU, stessi argomenti e stesso input di chiedi_a_haiku, con il modello di --modello
(sola condizione «hook»). Con --hook-da <cartella> si usano invece REGOLE_HAIKU di quella copia di modello_hook.py
(es. un backup di .graph_backup) e niente pagine pre-caricate: la versione precedente, per il confronto.
Sempre, dopo la tabella del recall, i casi negativi (NEGATIVI): per ognuno i semi che non devono comparire
(testo incollato, parole comuni che sono nomi di pagina, titoli con parole sparse); exit 1 se ce n'è qualcuno
o se manca un seme atteso: un seme spurio inietta fatti e domande aperte fuori tema.
Poi il ripiego sul testo delle pagine (TESTO), misurato come lo usa recall_hook.py (recall_hook.ripiego_testo: niente
semi dal grafo, memoria.e_domanda, poi recall.per_testo_a_cascata; la memoria qui non c'è): prompt che il grafo non riconosce per
nome ma le cui parole, identificatori o date sono nel corpo delle pagine, con le pagine attese tra quelle trovate; e
prompt di conversazione, di lavoro, sul sistema o generici che devono dare 0 pagine. Controlla anche che le DOMANDE abbiano semi per nome (il ripiego non scatta); exit 1 se un caso fallisce.
Infine la memoria (MEMORIA, memoria.sospendi su un db in memoria): le domande sul contenuto restano in sospeso, i
comandi, le richieste di modifica e la conversazione no; exit 1 se un caso è sbagliato.
Alla fine ATTESI_FALLITI: difetti noti del recall (morfologia derivativa, sinonimi, varianti grafiche, parola rara
isolata) trasformati in casi che oggi falliscono. Si stampano «atteso KO» e non fanno uscire con 1; quando un caso
comincia a passare compare «ORA OK» (va spostato nella lista normale: DOMANDE, TESTO o NEGATIVI), così chi migliora
il recall vede il miglioramento senza rompere la CI. L'exit resta 0 finché i casi normali passano.
Poi il banco (BANCO, .graph/banco.json: le domande le scrive chi lo usa, banco.py --semi dà il materiale e
banco.py --verifica lo controlla): domande con le pagine che il vault deve portare, scritte senza le parole dei titoli.
Si misurano con lo stesso calcolo di misura_recall; senza semi per nome, con il ripiego sul testo, segnalato «T».
Una riga per domanda e il riepilogo: pagine attese portate, domande complete, token medi, domande senza semi.
È informativo: non fa uscire con 1. Senza banco.json la sezione non si stampa.
--banco-salva FILE scrive i risultati per domanda; --banco-confronta FILE li confronta con quel salvataggio: per
domanda MIGLIORATA o PEGGIORATA (pagine attese, e rumore, cioè pagine portate ma non attese), con la variazione dei
token, poi il saldo; --solo-banco stampa solo il banco.
Con --routing non si chiama nessun modello: per ogni domanda di DOMANDE (destinazione in ATTESE) e di ROUTING
si confronta la destinazione attesa con quella di modello_hook.instradamento, con una sessione Opus simulata.
La correttezza automatica è solo un'approssimazione (regex sulla risposta): le risposte, salvate in --out, vanno rilette.

Uso:
  python .graph/misura.py
  python .graph/misura.py --modello claude-haiku-4-5-20251001 --out <cartella> --giri 3
  python .graph/misura.py --hook --modello haiku --out <cartella> --domande 2,5 [--hook-da .graph_backup/<data>]
  python .graph/misura.py --solo-banco --banco-salva <file>
  python .graph/misura.py --solo-banco --banco-confronta <file>

| Funzione | Descrizione |
| --- | --- |
| `misura_recall(db)` | — |
| `misura_negativi(db)` | Semi spuri dei casi di NEGATIVI (e semi attesi mancanti); restituisce quanti casi hanno un difetto. |
| `misura_testo(db)` | Il ripiego sul testo: pagine attese trovate, 0 pagine sui prompt di conversazione, e DOMANDE con semi per nome. |
| `misura_attesi_falliti(db)` | Stato di ATTESI_FALLITI: «atteso KO» finché il caso fallisce, «ORA OK» quando passa. Non incide sull'exit. |
| `esito_banco(db, info, domanda)` | Le pagine che il recall porta per una domanda del banco, come misura_recall. Senza semi per nome, il ripiego |
| `carica_banco(percorso)` | Le voci di banco.json. None se il file non c'è (la sezione non si stampa) o non è un banco valido. |
| `misura_banco(db, percorso)` | Il banco: per domanda le pagine attese che il recall porta, token e tempo, poi il riepilogo. Informativo: non |
| `carica_salvataggio(percorso)` | I risultati di un --banco-salva. None se il file non si legge o non è un salvataggio del banco. |
| `confronta_banco(esiti, prima)` | Per domanda rispetto a un salvataggio di --banco-salva. MIGLIORATA: più pagine attese portate, o a parità meno |
| `salva_banco(esiti, percorso)` | — |
| `usa_banco(db, args, prima)` | La sezione del banco con le sue opzioni. Il confronto precede il salvataggio, così può essere lo stesso file. |
| `misura_memoria()` | Quali prompt la memoria mette in sospeso, su un db in memoria (mai memoria.sqlite); restituisce i casi errati. |
| `esegui(claude, vault, modello, condizione, domanda, hook)` | — |
| `misura_modello(vault, modello, out, paralleli, giri, scelte)` | — |
| `misura_routing()` | Tabella del routing senza chiamare modelli; esce con 1 se qualche caso è KO. |
| `carica_regole(cartella)` | REGOLE_HAIKU di un modello_hook.py in un'altra cartella (un backup), senza eseguirne l'hook. |
| `esegui_hook(claude, vault, db_path, modello, domanda, regole, precarica)` | Una domanda come la gestisce modello_hook.py: contesto del grafo, pagine pre-caricate, Haiku (o altro modello). |
| `misura_hook(vault, db_path, modello, out, paralleli, giri, scelte, hook_da)` | — |
| `main()` | — |

## `kit/graph/modello_hook.py`

Hook SessionStart e UserPromptSubmit: graph research con Opus, e risposta di Haiku quando il grafo dà il contesto.

Modello attivo: agli hook Claude Code non lo passa, quindi si ricostruisce. Vince il segnale più recente fra
  - SessionStart: campo `model` dell'evento se c'è, altrimenti `--model` nella riga di comando di claude (CLAUDE_PID),
    altrimenti ANTHROPIC_MODEL, altrimenti `model` in .claude/settings.local.json, .claude/settings.json, ~/.claude/settings.json;
    dopo /clear e /compact il modello resta quello del processo, già annotato;
  - transcript: `/model` («Set model to `Opus 5.5`», scritto appena dato il comando), il modello dei turni passati.
Se non è di classe Opus (opusplan non conta: usa Opus solo in plan mode) avvisa una volta per sessione e modello;
se lo è, a ogni SessionStart (anche dopo /clear e /compact) ricorda il prefisso @opus (AVVISO_OPUS).

Con Opus, a ogni prompt chiama recall_hook.py (che quindi non va registrato a parte; se non risponde in
TIMEOUT_RECALL secondi o fallisce, lo dichiara con un systemMessage e un avviso al modello: guasto_recall)
e, se il grafo riconosce delle pagine, passa domanda, contesto e conversazione recente all'ultimo Haiku
(alias `haiku`) in un `claude -p` che può solo leggere il vault; la risposta si mostra bloccando il prompt, così Opus non viene chiamato.
Prima di chiamare Haiku l'hook gli pre-carica nel prompt il testo delle pagine seme (punti_di_partenza) e, per ogni
seme, delle sue pagine di sintesi (tag `sintesi` e parte_di verso il seme: «Funzionamento del Gestionale» per
Gestionale), perché un hub da solo non dice «come funziona». Tetto di MAX_PAGINE_PRECARICATE caratteri in tutto,
prima i semi poi le sintesi; la pagina che sfora si tronca con «[…]». Le pagine `entropia` non nominate non si caricano.
Risponde comunque Opus, con il contesto di recall_hook.py, se:
  - il recall è fallito (tempo scaduto, errore, output non valido) o il grafo non è stato ricostruito: il contesto
    porta MARCA_GUASTO, l'utente vede il motivo nel messaggio e il modello riceve l'avviso a cercare nelle pagine;
  - il grafo non riconosce nessuna pagina (serve la ricerca nei file, e la memoria deve registrare le pagine lette);
    il contesto è allora il solo AVVISO_NESSUNA_PAGINA di recall_hook.py, che Opus riceve (anche con @opus o dopo
    risposte di Haiku da consegnare) e che lo manda a cercare in wiki/, oppure i fatti delle pagine trovate nel
    testo (recall.per_testo): aggancio debole, quindi Opus anche lì;
    il routing guarda solo il testo scritto dall'utente, non i blocchi <pasted_content> incollati;
  - la richiesta modifica il vault (ingerisci, lint, salva, aggiorna...) o è un comando /...;
  - la domanda riguarda il sistema e non il vault (haiku, opus, claude, hook, prompt, routing);
  - il prompt inizia con @opus;
  - la domanda è ampia (cosa fa, come funziona, spiega, confronta...: regex AMPIA), è di elenco (elenca, lista,
    tutti i, quali, quanti, ci sono, dammi i...: regex ELENCO; «quale» singolare e «tutto» restano puntuali), oppure
    nomina soltanto un hub (una pagina con almeno SOGLIA_HUB pagine parte_di, come il sistema principale del vault): Haiku sulle
    domande ampie e di elenco perde pezzi delle pagine, e il motivo compare nel messaggio all'utente. Si guarda solo il testo scritto dall'utente;
  - Haiku va in errore, supera TIMEOUT_HAIKU secondi o risponde PASSA_A_OPUS (domanda fuori dal vault
    o risposta non trovata nelle pagine).
Le risposte di Haiku non entrano nella cronologia: si passano a Opus nel contesto del primo turno successivo.
Stato per sessione in modello.json. Il `claude -p` di Haiku non carica gli hook del vault (--setting-sources user)
e ha GRAFO_HAIKU=1, con cui questo hook non fa nulla.

Registrato in .claude/settings.json; si prova a mano con:
  echo '{"hook_event_name": "UserPromptSubmit", "session_id": "prova", "prompt": "il file delle fatture non arriva, a chi scrivo?"}' | python .graph/modello_hook.py

| Funzione | Descrizione |
| --- | --- |
| `adesso()` | — |
| `carica_stato()` | — |
| `salva_stato(stato)` | — |
| `classe(modello)` | 'opus', 'altro' o None se non si sa (nessun modello, o 'default' che dipende dall'account). |
| `da_riga_di_comando()` | — |
| `da_impostazioni()` | — |
| `leggi_transcript(path)` | — |
| `testo(record)` | — |
| `dal_transcript(righe)` | (quando, modello) dell'ultimo segnale nel transcript, o None. |
| `modello_attivo(sessione, righe)` | — |
| `taglia(t, n=MAX_TESTO)` | — |
| `scambi_recenti(righe, risposte_haiku)` | Ultimi scambi utente/assistente (Opus dal transcript, Haiku da modello.json), in ordine di tempo. |
| `guasto_recall(motivo, stderr=b'')` | Output al posto di quello di recall_hook.py quando non si riesce a ottenerlo: avvisa utente e modello. |
| `richiama(evento)` | Output JSON di recall_hook.py per lo stesso evento. |
| `riconosciute(prompt)` | — |
| `pagine_precaricate(domanda, vault=VAULT, budget=MAX_PAGINE_PRECARICATE)` | Blocco di testo con le pagine seme e le loro sintesi, già lette, o "" se non ce ne sono. |
| `input_haiku(prompt, contesto, scambi, pagine='')` | Il testo che si passa a Haiku su stdin; lo usa anche misura.py --hook. |
| `argomenti_haiku(claude, modello=HAIKU, regole=REGOLE_HAIKU)` | Riga di comando del `claude -p` che risponde: sola lettura, senza hook del vault; la usa anche misura.py. |
| `hub_fra(semi)` | I semi con almeno SOGLIA_HUB pagine parte_di verso di sé. |
| `solo_nomi(domanda, semi)` | True se tolti i nomi (e gli alias) dei semi restano solo stopword: «Gestionale?», «Gestionale». |
| `instradamento(prompt, modello, contesto)` | (destinazione, motivo): "haiku" o "opus" e perché; il motivo è in italiano e per Opus è breve. |
| `chiedi_a_haiku(prompt, contesto, scambi)` | — |
| `avviso(sessione, modello)` | Testo dell'avviso se il modello non è Opus e per questo modello non si è già avvisato. |
| `inizio_sessione(evento, stato, sessione, processo)` | — |
| `prompt_utente(evento, stato, sessione, processo)` | — |
| `main()` | — |

## `kit/graph/ontology.py`

Ontologia Markdown lossless: parser e proposte pure, nessun accesso al filesystem.

Grammatica volutamente limitata: sezioni ATX h2, una tabella contigua per sezione,
2 colonne per i tipi e 3/5 per le relazioni. Contenuto ambiguo resta manuale.
Gli offset sono byte UTF-8; il serializer sostituisce solo tabelle riconosciute.

| Classe | Descrizione |
| --- | --- |
| `OntologyError` | — |
| `Span` | — |
| `Issue` | — |
| `TypeDef` | — |
| `Relation` | — |
| `Ontology` | — |
| `CatalogProposal` | — |

| Funzione | Descrizione |
| --- | --- |
| `validate(types, relations)` | Validazione del modello; impatto sulle pagine demandato al builder/preview. |
| `parse(source)` | — |
| `serialize(document, *, types=None, relations=None)` | — |
| `propose_type_catalog(document, observed_types=())` | — |

## `kit/graph/recall.py`

Richiama dal grafo i fatti legati a una domanda, da mettere nel contesto prima di rispondere.

Punti di partenza: nomi di pagina e alias citati nella domanda (senza maiuscole e accenti,
vince il nome più lungo: "Portale clienti nuovo" batte "Portale clienti"), più le loro varianti grafiche generate da
build_graph (tabella `varianti`: «Service Desk» e «service desk» trovano ServiceDesk, «modulofatture» il Modulo fatture);
poi le pagine di cui la domanda contiene le parole del titolo (o di un alias a più parole), confrontate per radice
(stemmer.py, Snowball italiano: flesse e derivate, «rilasciare in produzione» → Rilascio in produzione) e
vicine fra loro (finestra di len(titolo)+FINESTRA_EXTRA parole): "caricamento fallito" → Recupero di un caricamento fallito.
Cammino: 1° passo su tutti gli archi; dal 2° solo lungo relazioni tipizzate, solo da nodi
raggiunti con una relazione tipizzata e nello stesso verso, perché i link generici portano sempre
agli hub (le pagine del sistema principale) e i "fratelli" (altre pagine che puntano allo stesso nodo) sono rumore.
In avanti fino al 3° passo, perché le catene si stringono verso prerequisiti e referenti
(Rilascio in produzione → Console di rilascio → Incident settimanale → Anna Rossi); a ritroso
fino al 2°, perché si allargano (le parti delle parti).
Potatura: 3 o più fratelli diventano un fatto solo (le 10 pagine parte_di uno stesso sistema), così un hub
non riempie i posti e le catene lunghe restano dentro.
Limiti per tipo, non un top-k unico: tutte le relazioni tipizzate (tetto di sicurezza MAX_TIPIZZATE) e al più
MAX_MENZIONA link generici (`menziona`), i migliori per punteggio; i `menziona` pesano molto meno e un top-k unico
tagliava anche relazioni tipizzate (le catene) per far posto a loro o a hub. Quello che resta fuori è contato
(omessi) e formatta() lo dichiara in coda, così il modello sa che il contesto è parziale e può cercare.
Le pagine generate per entropia (tag `entropia`, sintesi.py) sono punti di partenza solo se nominate:
raggiunte dal cammino contano come un link generico e non proseguono catene.
Solo il testo scritto dall'utente conta (scritto()): i blocchi <pasted_content> incollati e i rapporti dei sub agent
(<agent-message>, che Claude Code consegna come prompt) nominano pagine senza che la
domanda le riguardi, e sono tolti prima di cercare i punti di partenza (e dal routing, dalla memoria, dalle domande aperte).
I nomi che sono anche parole comuni (PAROLE_COMUNI, es. Portale) valgono solo scritti con la maiuscola.
Nessun punto di partenza → nessun output. L'hook aggiunge come punti di partenza anche le pagine
lette in passato per domande simili (memoria.py); da riga di comando no.
Ripiego sul testo (per_testo, usato dall'hook solo se né il grafo né la memoria danno punti di partenza): ricerca
FTS5 nel corpo delle pagine (tabella `testo` di build_graph.py), per parole significative ridotte a radice con lo
stemmer (le colonne `radici_titolo` e `radici_corpo` hanno il testo già ridotto: FTS5 non può usare uno stemmer Python
come tokenizer; tollera flessioni e derivazioni, «rilasciare» trova «rilascio»; la radice è un termine intero, non un
prefisso) e per date in linguaggio naturale («10 settembre», «31/08»), che sono mappate alle fonti
`call-AAAA-MM-GG*` e quindi alle pagine che le citano. Al più MAX_TESTO pagine, sopra soglia: un aggancio debole,
che l'hook dichiara come tale. Le pagine `entropia` non si cercano nel testo (riassumono altre pagine).
Le parole comuni presenti in più di SOGLIA_FREQUENTE delle pagine (stesso, query, error: la frequenza viene
dall'indice FTS stesso, frequenti_testo) non distinguono nulla: non contano come «prese» né per il minimo e non vanno
nella query; con meno di due parole comuni utili e nessun identificatore o data il ripiego non dà pagine.
Una parola presente in al più SOGLIA_RARA pagine, di almeno MIN_RARA lettere e dall'aspetto di un nome (sembra_nome:
finisce per consonante o ha j k w x y; «fatturix» sì, «riunione» e «lunedì» no) conta come identificatore: basta da sola.
Le sole parole comuni (nessun identificatore) devono anche stare vicine nella pagina: almeno la metà di quelle cercate
(il minimo) in una finestra di FINESTRA_TESTO parole. Parole rare ma sparse in pagine lunghe («il collega mi ha chiesto
il report settimanale»: chiesto e settimanale a 58 parole in una pagina, a 144 in un'altra) non dicono che la pagina
parli di quello; le pagine giuste le hanno a 4-16 parole.
Se il primo giro non trova nulla, un secondo giro (per_testo_a_cascata) allarga finestra e soglia
(FINESTRA_TESTO_LARGA, SOGLIA_FREQUENTE_LARGA) e porta al più MAX_TESTO_LARGO pagine: le domande parafrasate hanno le
parole un po' più lontane o un po' più frequenti di quelle che nominano la pagina.

Uso: python .graph/recall.py "il file delle fatture non arriva, a chi scrivo?" [--menziona 10] [--tipizzate 30] [--json]

| Funzione | Descrizione |
| --- | --- |
| `scritto(prompt)` | Il prompt senza i blocchi incollati: quello che l'utente ha scritto davvero. |
| `radice(parola)` | Radice di una parola già normalizzata (norm): lo stemmer Snowball italiano (stemmer.py), non più le sole vocali |
| `radici(testo)` | — |
| `per_titolo(db, domanda, semi)` | Pagine con almeno due parole del titolo vicine nella domanda, che pesano almeno metà del titolo. |
| `punti_di_partenza(db, domanda)` | — |
| `date_nel_testo(testo)` | [(giorno, mese, anno o None)] delle date scritte come «10 settembre», «31 agosto 2026», «10/09». |
| `pagine_per_data(db, testo, tolte)` | Pagine che citano in `fonti` una chiamata (call-AAAA-MM-GG*) di una data scritta nel testo, prima quelle |
| `termini_testo(testo)` | [Termine(frase FTS5, chiave di verifica, forte, radice, parola)] dal testo, senza date. |
| `sembra_nome(parola)` | True se una parola (norm) non ha la forma di una parola italiana comune: finisce per consonante o ha una lettera |
| `frequenze_testo(db, termini, escluse)` | (totale, {chiave: pagine}) delle parole comuni di `termini`: in quante pagine non `escluse` (rowid di `testo`) |
| `frequenti_testo(db, termini, escluse, soglia=None)` | Chiavi (t.chiave) delle parole comuni di `termini` presenti in più di `soglia` (di norma SOGLIA_FREQUENTE) delle |
| `rare_testo(db, termini, escluse)` | Chiavi delle parole comuni di `termini` che valgono da identificatore: in al più SOGLIA_RARA pagine non `escluse` |
| `vicine(pagina, chiavi, minimo, finestra=None)` | True se almeno `minimo` chiavi distinte (forma di termini_testo: `" radice "`, parola intera) stanno in |
| `per_testo(db, domanda, n=MAX_TESTO, tolte=(), finestra=None, soglia_frequente=None)` | Ripiego quando il grafo non riconosce nulla: [pagine] trovate nel corpo (FTS5 `testo`), al più n. |
| `per_testo_a_cascata(db, domanda, tolte=())` | Il ripiego sul testo in due giri: per_testo; se non trova nulla, un secondo giro con FINESTRA_TESTO_LARGA e |
| `archi(db, nodi, solo_tipizzate, colonne=('source_id', 'target_id'))` | — |
| `richiama(db, domanda, max_tipizzate=MAX_TIPIZZATE, max_menziona=MAX_MENZIONA, extra=())` | (semi, fatti, omessi): omessi = {"tipizzate": n, "menziona": n} sono i fatti fuori dai limiti. |
| `nodi(fatto)` | — |
| `formatta(semi, fatti, info, omessi=None)` | — |
| `main()` | — |

## `kit/graph/recall_hook.py`

Hook UserPromptSubmit: mette nel contesto i fatti del grafo legati al prompt, prima che il modello parta.

Se una pagina di wiki/, index.md o Wiki reference.md è più recente di graph.sqlite, ricostruisce prima il grafo.
Nei vault con manifest compatibile usa invece snapshot/digest e generazioni immutabili con lock comune.
Tutto lavora sul solo testo scritto dall'utente (recall.scritto): i blocchi <pasted_content> incollati non danno
punti di partenza, non cercano nella memoria, non restano in sospeso e non fanno uscire domande aperte.
Fatti: tutte le relazioni tipizzate e al più 10 link generici (limiti per tipo in recall.py); se qualcosa resta fuori,
l'ultima riga dei fatti lo dice («N link generici omessi»).
Alle pagine nominate nel prompt aggiunge quelle lette in passato per domande simili (memoria.py).
Se né il grafo né la memoria danno punti di partenza, ripiego sul testo delle pagine (recall.per_testo_a_cascata, FTS5):
fino a 3 pagine che contengono le parole o le date del prompt, e se non ce ne sono un secondo giro più largo con al più
2 pagine; solo se è una domanda sul contenuto (memoria.e_domanda:
non per comandi, conferme, richieste di modifica o domande sul sistema), aggiunte come punti di partenza e dichiarate nel
contesto «trovate nel testo, non per nome» (aggancio debole: il modello le verifica), nel systemMessage con
«N pagine dal testo». La condizione sta in ripiego_testo, usata anche da misura.py. Non vale con la memoria: le pagine lette in passato per domande simili sono un segnale più
forte di una ricerca per parole, e non si mescolano. Il routing non cambia (modello_hook usa solo i semi per nome):
con soli semi dal testo risponde Opus.
Prompt che il grafo non riconosce → se è una domanda sul contenuto (non un comando, una richiesta di modifica,
una domanda sul sistema o una conferma: memoria.e_domanda) resta in sospeso in memoria.sqlite, in attesa delle pagine lette (learn_hook.py);
senza nemmeno pagine dalla memoria, la riga "nessuna pagina riconosciuta" per l'utente e, per il modello,
AVVISO_NESSUNA_PAGINA (cercare in wiki/, non rispondere dalla conoscenza generale): non tutti i vault hanno un CLAUDE.md
che lo dica. Non è un guasto, quindi non porta MARCA_GUASTO; modello_hook.py manda comunque a Opus.
Se la ricostruzione fallisce (per esempio frontmatter YAML non valido in una pagina) e graph.sqlite esiste, usa il
grafo precedente e lo dichiara: nel systemMessage e in testa all'additionalContext (AVVISO_GRAFO_VECCHIO). Un errore
nelle domande aperte ne fa perdere solo le domande (nota nel systemMessage). Qualsiasi altro errore, o graph.sqlite
assente e non ricostruibile, stampa comunque un JSON con systemMessage e AVVISO_SENZA_GRAFO per il modello: lo stdout
è sempre e solo quel JSON. Le righe di guasto iniziano con MARCA_GUASTO, che modello_hook.py usa per non dare mai
a Haiku un prompt senza recall affidabile.
Con GRAFO_SENZA_MEMORIA=1 (lo imposta misura.py) la memoria non si legge né si scrive.
Log dei turni (tabella `turni` di memoria.sqlite, memoria.py --turni): a OGNI prompt, anche senza semi, una riga con il
testo scritto, i semi con l'origine (nome, titolo, memoria, testo), le pagine iniettate nei fatti e il routing (NULL: lo
decide modello_hook dopo); learn_hook.py le collega le pagine che il modello poi legge. L'origine nome/titolo si ricava
da punti_di_partenza (presi per nome + per_titolo) senza toccare recall.py. Un errore nel log non fa fallire il recall:
si perde solo la riga, e lo stdout resta il solo JSON.
In coda ai fatti, al più 3 domande aperte del vault sulle stesse pagine (domande.py), mai due volte
la stessa nella sessione; con GRAFO_SENZA_DOMANDE=1 (lo imposta misura.py) nessuna domanda.

Lo chiama modello_hook.py, registrato in .claude/settings.json, che con Opus può far rispondere Haiku;
si prova a mano con:
  echo '{"prompt": "il file delle fatture non arriva, a chi scrivo?"}' | python .graph/recall_hook.py

| Funzione | Descrizione |
| --- | --- |
| `ripiego_testo(db, testo, dal_grafo, ricordate=())` | Le pagine del ripiego sul testo, o [] se non scatta. Una sola condizione per l'hook e per misura.py: ripiego solo |
| `origine_semi(db, testo, dal_grafo, ricordate, dal_testo, semi)` | [(pagina, origine)] dei semi: nome o titolo (punti_di_partenza = presi per nome + per_titolo(presi)), memoria, testo. |
| `aggiorna(vault, db)` | — |
| `breve(e)` | Errore su una riga, al più MAX_ERRORE caratteri. |
| `recall()` | — |
| `main()` | — |

## `kit/graph/sintesi.py`

Domande a cui il vault sa già rispondere, ma solo mettendo insieme più pagine: candidate a una pagina di sintesi.

Complementare a domande.py, che elenca le domande aperte da rivolgere all'autore. Qui la risposta c'è già,
sparsa: una pagina di sintesi la raccoglie, e il recall la trova senza percorrere la catena ogni volta.
Deterministico, nessun LLM: la pagina la scrive la skill di lint, questo script sceglie cosa e verifica.

Quattro famiglie di domande:
  memoria   domande reali che il grafo non riconosceva, con le pagine lette per rispondere (memoria.sqlite)
  catena    da un processo o sistema, le relazioni usa/richiede/referente seguite fino a 3 passi,
            se toccano almeno 2 pagine oltre al punto di partenza (Rilascio in produzione → Console di rilascio →
            Incident settimanale → Anna Rossi). Sono le domande in cui la ricerca
            senza grafo sbaglia di più
  termine   identificatori citati in 3+ pagine di 3+ aree senza pagina né alias (domande.termini)
  persona   le pagine di cui una persona è `referente`, se sono almeno 2

Una domanda è **coperta** se esiste già una pagina che linka tutte le pagine della risposta (o è una di
esse e linka le altre); per un termine, se una pagina lo ha come titolo o alias. Scrivere la pagina di
sintesi è quindi anche il modo di chiudere la domanda, e rilanciare lo script è la verifica.
L'entropia resta governata perché le pagine generate non generano domande nuove: sono `riferimento`
(non partono catene), non dichiarano `referente`, e domande.py e domande.termini le ignorano (tag `entropia`).
Una domanda che il vault non basta a chiudere si scarta con --scarta: esce da qui ed entra nelle domande
aperte di domande.py, cioè va all'autore.

--verifica controlla le pagine con tag `entropia` già scritte: avviso «Informazioni generate da entropia
del vault» con la domanda a cui rispondono, `riguarda`, domanda risultata coperta, nessuna fonte che
non sia già in una delle pagine linkate (un fatto nuovo porterebbe una fonte nuova).

Uso:
  python .graph/sintesi.py                     candidate non coperte, in ordine di priorità
  python .graph/sintesi.py --tutte             anche quelle coperte, con la pagina che le copre
  python .graph/sintesi.py --json              per la skill di lint
  python .graph/sintesi.py --scarta "domanda" --motivo "manca il referente: chiedere all'autore"
  python .graph/sintesi.py --verifica          controlla le pagine generate (exit 1 se ci sono problemi)

| Funzione | Descrizione |
| --- | --- |
| `collegamenti(db)` | Pagina → pagine linkate, nel testo o nel frontmatter. |
| `copertura(uscenti, pagine)` | La prima pagina che da sola collega tutte quelle della risposta, o None. |
| `catene(db)` | — |
| `termini(db, vault)` | — |
| `persone(db)` | — |
| `memoria(qui, esistenti)` | — |
| `candidate(db, qui, tutte=False)` | — |
| `verifica(db, qui)` | Problemi delle pagine generate per entropia: [(pagina, problema)]. |
| `main()` | — |

## `kit/graph/stemmer.py`

Stemmer italiano: l'algoritmo Snowball (https://snowballstem.org/algorithms/italian/stemmer.html) in Python puro.

Serve a far incontrare le forme derivate di una parola, che togliere le vocali finali non riesce a unire:

    rilasciare  rilascio  rilasciato      → rilasc        collaudare  collaudo  collaudato → collaud
    approva     approvazione  approvare   → approv        caricamento  caricamenti  caricare → caric
    chiave  chiavi                        → chiav         lunghe  lungo                  → lung

Adattamenti rispetto a Snowball, che lavora sul testo con gli accenti:
  - `stem()` riceve parole già passate da build_graph.norm (minuscole, a-z0-9, SENZA accenti). Gli accenti che
    Snowball cita nei suffissi (-ità, -istà, -erà, -irò ...) qui sono già caduti: «ità» diventa «ita», e basta (è
    già nell'elenco del passo 1, con la stessa regola R2). I suffissi verbali solo accentati (erà, erò, irà, irò)
    NON si aggiungono senza accento: «era», «ero» sono vocali finali comuni («numero» → «num» ma «numeri» →
    «numer») e le toglie comunque il passo 3a quando serve.
  - le vocali sono a e i o u; le regioni RV, R1, R2 si calcolano come in Snowball;
  - il passo 2 (suffissi verbali) lascia almeno MIN_RADICE_VERBO lettere: lo Snowball originale riduce «chiavi» a
    «chi» (-avi come imperfetto) ma «chiave» a «chiav»; così chiave e chiavi si incontrano;
  - una parola con cifre (acme0, db2, 2026) non si tocca: è un identificatore, non una parola italiana;
  - una parola di meno di 3 lettere non si tocca.
Il risultato non è una parola: è una chiave di confronto. Due parole con la stessa radice «parlano della stessa cosa»
(con qualche falso amico, come in ogni stemmer: «caricare» e «carico» sì, ma anche «carica» come ruolo).

| Funzione | Descrizione |
| --- | --- |
| `stem(parola)` | Radice di una parola italiana già normalizzata (norm: minuscole, a-z0-9, senza accenti). |

## `kit/graph/teseo_dashboard.py`

Avvia il servizio locale del kit installato, senza eseguire codice dei vault collegati.

## `kit/graph/teseo_git.py`

Autosync del vault: `pre` all'inizio di una skill (pull), `post` alla fine (commit e push).
`avvisi` conta gli aggiornamenti remoti con un solo fetch (usato dall'hook SessionStart): mai pull, mai scritture.

Codici di uscita: 0 eseguito, nulla da fare o collaborazione non attiva; 2 bloccato, serve
un'azione umana (messaggio su stderr, dettagli JSON su stdout); 3 rete o autenticazione assenti,
lavoro conservato. Nei vault non collaborativi non fa nulla ed esce con 0.

| Funzione | Descrizione |
| --- | --- |
| `main(argv=None)` | — |

## `kit/graph/teseo_receipt.py`

Genera una ricevuta locale del ciclo skill dal runtime fidato installato.

## `kit/graph/teseo_sync.py`

Ispezione readonly di un candidato Git conservato: nessun apply o push.

| Funzione | Descrizione |
| --- | --- |
| `inspect_candidate(vault, candidate)` | — |
| `main(argv=None)` | — |

## `kit/graph/teseo_validate.py`

Verifica sintesi da runtime fidato su copia sacrificabile, mai su DB personali.

| Funzione | Descrizione |
| --- | --- |
| `main(argv=None)` | — |

## `kit/dashboard/__init__.py`

Fondazioni della dashboard locale; nessun servizio o automatismo attivo.

## `kit/dashboard/adapters.py`

Adapter manuali: versioni osservabili, nessun avvio AI o callback presunto.

| Classe | Descrizione |
| --- | --- |
| `ManualAdapter` | — |

| Funzione | Descrizione |
| --- | --- |
| `phase_instructions(phase)` | — |
| `default_adapters()` | — |

## `kit/dashboard/authors.py`

Autori delle note dalla storia Git: la persona è l'autore del commit, agente e skill vengono dai trailer Teseo-*.

| Funzione | Descrizione |
| --- | --- |
| `history_head(root)` | OID di HEAD se root è un repository con almeno un commit, altrimenti None (copie isolate, vault senza Git). |
| `collect(root, pages)` | [(entity_id, creato_da, creato_il, modificato_da, modificato_il, agente, modifiche)] per le pagine in `pages`. |

## `kit/dashboard/autosync.py`

Autosync opt-in: pull prima e commit+push dopo ogni skill, sullo stesso motore del publisher.

Nessuna scorciatoia: stesso GitRepository (allowlist, segreti, checkpoint attribuito, integrazione
isolata, fast-forward) e stessa macchina a stati di SyncService. Una sessione per ogni esecuzione
di skill, in .teseo/local/autosync.sqlite. Conflitti reali, storie divergenti e pubblicazioni
bloccate restano alla dashboard.

| Classe | Descrizione |
| --- | --- |
| `Autosync` | — |

## `kit/dashboard/bootstrap_ui.py`

Workbench locale: asset fidati, contenuti del vault inseriti come testo.

## `kit/dashboard/client_receipt.py`

CLI locale esplicita: produce ricevuta, non invia rete né applica note.

| Funzione | Descrizione |
| --- | --- |
| `create_receipt(request_path, outcome, reason='', checks=None, answer_ids=None, operation_id=None)` | — |
| `main(argv=None)` | — |

## `kit/dashboard/consolidation.py`

UUID selezionati, note giustificate e merge dei soli eventi sopraggiunti.

| Funzione | Descrizione |
| --- | --- |
| `selection(base, answer_ids, vault)` | — |
| `prepare(journal, record, candidate, answer_ids)` | — |
| `validate_added_events(base, candidate, authorized)` | — |

## `kit/dashboard/contracts.py`

Contratti v1 puri: parsing e classificazione non modificano il vault.

Questo modulo è l'autorità runtime dei formati di base. Non adotta vault legacy,
non valida ancora lo schema dei singoli eventi e non autorizza scritture.

| Classe | Descrizione |
| --- | --- |
| `ContractError` | Errore serializzabile senza traceback o contenuto privato. |
| `PathKind` | — |
| `VaultCompatibility` | — |

| Funzione | Descrizione |
| --- | --- |
| `is_junction(path: str | Path)` | Junction NTFS anche prima di Python 3.12, dove Path.is_junction manca: mai "non è un link" per ignoranza. |
| `stamp_schema(db: sqlite3.Connection)` | Marca un database locale; rifiuta (senza riscrivere) uno scritto da una versione più recente. |
| `dir_token(identifier)` | Nome corto di cartella per un UUID: 64 bit, minuscolo perché NTFS non distingue le maiuscole. |
| `snapshot_base_rel(operation_id)` | — |
| `candidate_rel(operation_id, checkpoint_id)` | — |
| `rebased_rel(operation_id, rebased_id)` | — |
| `graph_name(generation)` | — |
| `max_vault_path_length()` | Lunghezza massima della radice del vault, o None se non c'è un limite di piattaforma. |
| `check_path_budget(root: str | Path)` | Rifiuta prima di scrivere: oltre MAX_PATH le operazioni fallirebbero a metà e resterebbero da recuperare. |
| `parse_json(data)` | JSON UTF-8 senza BOM, chiavi duplicate, float o normalizzazioni implicite. |
| `canonical_json(value)` | Byte canonici, LF incluso; conserva i campi opzionali sconosciuti. |
| `content_hash(value)` | — |
| `file_hash(path)` | — |
| `portable_path(path)` | Valida una stringa relativa portabile, senza accedere al filesystem. |
| `resolve_path(root, path)` | Controlla anche symlink e junction; non garantisce esclusione da race. |
| `validate_paths(paths)` | Rifiuta collisioni anche su filesystem sensibili alle maiuscole. |
| `classify_path(path)` | Classificazione conservativa: unknown non è un permesso di condivisione. |
| `parse_manifest(data)` | — |
| `inspect_vault(root)` | Legacy resta readonly; un manifest incompatibile non innesca migrazioni. |

## `kit/dashboard/diagnostics.py`

Diagnostica minima su stderr: tipo, codice contrattuale e posizione; mai messaggi, percorsi assoluti, contenuti o token.

| Funzione | Descrizione |
| --- | --- |
| `log_unexpected(error: BaseException)` | — |

## `kit/dashboard/git_sync.py`

Conservative Git primitives for *data* repositories, never the kit checkout.

Callers own the vault lock and must explicitly pause external writers before
checkpoint/adoption. Git locks and hash preconditions detect, not exclude, editors.
No credentials or raw subprocess output are persisted or returned on failures.

| Classe | Descrizione |
| --- | --- |
| `GitRepository` | — |

| Funzione | Descrizione |
| --- | --- |
| `global_author()` | {'name','email'} da ~/.gitconfig, oppure {} se mancano o non sono accettabili. |
| `remote_branch_oid(url, branch, *, allow_local_remote=False)` | OID del branch sul remoto, None se il remoto è vuoto o non ha quel branch; errore se irraggiungibile. |
| `clone_data_repository(url, branch, destination, *, allow_local_remote=False)` | Clona il repository dati in una cartella vuota o nuova, rifiutando alberi fuori policy. |
| `validate_remote(value, *, allow_local_remote=False)` | No credentials, arbitrary hosts, helpers, option injection or URL queries. |
| `github_repository_url(remote)` | — |
| `is_local_only(path)` | Fonte raw non testuale: resta sul disco e non entra mai nel repository dati. |
| `read_local_excludes(root)` | Percorsi del blocco Teseo in .git/info/exclude (vuoto se assente), senza gli escape di Git. |
| `write_local_excludes(root, patterns)` | Sostituisce il blocco Teseo in .git/info/exclude; le righe dell'utente restano intatte. |
| `preview_data_repository(root, selection=None)` | Read-only onboarding preview, including a vault not yet under Git. |
| `initialize_data_repository(root, branch, remote_url, selection, *, author, share_confirmed, expected_files=None, allow_local_remote=False)` | Initialize an explicitly approved data selection; never create/push a remote. |

## `kit/dashboard/graph_edit.py`

Editor del grafo: modifiche atomiche al frontmatter di una pagina, con preview e candidato già validato.

Sono modifiche di byte conservative (stesso criterio di ontology_migrations): si riscrive solo il blocco della chiave
toccata e il risultato deve riparsare esattamente nel frontmatter atteso, altrimenti la modifica è manuale.
Il corpo della pagina non si tocca mai. Nessuna scrittura sul vault: l'apply passa dal journal (ApplyService).

| Classe | Descrizione |
| --- | --- |
| `GraphEditService` | Cache di sessione limitata di proposte: niente journal, lock persistente o scritture nel vault. |

| Funzione | Descrizione |
| --- | --- |
| `edit_page(text, name, vocabulary, pages, operations, today)` | Nuovo testo della pagina `name` dopo le operazioni, oppure ContractError con codice edit_*. |
| `analyze(snapshot, page, operations, today)` | Preview deterministica: diff del frontmatter, candidato e problemi del grafo candidato (nessuna scrittura). |

## `kit/dashboard/graph_service.py`

Generazioni derivate: il solo manifest corrente viene sostituito atomicamente.

| Funzione | Descrizione |
| --- | --- |
| `rebuild(root, *, lock=None, cancelled=None, validating=None, operation_id=None)` | Build da copia dei byte, lock comune e controllo contenuti prima del marker. |
| `backup_personal_databases(root, timeout=30)` | SQLite online backup: include dati WAL committati, mai semplice copia file. |

## `kit/dashboard/graph_ui.py`

Disegno del grafo: layout a forze, zoom e pan, colori per tipo, vicinato espandibile. Solo SVG e DOM, nessuna risorsa esterna.

## `kit/dashboard/jobs.py`

Rebuild derivati espliciti: journal persistente, lock comune, nessun apply note.

| Classe | Descrizione |
| --- | --- |
| `RebuildCoordinator` | — |

## `kit/dashboard/node_ui.py`

Strumenti del nodo selezionato: autori, catena causale, vicinato nel disegno ed editor del grafo (anteprima → applica).

## `kit/dashboard/ontology_apply.py`

Apply manuale (Windows e POSIX) con journal e recovery; nessuna esclusione editor promessa.

| Classe | Descrizione |
| --- | --- |
| `ApplyService` | — |

| Funzione | Descrizione |
| --- | --- |
| `execute(journal, identifier, action='finish')` | Lock già detenuto, nessun replay automatico. Anche il rollback è esplicito. |

## `kit/dashboard/ontology_migrations.py`

Migrazioni conservative su byte: mai dump YAML o sostituzioni nel testo libero.

| Funzione | Descrizione |
| --- | --- |
| `migration_id(item)` | — |
| `migrate(data, item)` | — |
| `describe(data, item)` | — |

## `kit/dashboard/ontology_preview.py`

Preview su snapshot corrente: schema candidato e impatto, nessuna scrittura.

| Classe | Descrizione |
| --- | --- |
| `PreviewService` | Cache di sessione limitata: niente journal, lock persistente o scritture vault. |

| Funzione | Descrizione |
| --- | --- |
| `analyze(snapshot, patch)` | Funzione pura rispetto al filesystem: tutti i dati derivano dallo snapshot. |

## `kit/dashboard/ontology_ui.py`

Editor proposte e apply manuale confermato; testo del vault sempre inerte.

## `kit/dashboard/operation_validation.py`

Gate deterministici del candidato: attribuzione e confini prima dell'apply.

| Funzione | Descrizione |
| --- | --- |
| `validate_candidate(base, candidate, *, kind, inputs, scope, processed_response_ids=(), authorized_event_paths=())` | — |

## `kit/dashboard/operations.py`

Cicli skill persistenti: output isolato, ricevute e nessun successo implicito.

| Classe | Descrizione |
| --- | --- |
| `SkillCoordinator` | — |

## `kit/dashboard/read_api.py`

Consultazione di una generazione immutabile; nessuna GET costruisce o scrive dati.

| Classe | Descrizione |
| --- | --- |
| `ReadAPI` | — |

## `kit/dashboard/readonly.py`

Attach readonly; persistenza opzionale nel solo file scelto dal launcher.

| Classe | Descrizione |
| --- | --- |
| `VaultRegistry` | — |

## `kit/dashboard/receiver.py`

Opt-in remote detection; never apply, merge or replace live vault data.

The publisher mutex and kernel vault lock serialize detection with cooperative
writers. They cannot exclude editors: automatic application stays disabled.

| Classe | Descrizione |
| --- | --- |
| `Receiver` | — |

## `kit/dashboard/receiver_apply.py`

Explicit receive (Windows and POSIX): journal files, index and ref; never automatic apply.

| Classe | Descrizione |
| --- | --- |
| `ReceiverApplyService` | — |

## `kit/dashboard/registry_store.py`

Registro opzionale, locale al servizio: nessun token né codice dei vault.

| Classe | Descrizione |
| --- | --- |
| `RegistryStore` | — |

## `kit/dashboard/server.py`

Dashboard loopback: consultazione e rebuild derivati espliciti coordinati.

| Classe | Descrizione |
| --- | --- |
| `DashboardServer` | — |
| `DashboardHandler` | — |

| Funzione | Descrizione |
| --- | --- |
| `main(argv=None)` | — |

## `kit/dashboard/shared_migration.py`

Selective export from a consistent legacy backup; original SQLite stays local.

This module prepares events only. Publication belongs to the shared coordinator.
Unknown provenance is deliberately a new local UUID, never a content-derived ID.

| Classe | Descrizione |
| --- | --- |
| `LegacyMigration` | Explicit row selection with durable UUID/event mapping and stale-source gate. |

## `kit/dashboard/shared_service.py`

Explicit shared mutations; personal SQLite is never consulted by answer reads.

| Classe | Descrizione |
| --- | --- |
| `SharedService` | — |

| Funzione | Descrizione |
| --- | --- |
| `author_id(root)` | Stable pseudonym for this local checkout; callers hold the vault lock. |

## `kit/dashboard/shared_state.py`

Eventi condivisi v1: validazione pura, DAG causale e cache SQLite rigenerabile.

Il clock e l'autore sono informativi. Nessun evento esegue codice o modifica note.
La cache non sostituisce i file immutabili del vault.

| Funzione | Descrizione |
| --- | --- |
| `validate_event(event, vault_id, filename=None)` | Rifiuta versioni, campi eseguibili/sconosciuti e identità non canoniche. |
| `snapshot_events(snapshot, vault_id)` | Legge soltanto eventi nei byte già catturati, senza accesso al filesystem. |
| `project(events, vault_id, allow_pending=True)` | Proiezione deterministica del medesimo insieme, con conflitti visibili. |
| `import_events(db_path, events, vault_id)` | Merge transazionale locale: duplicati no-op, collisioni rollback completo. |
| `validate_snapshot(snapshot, vault_id=None, allow_pending=False)` | Valida l'insieme completo; il manifest è l'autorità per vault_id. |
| `rebuild_projection(db_path, events, vault_id)` | Ricostruisce soltanto la cache dall'insieme esatto post-checkpoint. |

## `kit/dashboard/shared_ui.py`

Risposte condivise: consenso esplicito, causalità e preview privacy.

## `kit/dashboard/skill_ui.py`

Controlli espliciti dei cicli: handoff, ricevute e applicazione revisionata.

## `kit/dashboard/storage.py`

Storage locale del coordinator futuro, senza apply delle note.

I lock coordinano solo i chiamanti cooperanti. Snapshot e precondizioni hash
non escludono editor esterni e non autorizzano apply automatici.

| Classe | Descrizione |
| --- | --- |
| `VaultLock` | Lock kernel su un file persistente: non rimuovere lock in base al PID. |
| `SnapshotFile` | — |
| `Snapshot` | — |
| `Journal` | Record SQLite transazionali e copie prima dell'operazione. |

| Funzione | Descrizione |
| --- | --- |
| `assert_receiver_complete(root)` | A crashed receive blocks other cooperative writers and live projections. |
| `capture_snapshot(root, max_bytes=64 * 1024 * 1024, *, allow_missing_schema=False)` | Due scansioni di confronto, limite esplicito; nessuna garanzia anti-race. |
| `validate_raw_unchanged(base, candidate)` | Nuove fonti ammesse; eliminazione, modifica e rename di raw vietati. |

## `kit/dashboard/sync_service.py`

Publisher esplicito: checkpoint attribuiti, candidati isolati e recovery OID.

La configurazione non autorizza l'automazione: ogni tentativo richiede conferma
di sospensione degli scrittori esterni. Credenziali gestite soltanto da Git.

| Classe | Descrizione |
| --- | --- |
| `SyncService` | — |

## `kit/dashboard/sync_ui.py`

Publisher dati: preview esplicita, nessuna credenziale nel browser.

## `kit/dashboard/sync_validation.py`

Deterministic integration gates; semantic reconciliation needs a human verdict.

The optional callback belongs to the trusted service, never to vault data. It
attests an already reviewed, frozen candidate and cannot authorize new bytes.
Lexical/neighborhood overlap is conservative evidence, not semantic proof.

| Funzione | Descrizione |
| --- | --- |
| `validate_integration(base_root, local_root, remote_root, candidate_root, *, reconcile=None)` | Validate isolated complete vaults; only candidate derived caches are written. |

## `kit/dashboard/ui_script.py`

Workbench: consultazione e proposte ontologia, contenuti sempre inerti.

## `kit/dashboard/ui_style.py`

Stile del workbench, senza asset o dipendenze esterne.

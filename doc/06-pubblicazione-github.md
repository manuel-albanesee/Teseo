# 6 — Pubblicazione automatica sul repository dati GitHub

Stato: progetto futuro. Dipende da [1](01-contratto-dati-operazioni.md), [2](02-dashboard-consultazione.md), [4](04-coordinamento-ingest-lint.md), [5](05-stato-condiviso.md). Obiettivo: concluso ingest+lint valido, integrare le novità degli altri e pubblicare senza passaggi ordinari manuali; i conflitti o le policy bloccanti diventano richieste specifiche e recuperabili.

## Stato attuale, onboarding e confini

Il [README](../README.md) documenta il clone del kit e l'installazione in una cartella vault; [installa.py](../installa.py) distribuisce file, ma non realizza sync collaborativa. [Ingest](../kit/skills/obsidian-wiki-ingest/SKILL.md) e [lint](../kit/skills/obsidian-wiki-lint/SKILL.md) aggiornano note/index/log. [domande.py](../kit/graph/domande.py) contiene stato locale da migrare prima della collaborazione. Non assumere che il repository del kit sia il repository dati.

La UI collega un repository dati esistente oppure guida alla sua creazione con scelta esplicita di proprietario, visibilità, branch condiviso e fonti da pubblicare. Il branch è scelto, non dedotto sempre come `main`; validare URL, tracking e identità del vault. Un vault non ancora Git richiede inizializzazione e prima preview della selezione dati; non caricare automaticamente tutto. Creazione repo è capacità futura separata, da verificare tramite Git/gh disponibili. Ogni persona autentica il proprio Git/gh con credenziali locali e identità autore Git; distinguere account autenticato, autore commit e permesso di push. Non richiedere token nel browser o salvare credenziali nei file condivisi.

Policy portabile allowlist di dati: note, schema, indice, log, eventi e nuove fonti selezionate; locale: percorsi e impostazioni account. Escludere ogni SQLite, WAL/SHM, cache, backup, sessione, token, configurazioni client e script eseguibili. Un `.gitignore` da solo non basta per file già tracked: bloccare e proporre pulizia esplicita, senza riscrivere storia. Non includere automaticamente `.graph/`, `.codex/`, `.claude/`, `.github/` o `AGENTS.md` dal vault. I dati possono suggerire istruzioni, ma non vanno eseguiti.

## Branch e algoritmo proposti

Futuro `git_sync.py` usa subprocess con argomenti separati, ambiente controllato, cwd verificata e timeout; nessuna shell costruita dai nomi note. Richiede working tree e index puliti all'inizio del job radice, o snapshot isolato con attribuzione verificata. Apply e adozione rispettano la modalità di esclusione degli scrittori esterni definita nel passo 1; gli hash da soli non la sostituiscono. Se l'utente introduce modifiche estranee durante il job, il completamento locale può essere conservato ma la pubblicazione automatica resta bloccata; niente stash/reset automatici.

Definizioni: `B` checkpoint condiviso di partenza, `L` checkpoint locale validato prodotto dall'operazione, `R` revisione remota dopo fetch, `C` candidato integrato. Il branch del clone segue lo shared branch ed è posseduto dall'utente. Scelta progettuale: al checkpoint locale creare `L` sul branch vivo soltanto dopo aver verificato che index e working tree contengano esclusivamente le modifiche attribuite all'operazione. L'integrazione con `R` avviene invece su ref e area isolate; `C` deve essere discendente di `L`, così l'adozione finale è fast-forward. Worktree temporaneo o repository di staging dedicato restano alternative di isolamento da valutare nella prima PR, senza cambiare questa regola di ancestry.

1. Consumare una sola volta `operation.validated`; verificare manifest, versione e policy. Se l'albero condivisibile è identico a `B`, registrare no-op senza commit log aggiuntivo.
2. Creare `L` dall'insieme preciso di file autorizzati. Richiedere index inizialmente vuoto, aggiungere solo i percorsi del manifest con controllo hash e verificare diff staged/albero finale e raw rispetto a `B` immediatamente prima del commit. Nessun `git add .` indiscriminato. Verificare dopo il commit che HEAD sia `L` e working tree/index siano puliti; una scrittura esterna interrompe la pubblicazione e conserva il checkpoint. Journal conserva OID e mapping operation→checkpoint prima di proseguire; al recovery identificare un commit già creato tramite operation ID e albero anziché duplicarlo.
3. Fetch del solo remote/branch configurato; fissare `R`. Se non accessibile, stato `waiting_network/auth`, nessuna perdita di `L`.
4. In area isolata costruire `C`: se `R=B`, usare `L`; se la base comune è coerente, integrare `L` e `R` con merge ordinario preservando entrambi. Cronologia estranea, upstream cambiato o branch locale divergente da quanto registrato richiedono risoluzione esplicita.
5. Risolvere conflitti deterministici solo quando dimostrabili. Index/log hanno entry con UUID operazione e ordinamento deterministico; preservare testo libero o segnalare conflitto. Non concatenare ciecamente index né scegliere automaticamente un lato dello schema. Conflitto sulla stessa nota o raw alterato blocca `C` senza toccare il vault vivo.
6. Controllare compatibilità, immutabilità raw rispetto a entrambi i parent, eventi, struttura, fonti, link e sintesi su `C`. Costruire grafo candidato. Verificare correlazioni semantiche come descritto sotto, anche quando Git non segnala conflitti testuali.
7. Salvare `C` validato e tentare push ordinario dell'OID sul branch selezionato, mai force. Se il remote è avanzato, nuovo fetch e nuovo candidato su `R` aggiornato; massimo iniziale proposto 3 tentativi, configurabile. Non ritentare ciclicamente fallimenti di policy, autenticazione o conflitti.
8. Dopo successo, registrare `published_oid=C`; promuovere clone vivo con procedura journal e precondizioni hash. HEAD deve essere ancora `L` e working tree/index puliti; applicare fast-forward a `C`, mai `reset --hard`. Se il branch è stato mosso esternamente, non cambiarlo: sospendere l'adozione e confrontare la nuova ancestry. Verificare file, index, ref e generazioni dopo l'aggiornamento prima di dichiarare convergenza.
9. Se il push è riuscito ma nel frattempo un editor ha cambiato il vault vivo, non sovrascrivere: stato `published_pending_local_adoption`, mantenere `C`, mostrare il diff e attendere risoluzione. Nessun nuovo push o rerun lint. Il receiver riconosce l'OID già pubblicato.

Alternativa scartata per il primo rilascio: mantenere `L` solo in una ref isolata mentre il branch vivo resta a `B` con note già modificate. Richiederebbe una promozione personalizzata di branch, index e file, con più stati di recovery. La strategia scelta lascia un commit locale non ancora pubblicato quando rete o policy bloccano il push: la UI deve mostrarlo e non cancellarlo.

## Riconciliazione semantica mirata

Note diverse possono dire «referente Anna» e «referente Bruno» per lo stesso processo pur passando un merge Git pulito. Costruire perimetro da pagine cambiate in `L` e `R`, entità/alias/fonti comuni, vicinato tipizzato e sintesi dipendenti. Se entrambe le parti interessano fatti correlati, avviare job di riconciliazione separato in area isolata tramite il passo 4; conservare fonti e segnalare contraddizioni sostanziali come punti aperti. Se l'analisi non può chiudere un conflitto, stato `needs_decision`, senza pubblicare come verificato. Non è un lint completo e non è richiesto su import disgiunti.

La chiave di deduplica è hash di `L`, `R`, schema, versione policy e insieme correlato; il risultato registra input/output. Un output di riconciliazione non avvia un nuovo ciclo ingest→lint→push: resta figlio della stessa operazione di sync. Limitare espansioni e tentativi; nuovo remote significa nuova chiave solo per nuovo contenuto. Non chiamare il modello per no-op. I controlli deterministici non provano assenza di contraddizioni semantiche; la UI deve mostrare perimetro verificato e limiti.

## Stato, policy e API future

`ready → checkpointed → fetching → integrating → validating → reconciling? → pushing → published → adopting → converged`; pause `waiting_network`, `waiting_auth`, `needs_resolution`, `needs_approval`, `retry_exhausted`, `published_pending_local_adoption`. Journal include `B/L/R/C`, tentativi, job figli e ricevuta push. Dopo crash in `pushing`, fetch e controllare se `C` è già raggiungibile sul branch remoto prima di ripubblicare; timeout non equivale a push fallito.

`POST /api/v1/vaults/{id}/sync/configure` salva selezione e policy esplicite; `GET /sync/status` mostra checkpoint; `POST /sync/publish` riprende o richiede pubblicazione; `POST /sync/resolve` applica una risoluzione revisionata a un candidato, mai file arbitrari. La policy automatica ascolta completamenti validati. Branch protection o consenso richiesto portano a `needs_approval`; nessun bypass. Modalità PR facoltativa produce un branch proposto e attende merge, senza aggiornare lo shared branch come se il merge fosse avvenuto. Il percorso diretto non impone PR.

## Incrementi da una PR e accettazione

1. Onboarding dati, credenziali delegate a Git/gh, allowlist e preview; uscita: nessun segreto/binario tracked e scelta visibilità esplicita.
2. Checkpoint e integrazione isolata con fixture Git locali; uscita: modifiche estranee mai committate e conflitti preservati.
3. Validazione e riconciliazione mirata con adapter finto e deduplica; uscita: note diverse correlate non passano come solo merge testuale.
4. Push/retry/journal e convergenza locale; uscita: timeout e crash non duplicano checkpoint.
5. UI conflitti, policy diretta/PR e smoke GitHub autorizzato; uscita: protezioni rispettate e messaggi recuperabili.

Comandi Git **esistenti** da usare su fixture: `git status --porcelain=v1`, `git rev-parse HEAD`, `git fetch origin`, `git merge --ff-only <OID>` solo su ramo pulito quando applicabile. Non rappresentano da soli l'intero algoritmo. I controlli del kit sono quelli del [README](../README.md); eseguirli dopo modifiche runtime. Test **futuri** `tests/test_dashboard_git_sync.py`, comando dopo creazione `python -m unittest discover -s tests -p 'test_dashboard_git_sync.py' -v`: due clone/stessa nota, stesso index/log, note correlate, raw mutato da remoto, push rifiutato, remote cambia durante push, autenticazione/policy negate, no-op, editor tra push e adozione. Usare bare remote temporaneo per test deterministici e mock di policy GitHub; smoke reale separato. Nessun push o test runtime svolto durante questa documentazione.

## Rollout, rollback e fonti

Prima preview, poi pubblicazione richiesta dall'utente, infine ciclo automatico configurato. Rollback sospende nuove pubblicazioni e conserva OID/journal; contenuti già pubblicati si correggono con commit compensativo validato. Nessun force push o cancellazione di storia. Restano da decidere nomi dei branch operativi, policy di riconciliazione per dominio e retention dei candidati.

[Git pull](https://git-scm.com/docs/git-pull) documenta fetch e integrazione e le opzioni fast-forward: il progetto esplicita le fasi per poterle validare. Gli [hook Git](https://git-scm.com/docs/githooks) sono legati a eventi del processo Git: un hook locale non sostituisce il rilevamento di push remoti. I comandi e le policy del progetto qui proposti non sono funzionalità già presenti nel kit.

# 6 — Pubblicazione automatica sul repository dati GitHub

Stato: publisher runtime disponibile con richiesta e conferme esplicite; automazione continuativa disabilitata. Onboarding locale, checkpoint, integrazione isolata, validazione, revisione mirata, push/recovery e UI sono implementati. Creazione remota GitHub e apertura automatica PR restano capacità distinte non attivate. Dipende da [1](01-contratto-dati-operazioni.md), [2](02-dashboard-consultazione.md), [4](04-coordinamento-ingest-lint.md), [5](05-stato-condiviso.md). Le sezioni progettuali seguenti descrivono anche l'obiettivo automatico; il contratto effettivo e i limiti del primo rilascio sono riportati in fondo.

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

## Stato, policy e API di riferimento

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

## Contratto runtime del primo rilascio

Moduli: `git_sync.py` contiene primitive Git e policy; `sync_service.py` journal
locale e coordinamento; `sync_validation.py` gate e correlazioni; `sync_ui.py`
la superficie dashboard. Tutti sono distribuiti dall'installer dashboard.

La creazione del repository su GitHub resta manuale: scegliere proprietario e
visibilità sul servizio, autenticarsi localmente, poi indicare l'URL esistente.
La dashboard non riceve password o token e non certifica la visibilità remota:
la conferma è una dichiarazione dell'utente. Sono supportati GitHub HTTPS/SSH;
helper globali credential manager/manager-core e agente SSH. Helper shell o
configurazioni eseguibili del repository vengono rifiutati. Gli altri helper,
inclusa una configurazione gh shell personalizzata, richiedono un percorso di
autenticazione supportato. Autore commit distinto dall'account autenticato.

In un vault non Git, la preview resta readonly. Inizializzazione esplicita con
branch, URL, autore e hash completi della selezione crea il solo commit locale:
nessun remoto viene creato o aggiornato. File esclusi restano visibili e locali;
prima di configurare il publisher bisogna revisionare eventuali modifiche
estranee ed esclusioni locali (`.git/info/exclude`), senza aggiungerle al commit
dati. Non viene adottato implicitamente un repository padre, né caricato tutto.
Un errore dopo init conserva `.git` per ispezione: nessuna cancellazione automatica.

Endpoint relativi a `/api/v1/vaults/{id}/sync`, protetti dalla sessione locale;
ogni POST richiede anche Origin e CSRF:

| Metodo/percorso | Corpo e comportamento |
| --- | --- |
| GET `/status` | Readonly: configurazione, autore, B/L/R/C, stato e ultime 30 richieste |
| POST `/preview` | `raw_paths` opzionale; file/hash inclusi, esclusioni e violazioni tracked |
| POST `/initialize` | branch, remote_url, raw_paths, author{name,email}, share_confirmed, expected_files{percorso:hash} |
| POST `/configure` | remote=origin, branch, visibility, mode direct/pr, raw_paths, share_confirmed, expected_head |
| POST `/publish` | operation_id, idempotency_key, exclusive_confirmed, expected_head; raw_paths/share_confirmed opzionali per nuove fonti revisionate |
| POST `/resolve` | idempotency_key originale, exclusive_confirmed; human_decision_key e resolution_digest opzionali |

Configurare su branch/working tree/index puliti **prima** del ciclo radice.
Il digest iniziale del ciclo deve coincidere con il checkpoint B configurato,
eventualmente esteso dalle sole nuove fonti input selezionate esplicitamente.
Modifiche condivise preesistenti, anche eventi appena registrati fuori da quel
ciclo, richiedono un checkpoint revisionato prima di avviare il ciclo successivo:
non vengono attribuite silenziosamente al lint. Per nuove fonti raw, revisionare
una nuova preview e confermare la selezione prima del publish: i loro hash devono
essere quelli degli input del ciclo. Nessun altro dato può estendere il baseline
in questo modo e non vengono creati commit arbitrari per ripulire il working tree.

Solo `operation.validated` dopo apply riuscito di ingest/lint, con tutti i gate,
può essere consumato. Una chiave diversa non ripubblica la stessa operazione.
No-op registrato senza nuovo commit; un fallimento non cancella L. Index isolato,
hash e confronto byte/OID prima e dopo i gate impediscono di committare file
estranei o pubblicare un tree diverso da quello verificato. Raw/eventi esistenti
sono immutabili contro entrambi i parent. Il candidato contiene esclusivamente
dati ammessi; il codice di validazione proviene dal kit installato.

Git usa argomenti separati, ambiente filtrato, binari risolti da PATH assoluto,
timeout, hook/filtri dei dati disabilitati e TLS verificato. Policy HEAD e storia
sono controlli conservativi: SQLite, binari, script/configurazioni e alcuni
pattern di credenziali riconoscibili bloccano il percorso automatico. Non è uno
scanner universale di segreti: la revisione completa dei testi resta necessaria.
Nessun force, stash, reset hard o aggiramento delle protezioni remote.

L'audit automatico della storia è limitato a 128 commit raggiungibili e 64 MiB
di blob unici; richiede manifest compatibile e identità costante anche nei
commit storici. Storia più grande, priva di manifest o contaminata blocca il
push e richiede una procedura esplicita: non viene riscritta automaticamente.
La preview distingue il controllo HEAD dall'audit imposto prima del push.

La validazione ricalcola struttura, eventi, grafo e sintesi. Correlazioni tramite
link, componenti tipizzate, alias, fonti, sintesi ed eventi della stessa domanda
producono `needs_decision`. Limite: 512 percorsi cambiati per ramo. La chiave di
revisione copre digest B/L/R/C e perimetro; senza attestazione umana esatta non si
pubblica il candidato correlato. Nessun modello è avviato da questa analisi e la
heuristica non prova assenza di contraddizioni semantiche.

Per conflitti testuali modificare soltanto la copia conservata indicata nel
journal. Dopo la revisione, ottenere il digest con:

```powershell
python .graph/teseo_sync.py --vault "C:\dati\Vault" --candidate "C:\dati\Vault\.teseo\local\git-candidates\UUID"
```

Inserire digest e conferma nella UI. Il servizio controlla appartenenza della
copia, parent, assenza di marker, immutabilità e gate; se occorre, richiede anche
la chiave della revisione semantica. Remote avanzato invalida quella risoluzione.
Non vengono accettati upload di file arbitrari e non si modifica il vault vivo
per risolvere un conflitto remoto.

Massimo tre push: remoto avanzato produce nuova integrazione; policy o auth
fermano il ciclo. Dopo conferma persa, verifica dell'OID sul remoto anche dopo
l'ultimo tentativo. PR mode pubblica soltanto `codex/teseo-<operation_id>` e
restituisce `needs_approval` e link confronto: apertura/merge PR sono manuali,
il branch condiviso non viene dichiarato aggiornato. Il primo rilascio non
adotta automaticamente il merge futuro della PR.

Push riuscito e modifica locale successiva producono
`published_pending_local_adoption`: OID conservato, nessun altro push e nessun
overwrite. Ripresa verifica HEAD/index/byte, fast-forward, grafo e proiezione;
solo allora `converged`. Il journal registra operation/checkpoint→OID. Le risposte
consolidate mostrano pubblicazione attestata dal journal locale; nei clone che
non hanno quella ricevuta resta non verificata. Il ricevitore è il passo 7.

[Verifiche ed evidenze ECC](evidence/step-6/verification.md). Test Git su remoti
bare locali; uno smoke GitHub dei dati richiede la scelta di un repository dati
specifico. Non usare il repository del kit per provare la pubblicazione dei vault.

# Analisi ECC e avanzamento

Branch di sviluppo: `codex/dashboard-foundations`, creato da `main` il 22 ottobre
2026. Nessun merge; i branch principali non vengono aggiornati. Ogni incremento
runtime verificato prevede commit e push separati su questo branch.
Destinazione autorizzata esplicitamente dall'utente:
`https://github.com/manuel-albanesee/Teseo.git`. Pubblicati con due push ordinari
distinti, in ordine: `01ba97e` (contratti) e `2e16787` (builder). Il branch locale
segue `origin/codex/dashboard-foundations`; nessun merge eseguito.

## Valutazione del piano

La sequenza dei sette passi separa correttamente kit e dati, autorità Markdown,
eventi condivisi e DB personali. I gate di recovery e gli editor non cooperanti
sono necessari: hash e watcher da soli non autorizzano apply automatici.

La prima consegna utile è il contratto puro, seguito dalla correzione del builder
esistente. Anticipiamo la sola protezione della pubblicazione del passo 1.3
rispetto al journal 1.2: corregge un difetto indipendente e verificabile, senza
introdurre nuove scritture delle note. Snapshot stabili, lock condiviso e lettori
a generazioni restano prerequisiti per attivare la dashboard e le automazioni.

| Passo | Valutazione / lavoro restante |
| --- | --- |
| 1 | Contratti, journal, lock kernel e snapshot implementati; integrazione chiamanti, apply protetto e generazioni ancora da realizzare |
| 2 | Bootstrap e UI attendono le fondazioni; scegliere server solo dopo prova packaging |
| 3 | Parser conservativo necessario; nessuna riscrittura implicita del vocabolario |
| 4 | Probe e ricevuta da provare su ogni client; Stop non certifica il successo |
| 5 | Canonicalizzazione disponibile; schema eventi per tipo, DAG, proiezioni e migrazione ancora da sviluppare |
| 6 | Staging Git isolato e attribuzione precisa obbligatori prima del push dati |
| 7 | Apply automatico subordinato a recovery e gate Windows; rilevamento può precederlo |

## Incremento 1 — contratti puri

`kit/dashboard/contracts.py` definisce le versioni supportate v1 e la prima
versione del contratto kit `1.0.0`. Non è una dichiarazione di completamento della
dashboard. Manifest esplicito con UUID e allowlist selezionabile dei sei percorsi
condivisi previsti; campi opzionali sconosciuti conservati come dati inerti.
Le versioni kit accettano inizialmente solo `major.minor.patch` stabili.

`inspect_vault` restituisce `legacy_readonly`, `compatible` o `incompatible`
senza creare directory, migrare o autorizzare scritture. `compatible` indica solo
compatibilità dei formati, non validità semantica né capacità di apply.
La classificazione copre dati, grafo, DB personali, stato locale, script/config
client e percorsi sconosciuti; unknown non è condivisibile automaticamente.
Un raw contenente codice resta una fonte inerte, mai uno script da eseguire.

JSON canonico v1 con fixture byte: UTF-8, NFC, chiavi ordinate, LF finale,
interi sicuri, rifiuto di duplicati, BOM, float e surrogate. Il serializer non
sostituisce la validazione dello schema evento del passo 5. Percorsi portabili
e risoluzione dentro root includono collisioni case-insensitive e junction;
non costituiscono una protezione dalle race di scrittori esterni.

Distribuzione nel vault rinviata al packaging del passo 2: il modulo vive nel kit
e non viene copiato o attivato implicitamente dall'installatore corrente.

Verifica ECC `verification-loop`, adattata al progetto Python: unittest mirati,
suite esistente, `installa.py --prova`, compilazione Python e revisione diff.
Non esistono configurazioni di type checker, linter o coverage nel repository:
non attribuire risultati a strumenti non eseguiti.

Esito incremento 1: suite 44 test, 43 superati e 1 saltato (creazione symlink non
consentita su questo Windows); installazione `--prova` superata, compilazione e
controllo whitespace superati. I test filesystem sono stati ripetuti fuori dal
sandbox perché l'API Windows di risoluzione stretta dei percorsi viene negata
anche nelle cartelle scrivibili. Nessun controllo del runtime è stato indebolito.

## Incremento 2 — gate del builder legacy

`build_graph.py` separa `parse_snapshot`, `validate_snapshot`, `build_candidate`
e `publish_generation`. Parsing e controlli semantici precedono la creazione del
candidato. Temporanei unici per build, connessioni chiuse, controllo integrità
SQLite readonly e cleanup su errore. Sia CLI con/senza `--check` sia chiamata
dall'hook rifiutano il grafo invalido: il precedente resta disponibile; l'hook
usa il proprio fallback già esistente e dichiara il rebuild fallito.

Questo completa la protezione da pubblicazione invalida del passo 1.3, non il
passo 1 completo. `parse_snapshot` legge i dati in memoria, ma il chiamante deve
ancora fornire una copia stabile: non offre isolamento da editor concorrenti.
La pubblicazione conserva per compatibilità `.graph/graph.sqlite`: lettori Windows
possono impedire il replace, che fallisce conservando il DB precedente. Restano
da realizzare generazioni immutabili e migrazione dei lettori (1.4), journal,
lock, digest e verifica pre-apply (1.2). Il vecchio hook controlla ancora mtime.
Non vengono attivati dashboard, ingest/lint automatici o sincronizzazione dati.

Esito incremento 2: suite completa 55 test, 54 superati e lo stesso skip symlink;
dopo la revisione, suite mirata del builder rieseguita con tutti i 12 test
superati (incluso il nuovo caso wiki mancante e frontmatter senza chiusura).
`installa.py --prova`, compilazione Python, controllo whitespace e revisione diff
superati. Nessuna nuova dipendenza. Nessun risultato di coverage o type checking
è dichiarato. `main` resta sul commit iniziale `19e5288`; non esiste un branch
locale `master` e nessun branch principale è stato modificato.

## Incremento 3 — journal, lock e snapshot (passo 1.2)

`kit/dashboard/storage.py` introduce fondazioni non ancora attivate nel vault
dall'installatore. Richiede manifest compatibile: nessuna adozione implicita dei
vault legacy. Non aggiunge dipendenze. Scelta lock: standard library `msvcrt` su
Windows, `fcntl` su POSIX. Test reali eseguiti su Windows; POSIX non verificato
in questa sessione.

`VaultLock` usa un lock esclusivo del kernel con timeout, senza rimozione del file
in base al PID; il crash del processo libera il lock. Serializza i chiamanti che
adottano questa API. Timeout produce `vault_busy`; attesa e coda dei job saranno
integrate nel coordinator del passo 4. Hook e CLI legacy non usano ancora questo
lock: non si dichiara esclusione globale degli scrittori esistenti.

`capture_snapshot` legge due volte tutto il perimetro dati e confronta hash e
percorsi. Include manifest, schema, note, index/log, raw ed eventi; esclude DB
personali, script/client e stato locale. Censisce anche dati non selezionati per
export. Rifiuta file inattesi nel perimetro, collisioni, path traversal, symlink
e junction (anche se interni, scelta conservativa). Limite predefinito 64 MiB per
scansione; le copie sono in memoria, non adatte ancora a raw molto grandi.
Timestamp invariati non nascondono cambiamenti. `validate_raw_unchanged` permette
aggiunte ma blocca modifica, eliminazione e rinomina di fonti preesistenti.

`Journal` richiede il lock per ogni accesso. SQLite con `synchronous=FULL`
conserva UUID, vault, tipo, revisione Git base fornita dal chiamante (null senza
Git), digest contenuto/schema, letture, hash prima/dopo, stato, errore e checkpoint.
Chiave idempotente uguale e stesso payload restituiscono il record esistente;
payload diverso produce conflitto. Copie base/candidato sono scritte e fsyncate
prima di registrare il relativo checkpoint. `prepare` controlla base live e raw,
ricontrolla la base dopo la copia e lascia intatte le note. La validazione di
dominio (YAML, grafo, eventi) resta responsabilità della pipeline chiamante:
`prepared` qui certifica le sole precondizioni dello storage.

Lo stato è in `.teseo/local/`, protetto da `.gitignore` con sola regola `*`;
configurazioni che reincludono file richiedono correzione esplicita. Non vengono
rimossi eventuali file già tracked in installazioni precedenti. Snapshot e DB
personali non sono esportati da questo modulo. Nessuna retention automatica:
le copie richiedono spazio e rimangono disponibili per diagnosi.

Recovery iniziale conservativa: `require_recovery` marca le operazioni interrotte,
preserva hash e checkpoint e le ripropone ai riavvii successivi; `orphan_snapshots`
segnala copie senza record/checkpoint dopo guasti. Non ripristina e non cancella
file. Apply e transizioni `applying`/`succeeded` sono bloccati finché non sarà
implementata la protezione di scrittura. Non è una transazione globale tra SQLite
e filesystem, né una promessa di resistenza a ogni guasto elettrico.

Prossimo incremento: passo 1.4, generazioni immutabili, migrazione dei lettori e
backup SQLite consistenti; integrare questi strumenti nel percorso reale prima
di attivare il servizio. Watcher, scheduling, completamento automatico della
recovery e protezione da editor non cooperanti restano futuri. Le scansioni hash
rilevano modifiche, ma non eliminano la finestra tra ultimo controllo e apply.

Verifica ECC `verification-loop`: suite completa 79 test (78 superati, uno skip
symlink già noto), poi suite storage rieseguita con 24 test tutti superati dopo
l'aggiunta del controllo timeout finiti. Inclusi processi concorrenti, attesa e
kill del proprietario, crash con `os._exit`, scrittura esterna durante copia,
immutabilità raw, copia corrotta, fallimento di checkpoint e junction Windows.
`python installa.py --prova`, compilazione Python, controllo whitespace e revisione
diff superati. Nessuna dipendenza aggiunta; type checker, lint dedicato e coverage
non configurati e non dichiarati eseguiti.

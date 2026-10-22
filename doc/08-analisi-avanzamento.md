# Analisi ECC e avanzamento

Branch di sviluppo: `codex/dashboard-foundations`, creato da `main` il 22 ottobre
2026. Nessun merge; i branch principali non vengono aggiornati. Ogni incremento
runtime verificato ha commit e push separati su questo branch.

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
| 1 | Contratti di base implementati; journal, snapshot, esclusione scrittori e generazioni ancora da realizzare |
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

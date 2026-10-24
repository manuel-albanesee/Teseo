# Verifica ECC — passo 6

Windows, 24 ottobre 2026. Solo fixture sintetiche, repository Git temporanei e
remoti bare locali. Nessun vault utente modificato o pubblicato.

Workflow ECC: orch-add-feature/pipeline, TDD, git-workflow, security-review,
verification-loop, frontend-design-direction, conventional-commit-review e
autovalutazione. Le fasi sono state delegate per core Git, validazione e UI;
review trasversale ha preceduto i push incrementali autorizzati dall'utente.

## Risultati

Suite generale: **nessun esito completo PASS dichiarato**. La prima esecuzione
su sorgenti ancora in integrazione ha eseguito 294 test con tre failure, un
errore di cleanup e uno skip noto Windows. Le due attese apply e la vecchia
route initialize sono state corrette e superate nelle riprove mirate.
La ripetizione sul sorgente stabile (312 test censiti) è rimasta incompleta:
ultimo errore nel test privacy e nessun riepilogo finale. Le directory residue
erano vuote e bloccate, come nei precedenti errori WinError32 di cleanup.
Lo stesso test privacy ripetuto isolatamente è passato: un test, 7.701 s.
Occorre ripetere la suite generale in un ambiente Windows stabile.

Verifiche mirate concluse: 26 test servizi/HTTP/stato condiviso superati
(32.173 s); tre regressioni consolidamento/pubblicazione superate (65.388 s);
tre pipeline Git reali superate (224.609 s), più risoluzione revisionata
(126.133 s) e nuova fonte selettiva (77.336 s). Validatore: 19 test superati.
Le 18 prove core hanno superato le asserzioni funzionali, con un errore di
cleanup Windows; sette riprove dopo il retry bounded sono passate.

Installer finale `python installa.py --prova --dashboard`: superato, compresi
builder, recall, misura, sintesi, banco e hook. Compilazione Python, sintassi
JavaScript assemblato e controllo whitespace superati. Nessun nuovo pacchetto.
Il repository non configura un type checker o un linter Python dedicato.

Copertura misurata per modulo: **87% core Git** (616 statement, 79 mancanti),
**99% validatore integrazione** (131 statement, uno mancante). Non è coverage
dell'intero kit o del servizio. Le prove del servizio e della pipeline coprono
anche rami non inclusi in queste misure separate.

## Prove di integrazione

- Due clone e un remoto bare: modifiche disgiunte producono candidato integrato,
  push ordinario e convergenza del clone vivo; storico di entrambi conservato.
- Note diverse correlate: nessuna pubblicazione prima di una revisione legata
  alla chiave degli input e del perimetro. Nessun modello AI chiamato.
- Stessa nota: conflitto isolato, L conservato, remoto intatto. Revisione della
  copia, digest, gate, attestazione umana e successivo push/adozione verificati.
- Nuova fonte raw input selezionata: baseline esteso solo da quegli hash,
  pubblicazione attribuita senza includere altro.
- File estranei, index occupato, hash mutato, raw/eventi alterati, manifest
  incoerente, credenziali riconoscibili, file privati nella storia, hook/filtri,
  URL/opzioni/configurazioni pericolose: bloccati nelle fixture.
- Recovery: commit creato prima del salvataggio L, ack perso dopo l'ultimo
  tentativo, ack perso del branch PR, modifica locale dopo push, ripresa della
  sola adozione senza duplicare push o checkpoint.
- Byte del candidato confrontati con tree(C) prima e dopo la validazione;
  intento di push persistito prima della rete. OID candidati ancorati a ref
  locali dedicate, separati dal branch vivo.

## Prove renderizzate

Chrome DevTools ECC, viewport emulati e verificati via innerWidth/innerHeight:
1440×900 e 390×844. Runtime reale con fixture Git e push su bare locale mostra
`converged` e B/L/R/C; ripresa con consenso ed **Enter** restituisce lo stesso
checkpoint e mantiene un solo tentativo. UUID inesistente inviato dalla UI
produce errore recuperabile `sync_unvalidated`.

Preview reale: DB personale escluso per percorso, nessun marker del contenuto
personale esposto, consenso non preselezionato e configurazione disabilitata.
Stato di caricamento e pulsante disabilitato osservati durante la richiesta.
Mobile: nessun overflow, label collegate, controlli misurati almeno 44 px,
nessuna animazione e nessun campo password/token.

Altre fixture renderizzate: vault compatibile non Git con stato vuoto e comandi
disabilitati; vault legacy senza form di inizializzazione/pubblicazione; journal
sintetico `needs_decision` con istruzione, chiave e perimetro. Quest'ultima è una
fixture della sola presentazione: le prove con Git reale del medesimo stato
sono nei test della pipeline, non una pubblicazione del journal sintetico.

Artefatti: desktop.json, mobile.json, privacy.json, empty.json, pending.json e
legacy.json. Servizi e sole schede create per le prove sono stati chiusi.

## Correzioni emerse nelle verifiche

La review ha trovato e fatto correggere il rischio di validare byte diversi da
C e il recovery dell'ack perso al terzo tentativo. Regressioni dedicate incluse.
Le prime esecuzioni sotto carico hanno mostrato attesa test apply di 12 secondi
insufficiente e un cleanup directory Windows transitorio: ora attesa terminale
bounded e retry limitato del solo cleanup. La prima suite generale era stata
importata durante l'aggiunta di initialize e conservava la vecchia mappa route;
la suite definitiva è stata avviata sul sorgente stabile senza carichi pesanti
paralleli, ma non ha restituito un esito completo. Questo limite resta aperto,
senza trasformare il risultato delle prove mirate in un PASS della suite intera.

## Limiti materiali

Creazione repository remoto e apertura/merge PR manuali. Visibilità dichiarata
dall'utente; Git verifica autenticazione e permessi al tentativo. Helper supportati:
manager/manager-core e SSH agent; helper shell personalizzati non eseguiti.
Audit automatico limitato a 128 commit e 64 MiB di blob unici; manifest richiesto
anche nella storia. Il rilevamento di pattern di credenziali non è uno scanner
universale di segreti. Correlazione conservativa, nessuna prova di assenza di
contraddizioni semantiche. Nessun audit screen reader o cross-browser.

Nessuno smoke GitHub dei dati eseguito: manca un repository dati esplicitamente
scelto dall'utente. I push del codice usano soltanto il branch del kit autorizzato.
Pubblicazione continuativa e receiver restano disabilitati e distinti dal passo 7.

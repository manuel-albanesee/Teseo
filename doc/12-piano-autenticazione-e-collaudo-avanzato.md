# 12 — Piano: autenticazione reale e collaudo avanzato con GitHub

Stato: piano, non implementato. Nasce dalle lacune dichiarate nel [rapporto di collaudo](evidence/step-11/collaudo-github.md) (repository privato o con branch protetto, SSH, due account GitHub distinti, gestori di credenziali veri di Windows e macOS) e dalla rilettura del codice che quelle lacune hanno provocato. Prosegue il punto 4 di [11](11-piano-completamento.md). Metodo e vincoli come negli altri passi: nessuna nuova dipendenza, stile compatto, commenti e messaggi in italiano, un branch `codex/<scopo>` per intervento.

## Premessa: che cosa è emerso e che cosa va corretto nel rapporto

Il collaudo del 2026-10-29 ha usato l'helper `store` con la credenziale della sessione: **non ha provato** i gestori di credenziali che gli utenti hanno davvero. La rilettura di `kit/dashboard/git_sync.py` mostra che il supporto aggiunto (lista di helper ammessi) è provato solo con test unitari e, per come gli strumenti reali scrivono la configurazione, **probabilmente non basta**:

| # | Fatto verificato nel codice o con gli strumenti | Conseguenza |
| --- | --- | --- |
| 1 | `_global_values` legge solo `~/.gitconfig`; l'ambiente di Git è ripulito con `GIT_CONFIG_NOSYSTEM=1` e `GIT_CONFIG_GLOBAL=/dev/null` | L'helper configurato a livello di **sistema** non si vede: Git for Windows installa `credential.helper=manager` in `etc/gitconfig`, Xcode/Command Line Tools impostano `osxkeychain` nel gitconfig di sistema. Chi non ha riscritto l'helper nel proprio file riceve `git_auth` |
| 2 | Lo stesso vale per `~/.config/git/config` (XDG), dove molti utenti Linux tengono la configurazione | Helper non letto |
| 3 | `gh auth setup-git` scrive chiavi **per URL** (`[credential "https://github.com"]`) con un primo valore vuoto e un percorso assoluto: `helper =` poi `helper = !/usr/local/bin/gh auth git-credential` (verificato con `gh` in una HOME vuota). Il codice legge solo la chiave `credential.helper`, la vuole a valore unico e ammette solo la stringa esatta `!gh auth git-credential` | Il supporto a `gh` dichiarato nel rapporto **non si attiva** con la configurazione reale di `gh`: va considerato non verificato |
| 4 | Con più valori (reset vuoto + helper) la lettura restituisce «nessun helper» (`len(values) == 1`) | Stessa conseguenza dei punti 1–3 |
| 5 | `StrictHostKeyChecking=yes` con `BatchMode`: un host non presente in `known_hosts` fallisce, ma `Host key verification failed` non è tra le stringhe classificate e diventa il generico `git_failed` | Nessuna indicazione utile all'utente su SSH |
| 6 | Un repository privato senza accesso risponde `Repository not found` (come se non esistesse); un token senza scope di scrittura o revocato dà 403 o `Invalid username or token`; un ruleset dà `GH013: Repository rule violations found`; un branch protetto `GH006` | Solo alcuni messaggi sono classificati; gli altri finiscono in `git_failed` |
| 7 | L'autosync richiede la modalità `direct` (`enable_automatic`) | Con un branch protetto il push diretto non è possibile e oggi non c'è un percorso guidato |
| 8 | `GIT_TERMINAL_PROMPT=0` e `GCM_INTERACTIVE=Never` sono forzati | Un gestore di credenziali non può chiedere nulla: le credenziali vanno memorizzate **prima**, e il prodotto deve dirlo |

Il rapporto `step-11` va letto con questa correzione: «helper noti ammessi» significa lista nel codice, non verifica con i gestori reali.

## Obiettivo e criteri di uscita

Un utente su Windows, macOS o Linux, con la configurazione di credenziali che ha già (GCM, `osxkeychain`, `libsecret`, `store`, `cache`, `gh`, chiavi SSH), con repository privato, token a scope limitato o branch protetto, ottiene una pubblicazione riuscita **oppure** un errore classificato con l'azione da compiere, senza mai esporre credenziali. Criteri di uscita: (a) fasi A–C completate; (b) matrice di collaudo della fase B verde su tre sistemi; (c) controllo di igiene dei segreti senza reperti; (d) `doc/09` e il rapporto aggiornati con la matrice dei gestori provati e dei limiti.

## Fase A — Individuare la configurazione reale (codice)

| Intervento | File | Come | Esempio da seguire |
| --- | --- | --- | --- |
| A1. Leggere gli scope giusti | UPDATE `kit/dashboard/git_sync.py` | Invece del solo `~/.gitconfig`, interrogare Git per **sistema**, **globale** e **XDG** con `git config --system`/`--global --no-includes` (mai `--local`, mai file del vault); ordine di precedenza di Git (sistema < XDG < globale). L'ambiente dei comandi di lavoro resta ripulito: cambia solo come si sceglie l'helper | `_global_values` (stessa invocazione sicura `_invoke`, `check=False`, tetto di 1 MiB sul file) |
| A2. Chiavi per URL e reset | UPDATE `git_sync.py` | Considerare `credential.helper` e `credential.<url>.helper` quando l'URL del remoto corrisponde (schema+host, `useHttpPath` ignorato); un valore vuoto azzera i precedenti; vale l'ultimo non vuoto | Semantica documentata di `gitcredentials(7)`; test con configurazioni scritte da `gh auth setup-git` |
| A3. Forme ammesse | UPDATE `git_sync.py` (`_CREDENTIAL_HELPERS`) | Nomi semplici (`manager`, `manager-core`, `wincred`, `osxkeychain`, `libsecret`, `store`, `cache`) **e** percorsi assoluti a file eseguibili con basename in un elenco chiuso (`git-credential-manager`, `git-credential-manager-core`, `git-credential-osxkeychain`, `git-credential-libsecret`, `gh` con argomenti esatti `auth git-credential`, anche con prefisso `!`). Nessun altro argomento, nessun altro comando | `_credential_helper` attuale; stessa idea di `_executable` (solo percorsi assoluti, mai cartella corrente) |
| A4. Classificazione degli errori | UPDATE `git_sync._invoke` | Nuovi codici: `git_hostkey` (`host key verification failed`), `git_not_found` (`repository not found`, ambiguo con repository privato senza accesso), `git_auth` anche per `invalid username or token` e `support for password authentication was removed`; `git_policy` anche per `GH006`, `GH013`, `protected branch update failed`, `at least 1 approving review` | Mappa stringhe già presente (`git_push_rejected`, `git_auth`, `git_network`, `git_policy`) |
| A5. Messaggi con la prossima azione | UPDATE `kit/dashboard/server.py`, `sync_ui.py`, `kit/graph/teseo_git.py` | Per ogni codice, un messaggio fisso con il rimedio (es. «autenticati una volta con `git ls-remote <url>` nel terminale: il servizio non può chiedere la password», «aggiungi github.com a `known_hosts`»). Mai testo grezzo di Git | Mappa errore → stato in `sync_service` e `autosync._blocked` |
| A6. Comando di diagnosi | CREATE sottocomando `diagnosi` in `kit/graph/teseo_git.py`, metodo in `autosync.py` | Stampa quale helper e da quale scope viene scelto, se SSH o HTTPS, l'esito di un `ls-remote` classificato; nessun segreto, nessun URL con credenziali | `Autosync.status()` |
| A7. Branch protetto | UPDATE `sync_service.py`, `autosync.py`, UI | Su `git_policy` proporre il percorso già esistente a PR (`mode=pr`, branch proposto e link di confronto); l'autosync resta `direct` e si ferma con un messaggio che lo dice. La creazione automatica della PR è il punto 7 di `doc/11` | Modalità `pr` di `SyncService` |

Test di fase A (`tests/test_dashboard_git_sync.py`, stile esistente con HOME e `gitconfig` temporanei): configurazioni reali scritte da `gh auth setup-git`, GCM e `osxkeychain`; gitconfig di sistema simulato con `GIT_CONFIG_SYSTEM`; XDG; reset vuoto; rifiuto di helper non ammessi; messaggi per ogni nuovo codice.

## Fase B — Collaudo automatizzato e ripetibile

Un workflow `collaudo-avanzato.yml` con avvio manuale (`workflow_dispatch`) e `script/collaudo_github.py` esteso. Usa un repository privato e un secondo account (o utente macchina) creati dal proprietario, con token a scope minimo conservati come segreti del repository.

| Scenario | Come | Esito atteso |
| --- | --- | --- |
| B1. Repository privato | `--url` del repository privato; il token entra nel gestore **reale** del runner con `git credential approve` (Windows: GCM `manager`; macOS: `osxkeychain`; Linux: `store`, `cache` e `gh auth setup-git`), mai in variabili lette dal prodotto | Tutti gli scenari S01–S09 verdi |
| B2. Credenziale revocata o scaduta | token cancellato prima di un `post` | `git_auth` con messaggio e rimedio; commit locale conservato; `riprendi` riesce dopo il ripristino |
| B3. Token senza scrittura | token fine-grained di sola lettura | `git_auth` o `git_policy` classificato, nessun push, nessuna perdita |
| B4. Branch protetto | ruleset che richiede PR su `main` e branch dati protetto | `git_policy` con il rimedio PR (A7); nessun tentativo di forzare |
| B5. SSH | chiave di deploy con scrittura nell'agente, `known_hosts` con le chiavi host di GitHub fissate dall'endpoint `meta`; poi un host key volutamente sbagliato | pubblicazione riuscita; con chiave sbagliata `git_hostkey`, mai accettazione silenziosa |
| B6. Due account | Alice e Bob con token di due account diversi e identità Git diverse (anche non coincidenti con l'account) | autori nel grafo dall'identità Git, non dall'account; nessun conflitto di permessi |
| B7. Igiene dei segreti | dopo ogni scenario, ricerca delle sottostringhe dei token in `.teseo/local`, `.git/config`, `autosync.sqlite`, journal, output di `teseo_git.py`, annotazioni della CI | nessuna occorrenza; i token sono mascherati nei log del workflow |

Struttura del workflow: matrice `os` (`ubuntu`, `windows`, `macos`) × gestore; ogni job prepara la HOME, memorizza la credenziale nel gestore, esegue lo script, carica il rapporto come annotazioni (come `script/ci_riassunto.py`, perché i log completi non sono leggibili da questa sessione). Nessun segreto nei fork (`pull_request` non lo riceve): solo `workflow_dispatch` sul repository principale.

## Fase C — Prove su macchine reali (manuali)

Non automatizzabili del tutto: GCM può aprire il browser alla prima autenticazione, `osxkeychain` può chiedere lo sblocco, `libsecret` richiede una sessione desktop. Una scheda per sistema (`doc/evidence/step-12/`) con: versione di Git e del gestore, comando di autenticazione iniziale, esito degli scenari B1, B2 e B5, e screenshot o log **senza segreti**. Criterio: il messaggio di A5 porta l'utente dal fallimento alla riuscita senza leggere il codice.

## Che cosa serve da chi possiede gli account

Il proprietario deve: creare un repository **privato** di prova e un secondo account GitHub (o un utente macchina) con accesso al repository; creare token fine-grained limitati a quel repository (scrittura per Alice, sola lettura per B3, scrittura per Bob) e una chiave di deploy; configurare il ruleset di B4; inserire i segreti `TESEO_COLLAUDO_TOKEN_A`, `_B`, `_RO` e la chiave SSH come segreti del repository; consentire l'uso di GitHub Actions con minuti Windows e macOS. Da questa sessione non posso creare account, token né regole di protezione.

## Rischi

| Rischio | Probabilità | Impatto | Mitigazione |
| --- | --- | --- | --- |
| Allargare la lettura della configurazione (A1–A3) apre la porta a helper non voluti | Media | Alto | Solo scope di utente e sistema (mai repository o vault), elenco chiuso di basename, percorsi assoluti esistenti, nessun argomento extra, test di rifiuto per ogni forma ostile |
| I token finiscono nei log o nel disco | Bassa | Alto | B7 obbligatorio e bloccante; mascheramento dei segreti nel workflow; nessuna URL con credenziali (`validate_remote` le rifiuta già) |
| I runner ospitati non hanno un gestore sbloccato (macOS keychain, Windows GCM) | Media | Medio | Provare presto B1 su un job di prova; in alternativa keychain temporanea creata dal job; la fase C copre ciò che resta |
| Costi e tempi (Windows 20–27 minuti a suite) | Alta | Basso | Il workflow esegue solo lo script di collaudo (pochi minuti), non l'intera suite |
| Un ruleset troppo severo blocca anche il collaudo | Media | Basso | Branch dati dedicato con regola propria; `main` protetto solo per B4 |

## Verifica e complessità

- Fase A: `python -m unittest discover -s tests -p "test_dashboard_git_sync.py" -v` più `ruff check .` e `mypy`; poi la CI a nove job.
- Fase B: esito del workflow `collaudo-avanzato.yml` su tre sistemi con rapporto in `doc/evidence/step-12/`.
- Fase C: schede compilate per i tre sistemi.

| Fase | Complessità | Dipende da |
| --- | --- | --- |
| A | M (modifica mirata di un modulo sensibile, molti test) | — |
| B | L (account, segreti, matrice, igiene dei segreti) | A, e dal proprietario per gli account |
| C | M (tempo su macchine reali) | A, B |

Ordine: A (con i test), poi B su un solo sistema per validare la struttura, poi i tre sistemi, poi C. A5 e A6 possono uscire prima di B perché aiutano già gli utenti reali.

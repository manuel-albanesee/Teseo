# Collaudo con un repository GitHub reale (doc/11, punto 4)

Data: 2026-10-29. Script: [`script/collaudo_github.py`](../../../script/collaudo_github.py). Esito: **9 scenari su 9 superati** sul repository reale `manuel-albanesee/Teseo-collaudo`, dopo aver corretto due difetti trovati dal collaudo stesso (sotto).

## Condizioni

- Repository GitHub **pubblico**, creato dall'autore per il collaudo e contenente solo dati sintetici (il vault d'esempio del kit). Da cancellare a fine collaudo: dalla sessione non ho strumenti per farlo né per cancellare i branch (la policy Git della sessione rifiuta le cancellazioni di ref).
- Due persone simulate con due HOME distinte (`Alice`, `Bob`) e due cloni del vault; un terzo clone per lo scenario delle note correlate. I comandi sono quelli delle persone: `installa.py --collabora --si`, `teseo_git.py pre|post|avvisi|riprendi`, e la dashboard in locale con le sue rotte HTTP.
- Ambiente: Linux in container, Git 2.43.0, Python 3.13, uscita verso GitHub attraverso il proxy della sessione. L'autenticazione di Git è quella dell'ambiente (credential helper `store` con la credenziale della sessione, proxy per le richieste): lo script non legge né salva credenziali.
- Un solo account GitHub per l'accesso reale; Alice e Bob si distinguono per l'identità Git, non per l'account.

## Scenari

| # | Scenario | Esito | Che cosa è stato verificato |
| --- | --- | --- | --- |
| S01 | Installazione e primo push | OK | `installa.py --collabora --branch … --si` crea il branch sul remoto con 14 file condivisi (manifest, note, nessun file locale come `.graph/` o `.claude/`) e attiva l'autosync |
| S02 | Clone di Bob | OK | vault vuoto + remoto popolato: clone allineato (stesso HEAD), kit installato, autosync attivo |
| S03 | `pre`/`post` con attribuzione | OK | commit di Alice sul remoto con autore `Alice` e trailer `Teseo-Skill: ingest`, `Teseo-Agent: claude` |
| S04 | Avviso e pull | OK | `avvisi` di Bob: `behind` con 1 commit, senza toccare HEAD; `pre` lo riceve; poi `current` |
| S05 | Integrazione senza decisione | OK | note distinte e voci concorrenti di `log.md`: il secondo `post` integra e pubblica, senza marcatori di conflitto |
| S06 | Autori e modifica dalla dashboard | OK | la nota di Bob risulta creata da `Bob` nel grafo di Alice; anteprima → apply → pubblicazione con trailer `Teseo-Skill: dashboard` sul remoto |
| S07 | Offline e ripresa | OK | con un proxy irraggiungibile il `post` esce con 3 (`waiting`), il commit resta locale e non è sul remoto; `riprendi` lo pubblica |
| S08 | Stessa nota modificata da due persone | OK | il secondo `post` si ferma con `git_conflict` (exit 2); il vault vivo di Bob e il remoto restano intatti |
| S09 | Note correlate concorrenti | OK | la pubblicazione si ferma in `needs_decision`, il vault vivo resta intatto |

Tempi: 73,7 secondi per l'intera sequenza (3–13 secondi per scenario).

## Difetti trovati dal collaudo e corretti

1. **Credential helper di macOS e Linux ignorati.** `git_sync` accettava solo `manager` e `manager-core` (Windows): con `osxkeychain`, `libsecret`, `store`, `cache` o `gh` ogni push dava `git_auth`. Ora si accettano solo helper noti, scelti nel `~/.gitconfig` dell'utente: `manager`, `manager-core`, `wincred`, `osxkeychain`, `libsecret`, `store`, `cache` e la forma esatta `!gh auth git-credential`. Ogni altro valore (percorsi, comandi `!…`, argomenti extra) resta ignorato (test in `tests/test_dashboard_git_sync.py`).
2. **Proxy e certificati scartati.** L'ambiente dei processi Git veniva ripulito da ogni variabile: dietro un proxy aziendale ogni fetch e push falliva (e così in questa sessione). Ora passano solo `HTTP(S)_PROXY`, `ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `GIT_SSL_CAINFO`, `GIT_SSL_CAPATH`, `CURL_CA_BUNDLE`; `GIT_SSL_NO_VERIFY`, `GIT_CONFIG_*`, `GIT_ASKPASS` e le altre `GIT_*` no, e la verifica TLS resta obbligatoria.

## Che cosa il collaudo non copre

- Repository privato, branch protetto, regole di repository (`git_policy`), autenticazione SSH, chiavi o token con scope limitati, e due account GitHub distinti.
- Windows e macOS con un vero gestore di credenziali (`manager`, `osxkeychain`): qui la credenziale passa dal helper `store`; la lista degli helper è provata con test unitari, non con questi gestori.
- Editor non cooperanti e client AI autenticati (punti 5 e 6 del piano).
- Più di tre cloni o carichi grandi; il remoto contiene poche note.

# 11 — Piano per chiudere i punti aperti

Stato: punti 1–4, 7, 11 (tranne il build tollerante) e 12 chiusi (vedi «Esiti» in fondo); restano 5, 6, 8, 9 e 10. Parte dallo stato descritto in [08](08-analisi-avanzamento.md) e [10](10-editor-grafo-e-autori.md): le fasi 1–7 della roadmap collaborativa sono consegnate e provate su Linux con remoto Git locale. Qui sono raccolti i punti che restano aperti, in ordine di dipendenza, con file, rischi, verifica e stima. Ogni voce è consegnabile da sola (un branch `codex/<scopo>`), senza nuove dipendenze, con stile compatto e commenti in italiano.

## Riepilogo

| # | Punto aperto | Perché conta | Complessità |
| --- | --- | --- | --- |
| 1 | CI su Linux, Windows e macOS — **fatto (9 job, verdi dopo le correzioni sotto)** | Il codice nuovo è provato solo su Linux; nessuna CI nel repo | M |
| 2 | Qualità statica (`mypy` Windows, `ruff`) — **fatto** | 4 errori `mypy` e ~360 rilievi di stile coprono eventuali regressioni | M |
| 3 | Apply POSIX: durabilità e macOS — **fatto (macOS solo simulato)** | Niente `fsync` della cartella; su macOS nessun controllo dei volumi di rete | S |
| 4 | Collaudo reale con GitHub e due cloni — **fatto (9 scenari su 9, con due difetti corretti)** | Tutto il flusso è provato solo con un remoto bare locale | M |
| 5 | Collaudo con editor non cooperanti (Obsidian) | L'esclusione degli scrittori esterni è solo dichiarata | M |
| 6 | Client AI autenticati (passo 4) | L'automazione nativa è non verificata, resta il fallback manuale per tre client | L |
| 7 | Apertura delle PR (passo 6) — **fatto** | La creazione del repository c'è (`--crea-remote`), la PR è ancora manuale | S |
| 8 | Adozione dei vault legacy ed export diagnostico (passo 2) | Dichiarati futuri in `doc/08` | M |
| 9 | Editor: creare, rinominare, eliminare pagine | Il mapping `page.renamed` è bloccato | L |
| 10 | Scala: disegno con migliaia di nodi, snapshot selettivo | Tetto 500 nodi nel disegno e 64 MiB di snapshot | L |
| 11 | Rifiniture dell'autosync — **fatto (resta aperta la sola decisione sul build tollerante)** | Un fetch per sessione, `valid` dell'editor, `cleanup_candidate` su POSIX | S |
| 12 | Decisione sull'apply automatico — **scritta, da confermare** ([13](13-decisione-apply-automatico.md)) | Disabilitato per scelta: va chiusa come decisione, non lasciata aperta | S |

Ordine consigliato: 1 → 2 → 3 (fondamenta e regressioni), poi 4 → 5 (collaudo), poi 7 e 11 (piccoli), poi 8, 6, 9, 10 (nuove capacità), 12 alla fine con i dati del collaudo.

## 1 — CI su tre sistemi operativi

- **Cosa**: un workflow GitHub Actions con matrice `ubuntu-latest`, `windows-latest`, `macos-latest` e Python 3.10, 3.12, 3.13 (il progetto dichiara ≥ 3.10); esegue `python -m unittest discover -s tests -v` e `python installa.py --prova`. Git è preinstallato sui runner.
- **File**: CREATE `.github/workflows/test.yml`; UPDATE `CONTRIBUTING.md` (come leggere la matrice), `doc/08` (esito). Il vault installato esclude `.github/` dai dati condivisi (`LOCAL` in `installa`/autosync): non interferisce.
- **Rischi**: i test Windows costano (≈75 ms per processo Git) e i percorsi lunghi sono già gestiti da `_shortpath`; alcuni test dipendono da `mkfifo`/permessi POSIX → mitigazione: `skipUnless` espliciti, come nel resto della suite. Media probabilità di primi fallimenti su macOS (filesystem case-insensitive, `/private/var` come realpath).
- **Verifica**: il workflow verde sui tre sistemi su un branch di prova; ogni fallimento classificato (piattaforma, difetto, ambiente) come nella prima verifica POSIX.
- **Complessità**: M (la stesura è breve, la correzione dei fallimenti no).

## 2 — Qualità statica

- **mypy**: i 4 errori sono attributi solo Windows in `contracts.py` (`winreg`, `IO_REPARSE_TAG_MOUNT_POINT`). Proteggerli con `if sys.platform == 'win32':` (che mypy capisce) o `getattr`, mantenendo il comportamento. Esempio nel modulo: `contracts.is_junction` già usa `getattr(path, 'is_junction', None)`.
- **ruff**: ~360 rilievi su regole non scelte dal progetto (`ruff.toml` ignora solo E701/E702). Decidere una policy: (a) fissare `select` esplicito in `ruff.toml` alle sole regole volute (`E`, `F`, `W`), (b) correggere in blocco quelle automatiche (`I001`, `FURB167`), (c) lasciare fuori le altre con motivazione. Nessuna correzione di stile mescolata a modifiche funzionali.
- **File**: UPDATE `ruff.toml`, `mypy.ini` se serve, `kit/dashboard/contracts.py`; modifiche meccaniche a molti file in un commit separato.
- **Rischi**: il riordino degli import tocca i file copiati nei vault (`kit/graph/*`, esenti da E731/E741/F401 per scelta): escluderli esplicitamente. Bassa probabilità di regressioni se la suite resta verde.
- **Verifica**: `ruff check .` e `mypy` senza errori su Linux, Windows e macOS (punto 1).
- **Complessità**: M.

## 3 — Apply POSIX: durabilità e macOS

- **fsync della cartella**: dopo `rename`/`link` in `ontology_apply._replace` e `_move_new`, `os.fsync` sul descrittore della cartella contenitore (su POSIX; su Windows non si fa). Esempio: `ontology_apply._write_stage` fa già `flush`+`fsync` sul file.
- **macOS**: `_filesystem` oggi legge `/proc/self/mountinfo`; su Darwin usare `os.statvfs` non basta (nessun tipo), quindi parsare l'output di `mount` (tipo e punto di mount, con `shell=False` e ambiente ripulito come in `git_sync._env`) e riusare `_REMOTE_FS` più `smbfs`/`nfs`/`afpfs`. Dove non è determinabile resta «nessun controllo», dichiarato.
- **File**: UPDATE `kit/dashboard/ontology_apply.py`, `tests/test_apply_posix.py` (casi mockati per `mount` e per l'ordine fsync).
- **Rischi**: `fsync` rallenta di poco ogni file; su filesystem che lo rifiutano → catturare `OSError` ed ignorare solo `EINVAL`. Bassa.
- **Verifica**: `python -m unittest discover -s tests -p "test_apply_posix.py"` e la suite di apply; esecuzione su macOS dal punto 1.
- **Complessità**: S.

## 4 — Collaudo reale con GitHub e due cloni

- **Cosa**: una procedura riproducibile con un repository GitHub privato di prova e due cloni (due persone o due account): ingest di A, `pre` di B, modifica concorrente della stessa nota (conflitto), note correlate (decisione), modifica dall'editor del grafo con pubblicazione `dashboard`, avviso di sessione, autori nel grafo, offline.
- **File**: CREATE `doc/evidence/step-11/collaudo-github.md` (checklist con esito e data), CREATE `script/collaudo_github.py` (prepara i due cloni, esegue gli scenari con `teseo_git.py` e stampa un rapporto; richiede token già configurato in `gh`, non lo legge né lo salva); UPDATE `doc/08`, `doc/09`.
- **Rischi**: richiede autorizzazione esplicita per creare e cancellare il repository di prova; credenziali mai nei log (il progetto delega a Git/gh, vedi `git_sync._env`). Alta probabilità di scoprire casi di autenticazione e protezione del branch non coperti dai test.
- **Verifica**: tutti gli scenari con esito atteso; i difetti trovati diventano test di regressione sul remoto bare.
- **Complessità**: M.

## 5 — Editor non cooperanti

- **Cosa**: misurare, con Obsidian reale che salva durante `post` e durante un apply, che hash e HEAD fermino la pubblicazione e che il recovery non perda dati. Documentare i risultati senza promettere esclusione.
- **File**: CREATE `doc/evidence/step-11/editor-non-cooperanti.md`; eventuali test con un processo scrittore (esiste già un test di processo esterno in `tests/test_dashboard_storage.py`, stile da seguire). Nessuna modifica del codice prevista salvo difetti trovati.
- **Rischi**: non automatizzabile del tutto (Obsidian è interattivo); alto valore, probabilità media di trovare finestre di race nel link/rename POSIX.
- **Verifica**: scenari ripetuti 20 volte senza perdita di byte né sovrascritture.
- **Complessità**: M.

## 6 — Client AI autenticati (passo 4)

- **Cosa**: per Claude, Codex e Copilot, provare davvero le skill ingest/lint con `pre`/`post` e gli hook, con client autenticati; confermare o correggere la parte «automazione nativa non verificata» di `doc/08`. Dove il client non chiama `post`, il `post` del ciclo successivo (`pre` rifiuta lavoro non pubblicato) copre già il caso: misurare quanto spesso accade.
- **File**: UPDATE `kit/skills/*/SKILL.md` e `kit/vault/*.md` se i passaggi vanno resi più espliciti; CREATE `doc/evidence/step-11/client-ai.md`; test unitari solo per ciò che si può simulare (formato degli hook).
- **Rischi**: dipende da versioni e permessi dei client (i hook Copilot e Codex cambiano formato); media probabilità di rotture dopo aggiornamenti → fissare nel rapporto le versioni provate.
- **Verifica**: per ogni client, un ciclo ingest→post visibile nel log del remoto con i trailer `Teseo-Skill` e `Teseo-Agent`.
- **Complessità**: L (tempo di prova, non di codice).

## 7 — Apertura delle PR (passo 6)

- **Cosa**: in modalità «PR» il link di confronto c'è; aggiungere l'apertura opzionale con `gh pr create` (titolo e corpo dai trailer e dal manifest), solo con conferma esplicita e con `gh` autenticato, come `installa --crea-remote` (`installa.py:371-381`: controllo `gh`, errore chiaro).
- **File**: UPDATE `kit/dashboard/sync_service.py` (azione `open-pr`), `kit/dashboard/sync_ui.py` (pulsante accanto al link), `kit/dashboard/server.py` (rotta e stati), CREATE test in `tests/test_dashboard_git_sync.py` con `gh` finto.
- **Rischi**: il corpo della PR non deve contenere testo delle note (privacy): solo elenco di percorsi e conteggi. Bassa.
- **Verifica**: test con `gh` simulato; prova manuale sul repository del punto 4.
- **Complessità**: S.

## 8 — Adozione dei vault legacy ed export diagnostico (passo 2)

- **Adozione**: oggi i vault senza `.teseo/project.json` sono in sola lettura (`legacy_readonly`) e `--dashboard` inizializza solo cartelle vuote. Offrire un'adozione esplicita (anteprima, backup, manifest, consenso) simile a `installa --collabora` con vault già in uso (decisione D5 della roadmap, già accettata).
- **Export diagnostico**: un pacchetto locale (JSON) con stato, problemi, versioni e conteggi, senza testo delle note né percorsi assoluti, per le segnalazioni.
- **File**: CREATE `kit/dashboard/adoption.py`, `kit/dashboard/diagnostics_export.py` (esiste `diagnostics.py` per i log: seguirne le convenzioni); UPDATE `server.py`, `read_api.py`, UI; test su vault sacrificabili come `tests/test_dashboard_storage.py`.
- **Rischi**: un'adozione scorretta scrive nel vault: stessa prudenza dell'apply (snapshot, journal, rollback). Probabilità media, impatto alto → riusare `Journal`.
- **Verifica**: adozione e rollback su vault di prova con raw immutabili invariati; l'export non contiene byte delle note (test di assenza).
- **Complessità**: M.

## 9 — Creare, rinominare, eliminare pagine dall'editor

- **Cosa**: nuove operazioni `create_page`, `rename_page`, `delete_page` nell'editor del grafo. La rinomina aggiorna i wikilink nel corpo e nel frontmatter delle altre pagine, `index.md` e le chiavi di `relazioni_dettaglio`, e genera l'evento condiviso `page.renamed` (oggi il mapping è bloccato in `ontology_apply._candidate` con `shared_mapping_unavailable`). L'eliminazione richiede che non restino link entranti (o li segnala).
- **File**: UPDATE `kit/dashboard/graph_edit.py` (operazioni multi-file: oggi l'editor tocca **una** pagina), `kit/dashboard/ontology_apply.py` (candidato con più file e mapping eventi), `kit/dashboard/shared_state.py` (evento), UI; test in `tests/test_graph_edit.py` e `tests/test_shared_pipeline.py`.
- **Rischi**: è il punto più delicato: riscrivere il corpo di altre pagine rompe la regola «una modifica = una pagina» e il confronto con gli editor non cooperanti; rinomine concorrenti fra cloni. Alta probabilità di casi limite (link con alias, sezioni, maiuscole) → riusare `bersaglio()` del builder e la verifica per riparsing.
- **Verifica**: rinomina su vault con link in corpo, frontmatter e tabelle; doppio import senza effetti; due cloni che rinominano la stessa pagina → decisione, non sovrascrittura.
- **Complessità**: L.

## 10 — Scala

- **Disegno**: oltre 500 nodi il layout O(n²) non è fluido. Passare a Barnes-Hut (quadtree) nello stesso `graph_ui.py`, livello di dettaglio (niente etichette e frecce sotto una soglia di zoom, già parziale), e pesi per cluster; misurare con un vault sintetico di 2000 e 5000 nodi (`tests/dashboard_graph_fixture.py` parametrico). Alzare il tetto solo con i numeri in mano.
- **Snapshot selettivo**: `capture_snapshot` legge tutto il perimetro in memoria con tetto 64 MiB (`snapshot_too_large`); rendere le fonti binarie di `raw/` hash-only (percorso e digest, non byte) dove il consumatore non le legge. Esempio nel modulo: `is_local_only` già distingue i file che restano sul disco.
- **File**: UPDATE `kit/dashboard/graph_ui.py`, `kit/dashboard/storage.py` (snapshot a due livelli), test in `tests/test_dashboard_storage.py`.
- **Rischi**: lo snapshot è il perno di journal, backup e confronto raw: un cambio lì tocca tutto → feature flag e doppia verifica finché la suite non è verde su entrambi i percorsi. Media.
- **Verifica**: vault con PDF da 200 MiB che oggi blocca l'autosync e dopo la modifica no; layout assestato in meno di 3 s a 2000 nodi in Chromium.
- **Complessità**: L.

## 11 — Rifiniture dell'autosync

- **Avviso di sessione**: un fetch a ogni avvio (fino a 8 s). Aggiungere una cache a tempo (es. 10 minuti) in `.teseo/local/` per non ripeterlo a sessioni ravvicinate; nessuna scrittura sulle note.
- **`valid` dell'editor**: oggi un problema preesistente altrove blocca ogni modifica perché il grafo si ricostruisce solo da un vault valido. Valutare un build «tollerante» che pubblica la generazione con i problemi elencati come avvisi; è un cambio di contratto del builder (`GraphValidationError`), da decidere esplicitamente prima.
- **`cleanup_candidate` su POSIX**: aggiungere il test dei pack in sola lettura (oggi descritto per Windows in `doc/09`).
- **File**: UPDATE `kit/graph/avvisi.py`, eventuale `kit/graph/build_graph.py`, test in `tests/test_avvisi.py` e `tests/test_dashboard_git_sync.py`.
- **Rischi**: il build tollerante cambia una garanzia («un grafo invalido non sostituisce quello precedente»): da non fare senza decisione.
- **Verifica**: test della cache (due avvisi ravvicinati, un solo fetch) e dei pack read-only.
- **Complessità**: S.

## 12 — Apply automatico: decisione

- **Cosa**: oggi disabilitato per scelta (nessun flag lo abilita; `ontology_apply_automatic` e `external_writer_exclusion` restano falsi). Dopo i punti 4 e 5, decidere per iscritto: o resta disabilitato in modo permanente (documentare «non previsto»), oppure definire i criteri di qualifica (esclusione reale degli scrittori, recovery provato n volte, consenso per vault) e tenerli come gate di rilascio.
- **File**: UPDATE `doc/01-contratto-dati-operazioni.md` e `doc/08`; nessun codice se la decisione è «resta disabilitato».
- **Rischi**: abilitarlo senza esclusione reale degli editor può sovrascrivere lavoro non salvato. Alta gravità → default prudente.
- **Verifica**: la decisione è scritta e referenziata dai gate di rilascio.
- **Complessità**: S.

## Rischi trasversali

| Rischio | Probabilità | Mitigazione |
| --- | --- | --- |
| Il collaudo reale scopre difetti di autenticazione o protezione del branch | Alta | Fare il punto 4 presto; ogni difetto diventa un test sul remoto bare |
| Modifiche a snapshot/journal (punti 9 e 10) rompono recovery | Media | Un branch per punto, suite completa su tre sistemi (punto 1) prima di ogni merge |
| Divergenza fra Windows, Linux e macOS su rename, link e percorsi | Media | CI a matrice e `skipUnless` espliciti; nessuna promessa non misurata nei documenti |
| Interventi di stile mescolati alle modifiche funzionali | Media | Commit separati, nessun cambio di stile nei file copiati nei vault |

## Come si verifica il piano nel suo insieme

`python -m unittest discover -s tests -v`, `python installa.py --prova`, `ruff check .`, `mypy` sui tre sistemi (punti 1–2); smoke Playwright (`tests/dashboard_graph_smoke.js`, `tests/dashboard_autosync_smoke.js`); i rapporti di collaudo in `doc/evidence/step-11/` (punti 4–6) con data, versioni e esito; `doc/08` aggiornato a ogni voce chiusa.

## Esiti dei punti 1–3

- **1 — CI**: `.github/workflows/test.yml` (matrice `ubuntu`/`windows`/`macos` × Python 3.10, 3.12, 3.13; `ruff`, `mypy`, suite, `installa.py --prova`; identità Git di prova e `core.autocrlf=false`; riassunto dei test falliti come annotazioni con `script/ci_riassunto.py`). Il primo giro ha trovato difetti reali che i test su Linux/Python 3.13 non vedevano:
  - **Difetti reali**: (a) su **Python 3.10** ogni GET senza parametri dava 400, perché `parse_qs("", strict_parsing=True)` solleva `ValueError` fino a 3.10; (b) su **Windows con Python 3.10** `git_sync._executable` non trovava `git.exe`, perché `shutil.which` non prova `PATHEXT` per un percorso con cartella prima di 3.12 (tutto il flusso Git era inutilizzabile); (c) su **macOS** il registro rifiutava qualunque percorso sotto `/var` o `/tmp` perché link di sistema (`/var` → `/private/var`); (d) le date degli autori dipendevano dalla versione di Git (`Z` o `+00:00`).
  - **Difetti dei test (ambiente o piattaforma)**: percorsi temporanei non risolti su macOS, `Path.is_junction` assente su Python < 3.12, oggetti Git di sola lettura nella pulizia su Windows, timeout HTTP di 5 s e attese di 12 s troppo brevi sui runner Windows (la suite dura 20–27 minuti).
  - **Rinforzi**: `gc.auto=0` e `maintenance.auto=false` nei comandi Git del progetto (un `gc` in background faceva fallire la pulizia), polling della UI che ritenta il 503 ritentabile del journal.
  - Stato: tutti e 9 i job verdi (esecuzione sul commit `3b29c0f`); il 3.13 su Windows aveva un solo fallimento di temporizzazione, corretto con un'attesa più lunga nel test. Il passo diagnostico temporaneo per `git_unavailable` è stato tolto dal workflow.
- **2 — Qualità**: `ruff.toml` ora seleziona esplicitamente `E`, `F`, `W` (con E701, E702 ed E501 ignorati); l'insieme predefinito di ruff 0.16 dava ~390 rilievi di stile non voluti dal progetto. `mypy`: `winreg` dietro `sys.platform != "win32"` e `stat.IO_REPARSE_TAG_MOUNT_POINT` via `getattr`; 0 errori su Linux (su Windows `mypy` controlla anche il ramo `winreg`, da vedere in CI). `ruff check .` pulito.
- **3 — Apply POSIX**: `_fsync_directory` dopo rename e link (backup per primo); `_mount_table` legge `/proc/self/mountinfo` su Linux e `/sbin/mount` su macOS (percorso fisso, ambiente ripulito), con `afpfs` fra i filesystem di rete. Il parsing di macOS è provato su un output d'esempio; la CI su macOS passa, ma non ha un volume di rete da rifiutare, quindi il rifiuto reale resta non verificato.

## Esito del punto 4

Rapporto completo in [doc/evidence/step-11/collaudo-github.md](evidence/step-11/collaudo-github.md): `script/collaudo_github.py` ha eseguito 9 scenari contro `manuel-albanesee/Teseo-collaudo` (installazione, clone, attribuzione, avviso e pull, integrazione, autori e modifica dalla dashboard, offline e ripresa, stessa nota, note correlate), tutti superati. Ha trovato due difetti reali, corretti: i credential helper di macOS e Linux erano ignorati (solo Windows), e le variabili di proxy e certificati venivano scartate (nessun uso dietro un proxy aziendale). Non coperti: repository privato o con branch protetto, SSH, due account distinti, gestori di credenziali reali di macOS e Windows. Il repository di prova è pubblico con dati sintetici e va cancellato dall'autore.

## Esiti dei punti 7, 11 e 12

- **7 — PR**: `POST /sync/open-pr` (`SyncService.open_pull_request`) apre la pull request del branch proposto con `gh pr create`, solo con `confirm: true` e per un'operazione in `needs_approval` con branch proposto; titolo e corpo contengono operazione e OID, mai testo delle note; l'esito è idempotente (`pr_url` registrato); `gh` assente o non autenticato dà `sync_gh_missing` o `sync_gh_failed` con il rimedio. Pulsante nel pannello «Pubblicazione Git dei dati». Provato con una `gh` finta (argomenti, idempotenza, errori senza testo grezzo); non provato con `gh` e un repository reali.
- **11 — Rifiniture**: cache a tempo (10 minuti) dell'avviso di sessione in `.teseo/local/avvisi.json`, cancellata da `pre`, `post` e `riprendi`; offline e guasti non si memorizzano. Pack di sola lettura su POSIX: la rimozione dei candidati rende scrivibile anche la cartella che li contiene, ma solo dentro l'albero rimosso. **Non fatto di proposito**: il build «tollerante» dell'editor cambia la garanzia «un grafo invalido non sostituisce quello precedente» e richiede una decisione del proprietario.
- **12 — Apply automatico**: [decisione 13](13-decisione-apply-automatico.md), «non previsto», con i criteri per riaprirla. È una proposta: la conferma spetta al proprietario.

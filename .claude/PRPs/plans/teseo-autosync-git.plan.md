# Plan: Autosync Git — repository all'installazione, pull prima e commit+push dopo ogni skill

## Summary
Aggiunge un **autosync opt-in per vault**. `installa.py --collabora <remote>` crea o aggancia il
repository dati e registra il consenso. Le skill ingest, lint e fill-gaps chiamano
`python .graph/teseo_git.py pre` all'inizio e `post` alla fine.
- `pre`: fetch, fast-forward e rebuild del grafo.
- `post`: `build_graph --check`, commit attribuito (persona + agente + skill), integrazione isolata, push e adozione.

Riusa il motore esistente (`GitRepository`, `SyncService._advance`) senza abbassarne le garanzie.
Copre le fasi 1–3 di [teseo-collaborazione-roadmap.plan.md](teseo-collaborazione-roadmap.plan.md).

## User Story
Come autore di un vault condiviso, voglio che ogni ingest, lint o chiusura delle lacune parta
dall'ultima versione del repository e finisca pubblicata con il mio nome, così da non fare mai pull,
commit o push a mano.

## Problem → Solution
**Oggi:**
- `installa.py` non crea Git.
- Nessun hook usa Git.
- `publish` richiede la dashboard, `operation.validated` ed `exclusive_confirmed` (`kit/dashboard/sync_service.py:178-233`).
- Il push si blocca oltre 128 commit (`kit/dashboard/git_sync.py:601-603`).
- `log.md` va in conflitto a ogni ciclo concorrente.

**Dopo:**
- Un flag d'installazione, due comandi richiamati dalle skill, push incrementale e unione automatica di `log.md` e `index.md`.
- I conflitti reali sulle note restano alla dashboard.

## Metadata
- **Complexity**: Large
- **Source PRD**: N/A — roadmap `teseo-collaborazione-roadmap.plan.md`, fasi 1–3
- **PRD Phase**: Fasi 1–3
- **Estimated Files**: 16 (5 nuovi, 11 modificati)
- **Prerequisiti**: decisioni D1–D6 della roadmap confermate dall'utente

---

## UX Design

### Before
```
installa.py <vault> --dashboard            (solo cartella vuota)
crea repo GitHub a mano · git config · avvia dashboard
UI: preview → initialize → configure
client AI: /obsidian-wiki-ingest
UI: crea operazione · ricevuta · completa · sospendi editor · publish
per ricevere: UI check → receive (solo Windows)
```

### After
```
python installa.py <vault> --collabora https://github.com/org/vault-dati.git [--crea-remote]
  → mostra file condivisi ed esclusi → "Pubblicare? [s/N]" → init + primo push + autosync attivo
client AI: /obsidian-wiki-ingest
  0. teseo_git.py pre  → "ricevuti 3 commit da origin/main, grafo ricostruito"
  … ingest …
  N. teseo_git.py post → "pubblicato a1b2c3d (ingest, claude, Mario Rossi)"
conflitto sulla stessa nota → "da risolvere nella dashboard: Pubblicazione Git → Risolvi"
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Installazione | nessun Git | `--collabora URL` crea o aggancia il repo dati | Conferma interattiva o `--si` |
| Secondo collaboratore | non previsto | `installa.py <cartella-vuota> --collabora URL` clona e configura | Stesso comando |
| Inizio skill | niente | `teseo_git.py pre` | Exit 0/2/3 documentati nella skill |
| Fine skill | niente | `teseo_git.py post` | Dopo `--check` e log |
| Modifiche a mano in Obsidian | non pubblicate | `teseo_git.py post --skill manuale` (anche suggerito dal `pre` successivo) | |
| Dashboard | publish manuale | il pannello sync mostra "automatico: attivo" e le sessioni autosync | Resolve invariato |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `kit/dashboard/git_sync.py` | 82-137 | `_env`/`_invoke`: Git non interattivo, classificazione degli errori |
| P0 | `kit/dashboard/git_sync.py` | 419-501 | `checkpoint`/`find_checkpoint`: commit attribuito e recovery; i trailer si aggiungono qui |
| P0 | `kit/dashboard/git_sync.py` | 503-629 | `fetch`, `integrate`, `push`, `audit_history` |
| P0 | `kit/dashboard/git_sync.py` | 706-717, 805-868 | `adopt` fast-forward; `initialize_data_repository` |
| P0 | `kit/dashboard/sync_service.py` | 121-158, 178-378 | `configure`, `publish`, `_advance`, `_adopt`: macchina a stati da riusare |
| P0 | `kit/skills/obsidian-wiki-ingest/SKILL.md` | 21-40 | Procedura in cui inserire i passi 0 e finale |
| P1 | `kit/dashboard/storage.py` | 48-130, 229 | `_local_directory`, `assert_receiver_complete`, `VaultLock`, `capture_snapshot` |
| P1 | `installa.py` | 351-452, 523-552 | `installa()`, creazione del manifest, argparse |
| P1 | `kit/graph/teseo_sync.py` | all | Pattern dell'entrypoint CLI copiato in `.graph/` |
| P1 | `tests/test_dashboard_git_sync.py` | 1-60, 166-200, 300-310 | Fixture Git reali, remote bare, pulizia |
| P2 | `kit/dashboard/contracts.py` | 22-24, 126-134, 300-337 | `DEFAULT_SHARED_PATHS`, `ContractError`, `inspect_vault` |
| P2 | `kit/skills/obsidian-wiki-lint/SKILL.md`, `obsidian-wiki-fill-gaps/SKILL.md` | passi log | Punto di aggancio del `post` |
| P2 | `doc/06-pubblicazione-github.md` | 57-90 | Motivazioni del design manuale da superare nell'ADR |

## External Documentation
| Topic | Source | Key Takeaway |
|---|---|---|
| `git merge-file --union` | git-scm.com/docs/git-merge-file | Risolve gli hunk in conflitto tenendo entrambe le versioni; exit 0 con `--union`; `-p` scrive su stdout |
| `git rev-list A --not B` | git-scm.com/docs/git-rev-list | Elenca solo i commit non ancora pubblicati: base dell'audit incrementale |
| `gh repo create` | cli.github.com/manual/gh_repo_create | `gh repo create OWNER/NAME --private` crea senza push; richiede `gh auth status` ok |
| Trailer Git | git-scm.com/docs/git-interpret-trailers | Blocco `Chiave: valore` nell'ultimo paragrafo; leggibile con `%(trailers:key=…,valueonly)` |

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: kit/dashboard/sync_service.py:17-31 — funzioni private corte, stile compatto voluto (ruff E701/E702 ignorati)
def _fields(body,required,optional=()):
    if not isinstance(body,dict) or not set(required)<=set(body) or set(body)-set(required)-set(optional):
        raise ContractError('sync_request','Campi pubblicazione non validi')
```
Codici errore `snake_case` con prefisso del modulo (`sync_*`, `git_*`); i nuovi usano `autosync_*`. Messaggi in italiano, brevi, senza dati privati.

### ERROR_HANDLING
```python
# SOURCE: kit/dashboard/contracts.py:126-134
class ContractError(ValueError):
    def __init__(self, code, message, path=None): ...
    def as_dict(self): return {"code": self.code, "message": str(self), "path": self.path}
# SOURCE: kit/dashboard/sync_service.py:337-341 — mappa errore → stato persistito, mai eccezioni grezze all'utente
paused='waiting_auth' if code in ('git_auth','git_authentication') else 'waiting_network' if code in ('git_network','git_timeout') else 'needs_approval' if code in ('git_push_rejected','git_policy') else 'needs_resolution'
```

### LOGGING_PATTERN
Nessun logger: gli entrypoint stampano JSON su stdout e il messaggio su stderr, e usano i codici di uscita.
```python
# SOURCE: kit/graph/teseo_sync.py:31-38
    try:
        print(json.dumps(inspect_candidate(args.vault,args.candidate),ensure_ascii=False,indent=2));return 0
    except (ContractError,OSError,ValueError) as error:
        print(str(error),file=sys.stderr);return 2
```
L'installer usa `rapporto(nome, esito)` e `rapporto.avviso(...)` (`installa.py:300-320`).

### REPOSITORY_PATTERN (stato locale SQLite)
```python
# SOURCE: kit/dashboard/sync_service.py:45-62
    def _path(root):
        for relative in ('.teseo','.teseo/local'): _no_link(root/relative)
        path=root/'.teseo/local/sync.sqlite'
        for suffix in ('','-wal','-shm','-journal'): _no_link(Path(str(path)+suffix))
        return path
    def _db(self,root):
        local=_local_directory(root);_ensure_ignored(local)
        return _connection(self._path(root))
    # _schema: PRAGMA synchronous=FULL; stamp_schema(db); CREATE TABLE IF NOT EXISTS ...; record = canonical_json(dict)
```

### SERVICE_PATTERN (entrypoint copiato nel vault)
```python
# SOURCE: kit/graph/teseo_sync.py:7-14 — import dal runtime installato (.graph/dashboard) o dal kit in sviluppo
try:
    from dashboard.contracts import ContractError
    from dashboard.storage import capture_snapshot,_no_link
except ImportError:
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from kit.dashboard.contracts import ContractError
```

### COMMIT_BODY (dove vanno i trailer)
```python
# SOURCE: kit/dashboard/git_sync.py:463-472
        if not isinstance(message, str) or len(message) > 500 or any(ord(c) < 32 for c in message):
            raise ContractError('git_invalid_message', 'Messaggio commit non valido')
        ...
        body = f'{message}\n\nTeseo-Operation: {operation_id}\nTeseo-Base: {expected_head}\n'
```

### TEST_STRUCTURE
```python
# SOURCE: tests/test_dashboard_git_sync.py:166-199
class GitSync(unittest.TestCase):
    def setUp(self):
        self.fixture = Path(tempfile.mkdtemp(prefix='teseo-git-', dir=Path.cwd()))
        self.addCleanup(self.cleanup_fixture)          # _remove_fixture: retry su lock Windows
        self.root = self.fixture / 'vault'; self.root.mkdir()
        self.git('init', '-b', 'shared'); self.git('config', 'user.name', 'Fixture') ...
        self.repo = GitRepository(self.root, allow_local_remote=True)
# remote: bare = self.fixture / 'remote.git'; self.git('init', '--bare', str(bare), cwd=self.fixture)
```
I test iniziano con `import _shortpath  # noqa: F401` per il budget MAX_PATH di Windows. Usano `unittest` e girano con pytest.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `kit/dashboard/autosync.py` | CREATE | Logica `enable`/`pre`/`post`/`resume`/`status`, sessioni in `.teseo/local/autosync.sqlite` |
| `kit/graph/teseo_git.py` | CREATE | CLI `pre|post|riprendi|stato`, copiata in `.graph/` dall'installer |
| `kit/dashboard/git_sync.py` | UPDATE | Trailer in `checkpoint`, audit incrementale in `push`/`audit_history`, unione `log.md`/`index.md` in `integrate`, `write_local_excludes` |
| `kit/dashboard/sync_service.py` | UPDATE | `publish_session`, `advance_baseline`, `enable_automatic`; trailer passati a `checkpoint`; `published` all'audit |
| `kit/dashboard/sync_ui.py` | UPDATE | Stato "automatico", sessioni autosync, interruttore con consenso |
| `installa.py` | UPDATE | `--collabora`, `--branch`, `--crea-remote`, `--si`; manifest per vault legacy con conferma |
| `kit/skills/obsidian-wiki-ingest/SKILL.md` | UPDATE | Passo 0 `pre`, passo `post` dopo il log |
| `kit/skills/obsidian-wiki-lint/SKILL.md` | UPDATE | Idem |
| `kit/skills/obsidian-wiki-fill-gaps/SKILL.md` | UPDATE | Idem (`post` a chiusura sessione) |
| `kit/vault/CLAUDE.md`, `kit/vault/AGENTS.md`, `kit/vault/copilot-instructions.md` | UPDATE | Una regola: modifiche manuali → `teseo_git.py post --skill manuale` |
| `doc/09-autosync-collaborativo.md` | CREATE | ADR: da "nessuna automazione" ad autosync opt-in; garanzie conservate |
| `README.md`, `doc/08-analisi-avanzamento.md` | UPDATE | Installazione collaborativa, stato |
| `tests/test_autosync.py` | CREATE | Due clone + remote bare, flussi end-to-end |
| `tests/test_installa_collabora.py` | CREATE | Casi nuovo, aggancio e clone dell'installer |
| `tests/test_dashboard_git_sync.py`, `tests/test_sync_service.py` | UPDATE | Trailer, audit incrementale, union merge, fake repository con nuovi kwarg |

## NOT Building
- Autori nel grafo e nella UI (fase 4): qui si scrivono solo i trailer che la fase 4 leggerà.
- Editor del grafo, causa-effetto, nuova visualizzazione (fasi 5–7).
- Risoluzione automatica di conflitti sulla stessa nota: resta nella dashboard (`sync/resolve`).
- Modalità `pr` per l'autosync: autosync solo `direct`; la modalità PR resta manuale dalla dashboard.
- Pubblicazione di fonti binarie (D4).
- Hook Claude `Stop`/`UserPromptSubmit` con Git: esclusi (timeout 10 s, `kit/vault/settings.json:21,28`).
- Ricezione automatica in background: il pull avviene solo in `pre`.

---

## Step-by-Step Tasks

### Task 1: ADR e contratto dell'autosync
- **ACTION**: creare `doc/09-autosync-collaborativo.md`.
- **IMPLEMENT**: decisioni D1–D6; garanzie conservate:
  - allowlist e scansione segreti;
  - checkpoint con solo file attribuiti;
  - integrazione isolata;
  - nessun merge nel vault vivo;
  - conflitti alla dashboard;
  - `_env` non interattivo.
  
  Tabella dei codici di uscita: 0 ok/noop/disattivato; 2 bloccato, serve un'azione umana; 3 in attesa di rete o autenticazione, lavoro conservato. Stati della sessione: `open → published|noop|blocked|waiting`.
- **MIRROR**: struttura e tono di `doc/06-pubblicazione-github.md` (stato in testa, tabelle).
- **VALIDATE**: link dal `doc/README.md`; la roadmap la richiama.

### Task 2: primitive Git — trailer, esclusioni locali, audit incrementale
- **ACTION**: modificare `kit/dashboard/git_sync.py`.
- **IMPLEMENT**:
  1. `checkpoint(..., message=..., trailers=None)`.
     - `trailers` è una `dict[str,str]` con chiavi in `{'Teseo-Skill','Teseo-Agent'}` e valori che rispettano `^[a-z][a-z0-9-]{0,31}$`; altrimenti `git_invalid_message`.
     - I trailer vanno aggiunti **dopo** `Teseo-Base` nello stesso paragrafo, in ordine di chiave.
     - `find_checkpoint` non cambia: cerca solo le righe `Teseo-Operation`/`Teseo-Base`.
  2. `audit_history(oid, published=None)`.
     - Se `published` è un OID antenato di `oid`: `rev-list --max-count=129 oid --not published`.
     - Altrimenti: comportamento attuale.
     - Il limite 128 vale sui commit **non pubblicati**.
     - Con `published` impostato, il controllo `vault_id` confronta con il manifest di `published`, non del primo commit scansionato.
  3. `push(oid, remote, branch, published=None)` passa `published` all'audit.
  4. Funzione modulo `write_local_excludes(root, patterns)`.
     - Scrive o aggiorna un blocco delimitato `# teseo:begin` / `# teseo:end` in `.git/info/exclude`.
     - `_no_link` su `.git/info` e sul file.
     - Nessuna altra riga dell'utente va toccata.
     - I pattern ammessi sono solo percorsi relativi validati con `portable_path`, più slash finale per le directory.
- **MIRROR**: COMMIT_BODY, ERROR_HANDLING.
- **IMPORTS**: nessun nuovo import.
- **GOTCHA**:
  - Il `message` non può contenere newline (`git_sync.py:463`): i trailer **non** vanno nel message.
  - `_safe_config` controlla `.git/info/attributes`, non `exclude`: scrivere `exclude` è ammesso.
  - `fetch` di un branch remoto inesistente fallisce: non chiamare `audit_history(published=...)` senza un OID remoto valido.
- **VALIDATE**: test in `tests/test_dashboard_git_sync.py`:
  - corpo con trailer; trailer non validi rifiutati;
  - 130 commit con i primi 128 già "pubblicati" → push ok;
  - 129 nuovi → `git_history_limit`;
  - blocco exclude idempotente che conserva le righe utente.

### Task 3: unione automatica di `log.md` e `index.md`
- **ACTION**: in `integrate()` (`git_sync.py:552-583`), dopo `merge --no-commit` fallito.
- **IMPLEMENT**:
  - Leggere i file non uniti: `_invoke(stage, ['diff','--name-only','--diff-filter=U','-z'])`.
  - Se l'insieme è vuoto o non è contenuto in `{'log.md','index.md'}` → `git_conflict` come oggi.
  - Altrimenti, per ogni file:
    1. Estrarre gli stadi `:1:` (base, che può mancare → bytes vuoti), `:2:` e `:3:` con `git show`, check=False sullo stadio 1.
    2. Scriverli in `stage/.git/teseo-union/{base,ours,theirs}`.
    3. Lanciare `_invoke(stage, ['merge-file','--union','-p',ours,base,theirs])` e prenderne lo stdout.
    4. Rifiutare se lo stdout contiene `<<<<<<<`.
    5. Scrivere il file nel worktree dello stage e fare `git add -- path`.
  - Poi `write-tree` come nel ramo esistente. Il commit di merge resta firmato `Teseo` (escluso dagli autori in fase 4).
- **MIRROR**: rami `_invoke(stage, …)` già presenti in `integrate`.
- **GOTCHA**:
  - Su Windows non passare `\r\n` aggiuntivi: lavorare in bytes.
  - `core.autocrlf=false` è già forzato.
  - L'unione è solo testuale: due voci di log nello stesso giorno restano entrambe, ed è il comportamento voluto.
- **VALIDATE**:
  - Due clone appendono voci diverse a `log.md` e modificano note diverse → `integrate` produce un merge senza marker, con entrambe le voci.
  - Conflitto su `wiki/A.md` + `log.md` → `git_conflict` invariato.

### Task 4: `SyncService` — sessioni autosync come pubblicazioni
- **ACTION**: modificare `kit/dashboard/sync_service.py`.
- **IMPLEMENT**:
  1. `enable_automatic(vault_id, body)` con body `{consent: True, expected_head}`, sotto `_mutex` + `VaultLock`.
     - Richiede config esistente con `mode=='direct'`.
     - Imposta `automatic=True`, `automatic_consent_at` (data ISO) e `raw_policy='text'`.
     - `disable_automatic(vault_id)` rimette `automatic=False`.
     - `status()` riporta `config['automatic']` invece del `False` fisso (`sync_service.py:83`).
  2. `advance_baseline(vault_id, oid)`: se `is_ancestor(config['B'], oid)` e HEAD==oid, aggiorna `B` e `base_digest` (stesso codice di `_adopt` alle righe 372-373).
  3. `publish_session(vault_id, *, operation_id, base, files, trailers, message)`.
     - Copiare i controlli di `publish` **esclusi** `exclusive_confirmed` e `_event`.
     - Richiede `config['automatic'] is True`.
     - Nessun job non convergente (stesso loop delle righe 199-201).
     - `_identity`, `repo.head()==base`, `is_ancestor(config['B'], base)`.
     - Crea il record come alla riga 225, con `B=base`, `expected_digest=capture_snapshot(root).digest` e `trailers`/`message` salvati nel record.
     - Poi `self._advance(...)`.
  4. In `_advance`:
     - `repo.checkpoint(record['operation_id'], record['B'], record['files'], **({'message':record['message'],'trailers':record['trailers']} if record.get('trailers') else {}))`.
     - `repo.push(record['C'], url, destination, published=record['R'])` quando `R` è antenato di `C`.
  5. `resume_session(vault_id, operation_id)`: riapre `_advance` su un record in `waiting_auth`/`waiting_network`.
- **MIRROR**: SERVICE_PATTERN di `publish`/`resolve`; REPOSITORY_PATTERN.
- **GOTCHA**:
  - I fake di `repository_factory` in `tests/test_sync_service.py` e `tests/test_sync_pipeline.py` vanno estesi per accettare `message`/`trailers`/`published`: cercare `def checkpoint` e `def push` nei test.
  - `configure()` resta invariato e scrive `automatic=False`: l'abilitazione è sempre un passo separato.
  - `_advance` invoca `validate_integration`: se restituisce `needs_decision`, la sessione diventa `blocked`; non forzare.
- **VALIDATE**:
  - Unit test: `publish_session` rifiutato con `automatic=False`.
  - Con un job dashboard pendente → `sync_pending`.
  - Il percorso felice converge e aggiorna `B`.

### Task 5: modulo `kit/dashboard/autosync.py` — configurazione e `pre`
- **ACTION**: creare il modulo.
- **IMPLEMENT**:
  - `class _SingleVault`: `root(vault_id)` restituisce la radice se l'id coincide con il manifest, altrimenti `ContractError('vault_unknown',…)`. Serve come registry per `SyncService`.
  - DB `.teseo/local/autosync.sqlite` (pattern REPOSITORY), tabella `sessions(id TEXT PRIMARY KEY, state TEXT NOT NULL, data BLOB NOT NULL)`.
  - `status(root)` → `{enabled, state, open_session, last}`.
  - `pre(root, skill, agent)`:
    1. Manifest assente o `automatic` falso → `{'state':'disabled'}`, exit 0.
    2. `VaultLock(root, timeout=30)` e `assert_receiver_complete(root)`.
    3. Sessione `open` esistente → `autosync_session_open` ("Sessione <skill> non chiusa: eseguire teseo_git.py post"). Sessione `waiting` → tentare `resume_session`; se resta `waiting` proseguire con avviso.
    4. `repo=GitRepository(root)`; `SyncService._identity(repo, config)`.
    5. `not repo.clean()` → `autosync_unpublished` ("Modifiche non pubblicate: `python .graph/teseo_git.py post --skill manuale`").
    6. `head=repo.head()`, poi `try: remote=repo.fetch(url, branch)`. Se `git_network`/`git_auth`/`git_timeout` → `offline=True` e si prosegue senza ricezione.
    7. In base al rapporto fra `remote` e `head`:
       - `remote==head` o `is_ancestor(remote, head)`: nulla da ricevere.
       - `is_ancestor(head, remote)`: `repo.adopt(head, {'oid':remote})`, rebuild di grafo e proiezione (copiare le righe 366-371 di `sync_service.py` in una funzione condivisa `_refresh_projections(root, vault_id, lock)` usata da entrambi), poi `advance_baseline`. Contare i commit ricevuti con `rev-list --count head..remote`.
       - altrimenti `autosync_diverged` ("Storie divergenti: dashboard → Pubblicazione Git → Risolvi").
    8. Inserire la sessione `open` con `{skill, agent, base: repo.head(), base_digest, started_at, offline}`.
- **MIRROR**: REPOSITORY_PATTERN, ERROR_HANDLING; validazione di `skill` in `{'ingest','lint','lacune','manuale','dashboard'}` e di `agent` in `{'claude','codex','copilot','umano'}`.
- **IMPORTS**: `from .contracts import ContractError, canonical_json, parse_json, parse_manifest`; `from .storage import VaultLock, capture_snapshot, assert_receiver_complete, _local_directory, _ensure_ignored, _no_link`; `from .git_sync import GitRepository`; `from .sync_service import SyncService`; `from .shared_migration import _connection`.
- **GOTCHA**:
  - Il `VaultLock` **non** può restare acquisito fra `pre` e `post` (processi distinti): la sessione nel DB fa da semaforo cooperativo.
  - Senza `user.name`/`user.email` → `git_author_required` già in `pre`, così non si scopre a fine ingest.
  - `GitRepository.__init__` legge solo `~/.gitconfig` (`git_sync.py:155-168`), non `XDG_CONFIG_HOME`: documentarlo nel messaggio.
- **VALIDATE**: `tests/test_autosync.py` casi 1, 3, 7, 10 (vedi Testing Strategy).

### Task 6: `post`, `riprendi`, modifiche manuali
- **ACTION**: completare `autosync.py`.
- **IMPLEMENT** `post(root, skill, agent)`:
  1. `disabled` come in `pre`.
  2. Sotto `VaultLock`: prendere la sessione `open`. Se manca e `skill=='manuale'`, crearne una implicita con `base=repo.head()`; se manca per altre skill → `autosync_no_session` ("Eseguire prima teseo_git.py pre").
  3. Controllo grafo: `subprocess.run([sys.executable, str(root/'.graph/build_graph.py'), '--check'], cwd=root, timeout=300)`; exit≠0 → `autosync_graph_check`. La sessione resta `open`.
  4. `repo.head()!=session.base` → `autosync_head_changed`.
  5. File cambiati: `repo._changes()` (stato git, untracked inclusi).
     - Per ogni path: se il file esiste ed è `_allowed(path, manifest, data)` → `files[path]=sha256`.
     - Se non esiste ed era tracciato → `None`.
     - Se è in `raw/` con estensione fuori `_TEXT_RAW` → aggiungerlo all'elenco `local_only` e a `write_local_excludes` (D4).
     - Altrimenti → `autosync_out_of_policy` con il path (es. un `.md` con un segreto).
  6. Nessun file → sessione `noop`.
  7. `SyncService(_SingleVault(...)).publish_session(...)` con:
     - `operation_id=session.id`;
     - `trailers={'Teseo-Skill': skill, 'Teseo-Agent': agent}`;
     - `message=f'Teseo: {skill} ({agent})'`.
  8. Stato del job → stato della sessione:
     - `converged` → `published` (exit 0);
     - `noop` → `noop`;
     - `waiting_*` → `waiting` (exit 3);
     - altri → `blocked` (exit 2), con `error` e l'istruzione per la dashboard.
  
  `resume(root)`: per la sessione `waiting`, `SyncService.resume_session`; poi aggiorna lo stato.
- **MIRROR**: mappa errore→stato di `_advance` (`sync_service.py:337-341`).
- **GOTCHA**:
  - `_changes()` solleva `git_index_not_empty` se l'utente ha fatto `git add`: il messaggio deve suggerire `git restore --staged .`.
  - `files` non può modificare raw già tracciati (`git_immutable_changed`, `git_sync.py:416-417`): è corretto, le fonti sono immutabili.
  - `.teseo/shared/events/` è immutabile allo stesso modo.
- **VALIDATE**: casi 2, 4, 5, 6, 8, 9, 11.

### Task 7: CLI `kit/graph/teseo_git.py`
- **ACTION**: creare l'entrypoint.
- **IMPLEMENT**:
  - argparse con sottocomandi `pre`, `post`, `riprendi`, `stato`; opzioni `--vault` (default: cartella padre di `.graph`, cioè `Path(__file__).resolve().parents[1]`), `--skill` e `--agente`.
  - Default di `--agente`: `claude` se `os.environ.get('CLAUDECODE')=='1'`, altrimenti obbligatorio per `pre`/`post`.
  - Se l'import di `dashboard.autosync` fallisce **e** non esiste `.teseo/project.json` → stampa "collaborazione non attiva" ed esce con 0. Così le skill restano valide nei vault non collaborativi.
  - Output: JSON su stdout e una riga umana su stderr. Exit 0/2/3 come da ADR.
- **MIRROR**: SERVICE_PATTERN di `teseo_sync.py` (import con fallback al kit).
- **GOTCHA**:
  - L'installer copia ogni `kit/graph/*.py` (`installa.py:380`), ma il package `dashboard/` solo con `--dashboard` (`installa.py:390-396`): `--collabora` deve attivare anche la copia della dashboard (Task 8).
  - Su Windows forzare `sys.stdout.reconfigure(encoding='utf-8')` come `installa.py:524`.
- **VALIDATE**: `python kit/graph/teseo_git.py stato --vault <fixture>` stampa JSON; vault senza manifest → exit 0.

### Task 8: installer `--collabora`
- **ACTION**: modificare `installa.py`.
- **IMPLEMENT**:
  - Nuovi argomenti: `--collabora URL`, `--branch` (default `main`), `--visibilita private|public` (default `private`), `--crea-remote`, `--si` (consenso non interattivo).
  - `collabora` implica `dashboard=True` per la copia del runtime. Il vincolo "solo cartelle vuote" (`installa.py:354-359`) viene superato **solo** con `collabora` e conferma (D5).
  - Estrarre la creazione del manifest (righe 438-446) in `crea_manifest(vault, rapporto)`.
  - Nuova funzione `collabora(vault, url, branch, visibilita, crea_remote, conferma, rapporto, *, allow_local_remote=False)`, con tre casi:
    - **Aggancio:** `vault/.git` esiste e `origin` == url → nessun init; esclusioni locali; `configure` + `enable_automatic`.
    - **Clone:** la cartella è vuota o inesistente e `git ls-remote url branch` restituisce un ref → `git clone --branch <branch> url vault` (con `_invoke` e `file_transport=allow_local_remote`), poi installazione normale e aggancio. Va eseguito **prima** di `installa()`, che altrimenti crea `raw/ wiki/ .graph/`.
    - **Nuovo:**
      1. Autore da `git config --global user.name/email`; se manca → errore con istruzioni.
      2. Selezione raw = file di `raw/` con estensione in `_TEXT_RAW`.
      3. `preview_data_repository`; stampa N file condivisi, gli esclusi (max 15) e la destinazione; conferma `s/N` salvo `--si`.
      4. Se `--crea-remote`: verifica `gh auth status` e lancia `gh repo create <owner/name> --private|--public`.
      5. `initialize_data_repository(..., share_confirmed=True, expected_files=hashes)`.
      6. `write_local_excludes(vault, LOCALI + raw_binari)`.
      7. `GitRepository(vault).push(head, url, branch)`.
      8. `configure` + `enable_automatic`.
  - `LOCALI = ['.graph/', '.graph_backup/', '.claude/', '.codex/', '.agents/', '.github/', '.obsidian/', '.trash/', '.teseo/local/', 'CLAUDE.md', 'AGENTS.md']`.
  - Stampa finale: "Autosync attivo: le skill faranno pull/push. Modifiche a mano: python .graph/teseo_git.py post --skill manuale".
- **MIRROR**: `rapporto(...)`/`rapporto.avviso(...)`; `ap.error` per gli argomenti incompatibili (`--collabora` con `--solo-integrazione` o `--prova`).
- **GOTCHA**:
  - `validate_remote` ammette solo GitHub (`git_sync.py:58-70`): i test passano `allow_local_remote=True` chiamando `collabora()` direttamente, non da CLI.
  - Le esclusioni vanno scritte **prima** di `configure`, che richiede `repo.clean()` (`sync_service.py:142`).
  - `configure` accetta al massimo 256 `raw_paths` (`sync_service.py:132`): passare `[]`, perché la policy `raw_policy='text'` dell'autosync pubblica i raw testuali per sessione.
  - Il primo push su un remote **non vuoto** viene rifiutato: in quel caso suggerire il caso Clone.
- **VALIDATE**: `tests/test_installa_collabora.py` sui tre casi; `python installa.py --prova` invariato.

### Task 9: skill e istruzioni del vault
- **ACTION**: aggiornare le 3 SKILL.md e i 3 file di istruzioni.
- **IMPLEMENT**:
  - Testo del passo 0, da inserire prima del passo 1 della Procedura:
    > **0. Sincronizza.** Se esiste `.graph/teseo_git.py`: `python .graph/teseo_git.py pre --skill <ingest|lint|lacune> --agente <claude|codex|copilot>`. Exit 0: prosegui e riporta gli aggiornamenti ricevuti. Exit 2: fermati senza modificare il vault e riporta il messaggio. Exit 3: sei offline; prosegui e avvisa che la pubblicazione avverrà dopo.
  - Testo del passo finale, da inserire dopo il passo "Appendi un'entry al log":
    > **Pubblica.** Con `--check` pulito: `python .graph/teseo_git.py post --skill … --agente …`. Riporta l'esito: pubblicato (commit), in attesa di rete (riprendere con `teseo_git.py riprendi`) o da risolvere nella dashboard.
  - Fill-gaps: un solo `post` a chiusura sessione (passo 6), non per ogni risposta.
  - `kit/vault/CLAUDE.md`, `AGENTS.md`, `copilot-instructions.md`: una riga sulle modifiche manuali.
- **GOTCHA**:
  - Le skill sono copiate in 3 cartelle client (`installa.py:13`): `--aggiorna` è necessario per i vault esistenti; documentarlo nel README.
  - I test di distribuzione (`tests/test_dashboard_distribution.py`) possono confrontare i byte delle skill: rieseguirli.
- **VALIDATE**: `grep -n "teseo_git.py" kit/skills/*/SKILL.md` restituisce 6 righe; i test di distribuzione passano.

### Task 10: UI sync e documentazione
- **ACTION**: `kit/dashboard/sync_ui.py`, `server.py` (rotte `sync/automatic-enable|automatic-disable`), `README.md`, `doc/08`.
- **IMPLEMENT**:
  - Interruttore con consenso esplicito e testo del rischio.
  - Elenco delle ultime 10 sessioni autosync (skill, agente, stato, commit, errore).
  - Le rotte seguono il controllo POST esistente (Origin, CSRF, JSON ≤16 KiB, `server.py:192-250`).
  - README: sezione "Collaborare su un vault" con i tre casi dell'installer.
- **MIRROR**: rotte `sync/<azione>` in `server.py:265-270`, stile UI di `sync_ui.py`.
- **VALIDATE**: `node tests/dashboard_ui_smoke.js`, o lo smoke equivalente, con la fixture `tests/dashboard_ui_fixture.py`.

---

## Testing Strategy

### Unit / integration tests (`tests/test_autosync.py`)
Fixture:
- remote bare in `teseo-git-*`;
- clone **A** creato con `collabora(..., allow_local_remote=True, conferma=True)`;
- clone **B** con il caso Clone;
- identità Git distinte (`Alice`, `Bob`) impostate con `git config --local`.

Kit installato con `installa()` così `.graph/build_graph.py` esiste.

| # | Test | Input | Expected | Edge? |
|---|---|---|---|---|
| 1 | pre allineato | A pulito | `ready`, sessione `open`, 0 ricevuti | |
| 2 | post pubblica | A modifica `wiki/X.md` + `log.md` | `published`; il commit remoto ha autore Alice, `Teseo-Skill: ingest`, `Teseo-Agent: claude` | |
| 3 | pre riceve | B dopo il 2 | fast-forward, `graph.sqlite` contiene la modifica di X | |
| 4 | concorrenza disgiunta | A e B modificano note diverse e appendono a `log.md` | il secondo `post` integra con union e pubblica; entrambe le voci di log presenti | ✔ |
| 5 | conflitto sulla stessa nota | A e B modificano `wiki/X.md` | il secondo `post` dà `blocked`, codice `git_conflict`, exit 2; vault vivo intatto | ✔ |
| 6 | modifica manuale | edit senza `pre`, poi `post --skill manuale` | pubblicato con `Teseo-Skill: manuale` | |
| 7 | pre su albero sporco | file modificato non pubblicato | `autosync_unpublished` | ✔ |
| 8 | check grafo fallito | link non risolto in X | `autosync_graph_check`, nessun commit, sessione `open` | ✔ |
| 9 | rete assente | remote rinominato | `waiting`, exit 3; ripristino + `riprendi` → `published` | ✔ |
| 10 | autosync disattivo | config `automatic=False` | `disabled`, exit 0, nessuna scrittura | |
| 11 | raw binario | `raw/a.pdf` nuovo | escluso, riportato in `local_only`, pubblicazione del resto | ✔ |
| 12 | sessione aperta | due `pre` consecutivi | `autosync_session_open` | ✔ |
| 13 | job dashboard pendente | job in `needs_resolution` | `post` → `sync_pending` | ✔ |

### Test delle primitive (`tests/test_dashboard_git_sync.py`)
- Trailer nel corpo e loro validazione.
- Audit incrementale (128 pubblicati + 2 nuovi ok; 129 nuovi → limite).
- Union solo per `log.md`/`index.md`.
- Blocco exclude idempotente.

### Edge Cases Checklist
- [x] Nessun file cambiato → `noop`
- [x] Più di 128 commit storici → audit incrementale
- [x] Percorsi lunghi su Windows → fixture `_shortpath`
- [x] Accesso concorrente → `VaultLock` + sessione unica + `sync_pending`
- [x] Rete o autenticazione assenti → `waiting`, nessun prompt (`_env`)
- [x] Permessi negati sul push (branch protetto) → `needs_approval` → `blocked`

---

## Validation Commands

### Static Analysis
```bash
python -m ruff check kit tests installa.py
python -m mypy
```
EXPECT: zero errori (mypy.ini copre `kit/dashboard`).

### Unit Tests
```bash
python -m pytest -q tests/test_autosync.py tests/test_installa_collabora.py tests/test_dashboard_git_sync.py tests/test_sync_service.py tests/test_sync_pipeline.py
```
EXPECT: tutti verdi.

### Full Test Suite
```bash
python -m pytest -q -p no:cacheprovider
```
EXPECT: nessuna regressione (baseline 2026-10-27: 399 passed, 1 skipped, ~24 min).

### Installer
```bash
python installa.py --prova
python installa.py --prova --dashboard
```
EXPECT: "tutto OK".

### Browser Validation
```bash
python .graph/teseo_dashboard.py --vault "<vault di prova>"
```
EXPECT: pannello sync con "Automatico: attivo" e sessioni elencate.

### Manual Validation (repository GitHub reale scelto dall'utente — richiede autorizzazione esplicita)
- [ ] `installa.py <vuota> --collabora <url privato> --crea-remote`: repo creato, primo commit visibile
- [ ] Ingest da Claude Code: `pre` e `post` eseguiti, commit con trailer su GitHub
- [ ] Secondo PC/utente: `installa.py <vuota> --collabora <url>` clona; `lint` riceve e pubblica
- [ ] Conflitto voluto sulla stessa nota: blocco con istruzioni, risoluzione dalla dashboard

---

## Acceptance Criteria
- [ ] Tasks 1–10 completati
- [ ] Validation commands verdi
- [ ] I test della tabella scritti e passanti
- [ ] Nessun errore ruff/mypy
- [ ] Vault non collaborativi invariati (skill → `teseo_git.py` exit 0 "non attiva")
- [ ] UX come in "After"

## Completion Checklist
- [ ] Codici errore `autosync_*` e messaggi in italiano senza dati privati
- [ ] Nessuna scrittura Git fuori da `GitRepository`/`_invoke` (niente `subprocess git` diretto)
- [ ] Nessun merge nel vault vivo; solo fast-forward (`adopt`)
- [ ] Stile compatto coerente con `sync_service.py`
- [ ] ADR, README e doc/08 aggiornati
- [ ] Nessuno scope delle fasi 4–7 anticipato

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `validate_integration` richiede spesso una decisione umana su note correlate | Media | Medio | Misurarlo nel caso 4; se troppo frequente, valutare una soglia nella fase successiva, mai un bypass silenzioso |
| Il modello dimentica `post` | Media | Medio | Il `pre` successivo rifiuta (`autosync_session_open` / `autosync_unpublished`) con il comando esatto |
| Obsidian salva durante `post` | Media | Basso | `checkpoint` ricontrolla gli hash; errore `blocked_external_change`, si rilancia `post` |
| `gh` assente o non autenticato | Media | Basso | `--crea-remote` facoltativo; messaggio con `gh auth login` |
| Le skill aggiornate non arrivano ai vault esistenti | Alta | Medio | README: `installa.py <vault> --aggiorna`; l'installer avvisa se le skill sono diverse |

## Notes
- Il trailer `Teseo-Agent` distingue l'operatore umano (autore del commit) dall'agente: la fase 4 leggerà `git log --format=%an%x00%aI%x00%(trailers:key=Teseo-Agent,valueonly)`.
- `teseo_git.py pre` sostituisce, per l'uso quotidiano, la ricezione manuale solo Windows (`receiver_apply.py:71`), perché usa `adopt` fast-forward, disponibile su tutte le piattaforme.
- La baseline dei test è stata misurata il 2026-10-27 sul branch `codex/dashboard-foundations` (`35a9840`).

"""Autosync opt-in: pull prima e commit+push dopo ogni skill, sullo stesso motore del publisher.

Nessuna scorciatoia: stesso GitRepository (allowlist, segreti, checkpoint attribuito, integrazione
isolata, fast-forward) e stessa macchina a stati di SyncService. Una sessione per ogni esecuzione
di skill, in .teseo/local/autosync.sqlite. Conflitti reali, storie divergenti e pubblicazioni
bloccate restano alla dashboard.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import subprocess
import sys
from uuid import uuid4

from .contracts import ContractError, canonical_json, inspect_vault, parse_json, resolve_path, stamp_schema
from .shared_migration import _connection
from .storage import _ensure_ignored, _local_directory, _no_link
from .sync_service import SyncService

SKILLS = ('ingest', 'lint', 'lacune', 'manuale', 'dashboard')
AGENTS = ('claude', 'codex', 'copilot', 'umano')
_OPEN, _WAITING_JOB = 'open', ('waiting_auth', 'waiting_network')
_OFFLINE = ('git_network', 'git_timeout', 'git_auth')
_CHECK_TIMEOUT = 300


class _SingleVault:
    """Registry minimo per SyncService: un solo vault, quello della cartella corrente."""
    def __init__(self, root, vault_id):
        self._root, self.vault_id = root, vault_id

    def root(self, vault_id):
        if vault_id != self.vault_id:
            raise ContractError('vault_unknown', 'Vault non riconosciuto')
        return self._root


def _result(state, exit_code, message, **extra):
    return dict(state=state, exit=exit_code, message=message, **extra)


def _blocked(error, **extra):
    return _result('blocked', 2, error.args[0], error=error.as_dict(), **extra)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Autosync:
    def __init__(self, root, *, allow_local_remote=False, validator=None):
        self.root = Path(root).resolve(strict=True)
        self.allow_local_remote = allow_local_remote
        compatibility = inspect_vault(self.root)
        self.vault_id = compatibility.manifest['vault_id'] if compatibility.mode == 'compatible' else None
        self.service = None
        if self.vault_id:
            self.service = SyncService(_SingleVault(self.root, self.vault_id), validator=validator,
                                       repository_factory=lambda r: self._repository(r))

    def _repository(self, root=None):
        from .git_sync import GitRepository
        return GitRepository(root or self.root, allow_local_remote=self.allow_local_remote)

    # -- stato delle sessioni -------------------------------------------------------------------
    def _db(self):
        local = _local_directory(self.root)
        _ensure_ignored(local)
        path = local / 'autosync.sqlite'
        for suffix in ('', '-wal', '-shm', '-journal'):
            _no_link(Path(str(path) + suffix))
        return _connection(path)

    @staticmethod
    def _schema(db):
        db.execute('PRAGMA synchronous=FULL')
        stamp_schema(db)
        db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,state TEXT NOT NULL,data BLOB NOT NULL)')

    def _sessions(self, *states):
        with self._db() as db:
            self._schema(db)
            where = ' WHERE state IN (%s)' % ','.join('?' * len(states)) if states else ''
            return [parse_json(row[0]) for row in db.execute('SELECT data FROM sessions' + where + ' ORDER BY rowid DESC', states)]

    def _save(self, session):
        with self._db() as db:
            self._schema(db)
            db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?)',
                       (session['id'], session['state'], canonical_json(session)))

    def _set(self, session, state, **extra):
        session.update(state=state, **extra)
        self._save(session)
        return session

    def _new_session(self, skill, agent, head, offline=False):
        session = dict(id=str(uuid4()), skill=skill, agent=agent, state=_OPEN, base=head, head=head,
                       offline=offline, started_at=_now(), error=None)
        self._save(session)
        return session

    # -- consenso e stato -----------------------------------------------------------------------
    def enabled(self):
        if not self.service:
            return False
        try:
            return self.service.status(self.vault_id).get('automatic') is True
        except ContractError:
            return False

    def enable(self, *, visibility='private'):
        """Configura il publisher (modalità direct, nessuna fonte raw preselezionata) e registra il consenso."""
        if not self.service:
            raise ContractError('vault_readonly', 'Richiesto manifest compatibile: eseguire installa.py --collabora')
        info = self._repository().inspect()
        self.service.configure(self.vault_id, dict(remote='origin', branch=info['branch'], visibility=visibility,
                                                   mode='direct', raw_paths=[], share_confirmed=True,
                                                   expected_head=info['head']))
        return self.service.enable_automatic(self.vault_id, dict(consent=True, expected_head=info['head']))

    def status(self):
        if not self.service:
            return _result('disabled', 0, 'Collaborazione non attiva: nessun manifest dati compatibile')
        sync = self.service.status(self.vault_id)
        on = sync.get('automatic') is True
        return _result('enabled' if on else 'disabled', 0, 'Autosync attivo' if on else 'Autosync non attivo',
                       sync_state=sync.get('state'), head=sync.get('head'), branch=sync.get('branch'),
                       sessions=[{k: s.get(k) for k in ('id', 'skill', 'agent', 'state', 'started_at', 'head', 'error')}
                                 for s in self._sessions()[:10]])

    @staticmethod
    def _check_names(skill, agent):
        if skill not in SKILLS:
            raise ContractError('autosync_request', 'Skill non valida: ' + ', '.join(SKILLS))
        if agent not in AGENTS:
            raise ContractError('autosync_request', 'Agente non valido: ' + ', '.join(AGENTS))

    def _guard(self, action):
        """Esegue action(); rete assente → exit 3, ogni altro ContractError → exit 2, mai un traceback."""
        try:
            return action()
        except ContractError as error:
            if error.code in _OFFLINE:
                return _result('waiting', 3, 'Rete o autenticazione non disponibili: lavoro conservato', error=error.as_dict())
            return _blocked(error)

    # -- pre ------------------------------------------------------------------------------------
    def pre(self, skill, agent):
        def run():
            self._check_names(skill, agent)
            if not self.enabled():
                return _result('disabled', 0, 'Autosync non attivo: nessuna sincronizzazione')
            return self._pre(skill, agent)
        return self._guard(run)

    def _pre(self, skill, agent):
        repo = self._repository()
        author = repo.inspect()['author']
        if not author['name'] or not author['email']:
            raise ContractError('git_author_required', 'Configurare user.name e user.email nel ~/.gitconfig')
        if not repo.clean():
            raise ContractError('autosync_unpublished',
                                'Modifiche non pubblicate nel vault: eseguire python .graph/teseo_git.py post --skill manuale')
        for stale in self._sessions(_OPEN):
            self._set(stale, 'abandoned')
        notes = []
        for waiting in self._sessions('waiting'):
            try:
                job = self.service.resume_session(self.vault_id, waiting['id'])
            except ContractError as error:
                if error.code not in _OFFLINE:
                    raise
                job = dict(state='waiting_network')
            if job['state'] in ('converged', 'noop'):
                self._set(waiting, 'published' if job['state'] == 'converged' else 'noop', head=repo.head())
                notes.append('pubblicata la sessione in attesa ' + waiting['id'][:8])
            elif job['state'] in _WAITING_JOB:
                return _result('blocked', 2, 'Una pubblicazione precedente attende ancora la rete: riprovare quando online '
                                             '(python .graph/teseo_git.py riprendi)', session=waiting['id'])
            else:
                raise ContractError('autosync_blocked', 'Pubblicazione precedente da risolvere nella dashboard '
                                                        '(Pubblicazione Git → Risolvi)')
        down = self.service.sync_down(self.vault_id)
        state = down['state']
        if state == 'pending':
            raise ContractError('autosync_blocked', 'Una pubblicazione precedente richiede la dashboard (Pubblicazione Git → Risolvi)')
        if state == 'diverged':
            raise ContractError('autosync_diverged', 'Storie divergenti: risolvere nella dashboard (Pubblicazione Git → Risolvi)')
        offline = state == 'offline'
        if offline:
            notes.append('offline: nessun aggiornamento ricevuto')
        elif state == 'received':
            notes.append('ricevuti %d commit' % down['received'])
        if down.get('warning'):
            notes.append('grafo da ricostruire dalla dashboard')
        head = repo.head()
        session = self._new_session(skill, agent, head, offline)
        return _result('ready', 0, '; '.join(notes) or 'Allineato al repository condiviso',
                       session=session['id'], received=down.get('received', 0), offline=offline, head=head)

    # -- post -----------------------------------------------------------------------------------
    def post(self, skill, agent, *, graph_check=True):
        """graph_check=False salta `.graph/build_graph.py --check`: serve al servizio dashboard, che ha già validato il
        candidato con il builder del runtime e non esegue script del vault."""
        def run():
            self._check_names(skill, agent)
            if not self.enabled():
                return _result('disabled', 0, 'Autosync non attivo: nessuna pubblicazione')
            return self._post(skill, agent, graph_check)
        return self._guard(run)

    def _graph_check(self):
        script = self.root / '.graph/build_graph.py'
        if not script.is_file():
            return 'skipped'
        try:
            done = subprocess.run([sys.executable, str(script), '--check'], cwd=self.root, capture_output=True,
                                  timeout=_CHECK_TIMEOUT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as error:
            raise ContractError('autosync_graph_check', 'build_graph --check oltre il tempo massimo') from error
        if done.returncode:
            lines = (done.stdout + done.stderr).decode('utf-8', 'replace').strip().splitlines()
            raise ContractError('autosync_graph_check', 'Il grafo non è valido; correggere e rilanciare post: '
                                + ' | '.join(line.strip() for line in lines[:5]))
        return 'ok'

    def _files(self, repo):
        """Percorsi cambiati → hash (None = eliminato). Le fonti binarie diventano esclusioni locali."""
        from .git_sync import MAX_FILE, is_local_only, read_local_excludes, write_local_excludes
        manifest = repo._manifest()
        files, local_only = {}, []
        for path in sorted(repo._changes()):
            target = resolve_path(self.root, path)
            if not target.exists() and not target.is_symlink():
                files[path] = None
                continue
            _no_link(target)
            data = target.read_bytes() if target.is_file() and target.stat().st_size <= MAX_FILE else None
            if data is not None and repo._allowed(path, manifest, data):
                files[path] = hashlib.sha256(data).hexdigest()
            elif is_local_only(path):
                local_only.append(path)
            else:
                raise ContractError('autosync_out_of_policy',
                                    'File fuori dalla policy dei dati condivisi (tipo, dimensione o contenuto): ' + path
                                    + '. Spostalo fuori dal vault oppure aggiungilo a .git/info/exclude, poi rilancia', path)
        if local_only:
            write_local_excludes(self.root, [*read_local_excludes(self.root), *local_only])
        return files, local_only

    def _post(self, skill, agent, graph_check=True):
        repo = self._repository()
        opened = self._sessions(_OPEN)
        if opened:
            session = opened[0]
        elif skill in ('manuale', 'dashboard'):  # modifiche fuori da una skill: la sessione nasce con la pubblicazione
            session = self._new_session(skill, agent, repo.head())
        else:
            raise ContractError('autosync_no_session', 'Nessuna sessione aperta: eseguire prima python .graph/teseo_git.py pre')
        if self._sessions('waiting'):
            raise ContractError('autosync_blocked', 'Una pubblicazione precedente attende la rete: eseguire riprendi a vault pulito, '
                                                    'oppure usare la dashboard (Pubblicazione Git → Risolvi)')
        graph = self._graph_check() if graph_check else 'skipped'
        if repo.head() != session['base']:
            raise ContractError('autosync_head_changed', 'HEAD è cambiato dopo pre: pubblicare con post --skill manuale')
        files, local_only = self._files(repo)
        if not files:
            self._set(session, 'noop', skill=skill, agent=agent)
            return _result('noop', 0, 'Nessuna modifica da pubblicare', session=session['id'], local_only=local_only, graph=graph)
        job = self.service.publish_session(self.vault_id, operation_id=session['id'], files=files,
                                           message='Teseo: %s (%s)' % (skill, agent),
                                           trailers={'Teseo-Skill': skill, 'Teseo-Agent': agent})
        return self._outcome(session, job, local_only, graph, len(files))

    def _outcome(self, session, job, local_only, graph, count):
        state, skill, agent = job['state'], session['skill'], session['agent']
        head = self._repository().head()
        common = dict(session=session['id'], files=count, local_only=local_only, graph=graph, head=head)
        if state == 'converged':
            self._set(session, 'published', head=head)
            return _result('published', 0, 'Pubblicato %s (%s, %s)' % (head[:7], skill, agent), **common)
        if state == 'noop':
            self._set(session, 'noop')
            return _result('noop', 0, 'Nessuna modifica da pubblicare', **common)
        if state in _WAITING_JOB:
            self._set(session, 'waiting', error=job.get('error'))
            return _result('waiting', 3, 'Rete o autenticazione non disponibili: commit conservato, '
                                         'riprendere con python .graph/teseo_git.py riprendi', error=job.get('error'), **common)
        self._set(session, 'blocked', error=job.get('error'))
        return _result('blocked', 2, 'Pubblicazione da risolvere nella dashboard (Pubblicazione Git → Risolvi): stato '
                       + state, error=job.get('error'), job_state=state, **common)

    # -- avvisi ---------------------------------------------------------------------------------
    def updates(self):
        """Aggiornamenti remoti non ancora ricevuti: solo fetch, mai pull né scritture su note, grafo o sessioni."""
        def run():
            if not self.enabled():
                return _result('disabled', 0, 'Autosync non attivo', count=0)
            config = self.service.status(self.vault_id).get('config') or {}
            repo = self._repository()
            head = repo.head()
            try:
                remote = repo.fetch(config['remote_url'], config['branch'])
            except ContractError as error:
                if error.code in _OFFLINE:
                    return _result('offline', 0, 'Offline: aggiornamenti remoti non verificabili', count=0)
                raise
            if remote == head or repo.is_ancestor(remote, head):
                return _result('current', 0, 'Allineato al repository condiviso', count=0, head=head)
            if not repo.is_ancestor(head, remote):
                return _result('diverged', 0, 'Storie divergenti: risolvere nella dashboard (Pubblicazione Git → Risolvi)', count=0, head=head)
            count = int(repo.run('rev-list', '--count', head + '..' + remote).strip())
            return _result('behind', 0, '%d aggiornamenti remoti da ricevere: la prossima skill li scarica con pre' % count,
                           count=count, head=head)
        return self._guard(run)

    # -- riprendi -------------------------------------------------------------------------------
    def resume(self):
        def run():
            if not self.enabled():
                return _result('disabled', 0, 'Autosync non attivo')
            waiting = self._sessions('waiting')
            if not waiting:
                return _result('noop', 0, 'Nessuna pubblicazione in attesa')
            if not self._repository().clean():
                raise ContractError('autosync_unpublished', 'Il vault ha modifiche non pubblicate: la ripresa richiede un albero pulito')
            session = waiting[0]
            return self._outcome(session, self.service.resume_session(self.vault_id, session['id']), [], 'skipped', 0)
        return self._guard(run)

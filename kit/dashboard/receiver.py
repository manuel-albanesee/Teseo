"""Opt-in remote detection; never apply, merge or replace live vault data.

The publisher mutex and kernel vault lock serialize detection with cooperative
writers. They cannot exclude editors: automatic application stays disabled.
"""
from pathlib import Path
import difflib
import random
import sqlite3
import threading
import time
from uuid import uuid4

from .contracts import ContractError, canonical_json, parse_json
from .shared_migration import _connection
from .storage import (Journal, VaultLock, _ensure_ignored, _local_directory,
                      _no_link, assert_receiver_complete, capture_snapshot,
                      validate_raw_unchanged)
from .sync_service import _fields, _oid


def _preview(base, candidate):
    """Bounded, inert source review bound to the candidate's content digest."""
    before={item.path:item.data for item in base.files}
    after={item.path:item.data for item in candidate.files}
    paths=sorted(path for path in before.keys()|after.keys() if before.get(path)!=after.get(path))
    files=[];chunks=[];remaining=20000;truncated=len(paths)>128
    for path in paths[:128]:
        files.append(dict(path=path,before=base.hashes.get(path),after=candidate.hashes.get(path)))
        try:
            old=before.get(path,b'').decode('utf-8').splitlines(keepends=True)
            new=after.get(path,b'').decode('utf-8').splitlines(keepends=True)
        except UnicodeError:
            truncated=True
            continue
        # Limit input as well as output: a single long line must not defeat bounds.
        if len(before.get(path,b''))+len(after.get(path,b''))>256000:
            truncated=True
            continue
        for line in difflib.unified_diff(old,new,fromfile='base/'+path,tofile='candidate/'+path):
            if len(line)>remaining:
                chunks.append(line[:remaining]);remaining=0;truncated=True
                break
            chunks.append(line);remaining-=len(line)
        if remaining==0:
            truncated=True
            break
    return dict(files=files,total_files=len(paths),diff=''.join(chunks),truncated=truncated,complete=not truncated)


class Receiver:
    def __init__(self, registry, sync_service, *, clock=time.time, jitter=None,
                 repo_factory=None):
        self.registry = registry
        self.sync = sync_service
        self.clock = clock
        self.jitter = jitter or (lambda: random.uniform(0, 5))
        self.repo_factory = repo_factory
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._lifecycle = threading.Lock()

    @staticmethod
    def _path(root):
        root = Path(root)
        for relative in ('.teseo', '.teseo/local'):
            _no_link(root / relative)
        path = root / '.teseo/local/receiver.sqlite'
        for suffix in ('', '-wal', '-shm', '-journal'):
            _no_link(Path(str(path) + suffix))
        return path

    @staticmethod
    def _default():
        return dict(state='idle', enabled=False, paused=True, interval_seconds=45,
                    automatic=False, last_seen_remote_oid=None, last_applied_oid=None,
                    pending_oid=None, last_fetch_at=None, backoff=0,
                    next_check_at=None, error=None, operation_id=None,
                    candidate=None, candidate_digest=None, base_head=None,
                    base_digest=None, revision=0)

    def _load(self, root):
        """Read-only low-level helper, also used under the apply coordinator lock."""
        result = self._default()
        path = self._path(root)
        if path.exists():
            with _connection(path.as_uri() + '?mode=ro', uri=True) as db:
                row = db.execute('SELECT data FROM receiver WHERE id=1').fetchone()
                if row:
                    result.update(parse_json(row[0]))
        result['automatic'] = False
        return result

    def _save(self, root, record):
        """Caller must hold sync._mutex and VaultLock; no live data are written."""
        local = _local_directory(Path(root))
        _ensure_ignored(local)
        record['automatic'] = False
        with _connection(self._path(root)) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS receiver(id INTEGER PRIMARY KEY CHECK(id=1),data BLOB NOT NULL)')
            db.execute('INSERT OR REPLACE INTO receiver VALUES(1,?)', (canonical_json(record),))

    def _config(self, root):
        path = self.sync._path(root)
        if not path.exists():
            raise ContractError('sync_unconfigured', 'Configurare prima il repository dati')
        with _connection(path.as_uri() + '?mode=ro', uri=True) as db:
            return self.sync._config(db)

    @staticmethod
    def _public(record):
        return {key: value for key, value in record.items()
                if key not in ('candidate', 'config')}

    def status(self, vault_id, parameters=None):
        if parameters:
            raise ContractError('invalid_parameters', 'Parametri receiver non supportati')
        try:
            root = self.registry.root(vault_id)
        except ContractError:
            if not hasattr(self.registry, 'operation_root'):
                raise
            root = self.registry.operation_root(vault_id)
        record = self._load(root)
        if self._receive_recovery(root):
            record.update(state='recovery_required',
                          error={'code': 'recovery_required', 'message': 'Ricezione interrotta: completare il recovery'})
        record.update(service_active=bool(self._thread and self._thread.is_alive()),
                      detection_only=True,
                      notice='Il servizio rileva revisioni mentre è attivo. Applicazione manuale con scrittori esterni sospesi; buffer non salvati non rilevabili.')
        return self._public(record)

    def pause(self, vault_id, body=None):
        _fields({} if body is None else body, ())
        root = self.registry.root(vault_id)
        with self.sync._mutex, VaultLock(root):
            record = self._load(root)
            record.update(paused=True, next_check_at=None)
            self._save(root, record)
        self._wake.set()
        return self.status(vault_id)

    def resume(self, vault_id, body=None):
        body = {} if body is None else body
        _fields(body, (), ('interval_seconds',))
        interval = body.get('interval_seconds', 45)
        if type(interval) is not int or not 30 <= interval <= 3600:
            raise ContractError('receiver_interval', 'Intervallo intero tra 30 e 3600 secondi')
        root = self.registry.root(vault_id)
        with self.sync._mutex, VaultLock(root):
            self._config(root)
            record = self._load(root)
            record.update(enabled=True, paused=False, interval_seconds=interval,
                          next_check_at=self._now(), backoff=0, error=None)
            self._save(root, record)
        self._wake.set()
        return self.status(vault_id)

    def _publishing(self, root):
        with _connection(self.sync._path(root).as_uri() + '?mode=ro', uri=True) as db:
            for (data,) in db.execute('SELECT data FROM jobs'):
                if parse_json(data).get('state') not in ('converged', 'noop'):
                    return True
        return False

    @staticmethod
    def _receive_recovery(root):
        try:
            assert_receiver_complete(root)
        except ContractError as error:
            if error.code == 'recovery_required':
                return True
            raise
        return False

    def _delay(self, record):
        return record['interval_seconds'] + int(max(0, min(float(self.jitter()), 15)))

    def _now(self):
        # Canonical JSON v1 permits integer numbers only. Clock precision below
        # a second is unnecessary for a poll interval of at least 30 seconds.
        return int(self.clock())

    def _assert_running(self):
        if self._stop.is_set():
            raise ContractError('receiver_stopped', 'Arresto richiesto; nessuna ulteriore operazione Git')

    def check(self, vault_id, body=None):
        _fields({} if body is None else body, ())
        root = self.registry.root(vault_id)
        with self.sync._mutex, VaultLock(root) as lock:
            record = self._load(root)
            config = self._config(root)
            repo = self.repo_factory(root) if self.repo_factory else self.sync._repo(root)
            try:
                self._assert_running()
                if self._receive_recovery(root):
                    raise ContractError('recovery_required', 'Ricezione interrotta: completare il recovery')
                self.sync._identity(repo, config)
                # Establish only an attested initial baseline, never infer applied R.
                head = repo.head()
                base = capture_snapshot(root)
                if record['last_applied_oid'] is None and head == config['B'] and repo.clean() and base.digest == config['base_digest']:
                    self.sync._assert_candidate(repo, {'oid': head, 'root': str(root)})
                    record['last_applied_oid'] = head
                record.update(state='fetching', error=None, config=config)
                self._save(root, record)
                self._assert_running()
                remote = _oid(repo.fetch(config['remote_url'], config['branch']))
                record.update(last_fetch_at=self._now(), backoff=0,
                              next_check_at=self._now() + self._delay(record))
                self._assert_running()
                previous = record['last_seen_remote_oid']
                if previous and previous != remote and not repo.is_ancestor(previous, remote):
                    raise ContractError('receiver_rewind', 'Cronologia remota riavvolta o divergente: revisione esplicita richiesta')
                record['last_seen_remote_oid'] = remote
                if record.get('candidate') and record['candidate']['oid'] != remote:
                    record.update(candidate=None, candidate_digest=None, base_head=None,
                                  base_digest=None, operation_id=None)
                self._assert_running()
                if remote == head and remote == record['last_applied_oid']:
                    record.update(state='up_to_date', pending_oid=None, candidate=None,
                                  candidate_digest=None, error=None)
                elif remote != head and repo.is_ancestor(remote, head):
                    record.update(state='local_ahead', pending_oid=None, candidate=None,
                                  candidate_digest=None)
                elif not repo.is_ancestor(head, remote):
                    raise ContractError('receiver_diverged', 'HEAD locale e remoto divergono: usare la riconciliazione isolata')
                else:
                    record['pending_oid'] = remote
                    try:
                        with Journal(lock) as journal:
                            journal.assert_notes_idle()
                        if self._publishing(root):
                            raise ContractError('sync_pending', 'Una pubblicazione richiede completamento')
                        if not repo.clean():
                            raise ContractError('git_dirty', 'Working tree o index modificati; ricezione rinviata')
                        base.assert_unchanged(root)
                        if repo.head() != head:
                            raise ContractError('git_head_changed', 'HEAD cambiato durante il controllo')
                    except ContractError as error:
                        record.update(state='waiting_idle', error={'code': error.code, 'message': 'Vault occupato o modificato; candidato conservato'})
                    else:
                        old = record.get('candidate')
                        if not (old and old.get('oid') == remote and record.get('base_head') == head and record.get('base_digest') == base.digest):
                            self._assert_running()
                            repo.audit_history(remote)
                            self._assert_running()
                            candidate = repo.snapshot(remote)
                            self._assert_running()
                            self.sync._assert_candidate(repo, candidate)
                            incoming = capture_snapshot(candidate['root'])
                            validate_raw_unchanged(base, incoming)
                            # Pre-existing events and manifest identity are immutable.
                            for path, digest in base.hashes.items():
                                if path.startswith('.teseo/shared/') and incoming.hashes.get(path) != digest:
                                    raise ContractError('immutable_event_changed', 'Evento condiviso alterato nella revisione ricevuta')
                            if incoming.hashes.get('.teseo/project.json') != base.hashes.get('.teseo/project.json'):
                                raise ContractError('manifest_changed', 'Manifest ricevuto diverso: revisione esplicita richiesta')
                            from .shared_state import validate_snapshot
                            validate_snapshot(incoming)
                            record.update(candidate=candidate, candidate_digest=incoming.digest,
                                          preview=_preview(base,incoming),
                                          base_head=head, base_digest=base.digest,
                                          operation_id=str(uuid4()))
                        record.update(state='pending', error=None)
            except ContractError as error:
                code = error.code
                if code == 'receiver_stopped':
                    record.update(state='waiting_idle', next_check_at=self._now(),
                                  error={'code': code, 'message': 'Servizio arrestato; rilevazione ripresa al prossimo avvio'})
                elif code in ('git_auth', 'git_authentication'):
                    record.update(state='auth_required', paused=True, next_check_at=None,
                                  error={'code': code, 'message': 'Autenticazione Git richiesta; riprendere dopo la correzione'})
                elif code in ('git_network', 'git_timeout'):
                    backoff = min(3600, max(30, record.get('backoff', 0) * 2))
                    record.update(state='offline', backoff=backoff, next_check_at=self._now() + backoff,
                                  error={'code': code, 'message': 'Rete Git non disponibile; nuovo tentativo limitato'})
                else:
                    state = 'diverged' if code in ('receiver_rewind', 'receiver_diverged', 'git_unrelated_history') else 'recovery_required' if code == 'recovery_required' else 'incompatible'
                    record.update(state=state, error={'code': code, 'message': 'Revisione non importata; occorre revisione esplicita'}, next_check_at=self._now() + self._delay(record))
            self._save(root, record)
        return self.status(vault_id)

    def _poll_once(self):
        """One deterministic scheduling tick; useful for clock/fault tests."""
        for item in self.registry.list():
            if self._stop.is_set():
                break
            vault_id = item.get('vault_id')
            if not vault_id:
                continue
            try:
                root = self.registry.root(vault_id)
                record = self._load(root)
                if record['enabled'] and not record['paused'] and (record['next_check_at'] is None or self.clock() >= record['next_check_at']):
                    # Do not wait behind a publishing thread during shutdown.
                    if self.sync._mutex.acquire(blocking=False):
                        try:
                            if not self._stop.is_set():
                                self.check(vault_id)
                        finally:
                            self.sync._mutex.release()
            except (ContractError, OSError, sqlite3.Error):
                # A busy/inaccessible vault must not terminate other poll targets.
                continue

    def _run(self):
        while not self._stop.is_set():
            self._poll_once()
            self._wake.wait(1)
            self._wake.clear()

    def start(self):
        with self._lifecycle:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='teseo-receiver', daemon=False)
            self._thread.start()

    def request_stop(self):
        self._stop.set()
        self._wake.set()

    def close(self):
        self.request_stop()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            # Every Git invocation has a 60 s bound. Wait for the current phase;
            # close must never advertise a stopped service while it still writes.
            thread.join()

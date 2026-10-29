"""Apply manuale (Windows e POSIX) con journal e recovery; nessuna esclusione editor promessa."""
import ctypes
import errno
import html
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from uuid import uuid4

from .contracts import ContractError, content_hash, file_hash, resolve_path, check_path_budget
from .diagnostics import log_unexpected as _log_unexpected
from .storage import Journal, NOTE_KINDS, Snapshot, SnapshotFile, VaultLock, capture_snapshot, _no_link
from .ontology_migrations import migrate
from .ontology_preview import _fields
from .read_api import _parser
from .jobs import _public

FINAL = {'succeeded', 'rolled_back', 'failed', 'blocked_external_change', 'cancelled'}


def _confirmed(body):
    if body.get('mode') != 'manual_paused' or body.get('external_writers_paused') is not True or body.get('semantic_reviewed') is not True:
        raise ContractError('manual_confirmation_required', 'Sospendere editor/hook esterni e revisionare diff, migrazioni e significato; apply automatico disabilitato')


_REMOTE_FS = frozenset({'nfs', 'nfs4', 'cifs', 'smb3', 'smbfs', 'afpfs', 'afs', 'ncpfs', 'fuse.sshfs', 'fuse.rclone', 'ceph', 'glusterfs'})
_MOUNT_LINE = re.compile(r'^(?P<device>.*?) on (?P<point>/.*) \((?P<type>[^,)]+)(?:,[^)]*)?\)$')


def _mounts_linux(text):
    """[(punto di mount, tipo)] da /proc/self/mountinfo."""
    found = []
    for line in text.splitlines():
        head, _, tail = line.partition(' - ')
        fields = head.split(' ')
        if tail and len(fields) > 4:
            found.append((fields[4].replace('\\040', ' '), tail.split(' ')[0]))
    return found


def _mounts_darwin(text):
    """[(punto di mount, tipo)] dall'output di `mount` di macOS: «dispositivo on /punto (tipo, opzioni)»."""
    return [(m['point'], m['type']) for m in map(_MOUNT_LINE.match, text.splitlines()) if m]


def _mount_table():
    if sys.platform == 'darwin':
        try:  # percorso fisso e ambiente ripulito: mai un `mount` trovato nel PATH o nella cartella corrente
            done = subprocess.run(['/sbin/mount'], capture_output=True, timeout=5, env={'PATH': '/usr/bin:/bin:/sbin', 'LC_ALL': 'C'}, check=False)
        except (OSError, subprocess.SubprocessError):
            return []
        return _mounts_darwin(done.stdout.decode('utf-8', 'replace'))
    return _mounts_linux(Path('/proc/self/mountinfo').read_text(encoding='utf-8', errors='replace'))


def _filesystem(root):
    """Tipo di filesystem che contiene root (mount con il prefisso più lungo); None se non determinabile."""
    try:
        target, best, kind = str(Path(root).resolve(strict=True)), -1, None
        for point, fstype in _mount_table():
            if (target == point or target.startswith(point.rstrip('/') + '/')) and len(point) > best:
                best, kind = len(point), fstype
        return kind
    except OSError:
        return None


def _fsync_directory(path):
    """fsync della cartella: rende durevole il nome appena spostato o creato (POSIX; su Windows non esiste)."""
    if os.name == 'nt':
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return  # cartella non apribile in lettura: nessuna garanzia in più da chiedere
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in (errno.EINVAL, errno.ENOTSUP):  # filesystem che non sa sincronizzare le cartelle
            raise
    finally:
        os.close(descriptor)


def _local_volume(root):
    if os.name != 'nt':  # Su POSIX si rifiutano i filesystem di rete noti; dove il tipo non è leggibile non c'è controllo.
        if _filesystem(root) in _REMOTE_FS:
            raise ContractError('apply_platform_unavailable', 'Apply disponibile solo su un volume locale, non su un filesystem di rete')
        return
    function = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_uint
    if function(str(Path(root).anchor)) != 3:  # DRIVE_FIXED; network/removable paths stay disabled.
        raise ContractError('apply_platform_unavailable', 'Apply disponibile solo su volume Windows locale fisso')


def _move_new(staged, target):
    """Sposta staged su un target che non deve esistere. Windows: rename fallisce se esiste; POSIX lo sovrascriverebbe,
    quindi link esclusivo (FileExistsError se uno scrittore esterno ha ricreato il target) e poi unlink di staged."""
    if os.name == 'nt':
        os.rename(staged, target)
        return
    try:
        os.link(staged, target)
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.ENOTSUP, errno.EMLINK, errno.EXDEV) or os.path.lexists(target):
            raise
        os.rename(staged, target)  # filesystem senza hard link: resta solo la finestra di race fra il controllo e il rename
        _fsync_directory(Path(target).parent)
        return
    os.unlink(staged)
    for directory in {Path(target).parent, Path(staged).parent}:
        _fsync_directory(directory)


def _replace(target, staged, backup):
    """Windows: ReplaceFileW conserva il file realmente sostituito, anche nella finestra di race.
    POSIX: rename del target nel backup (i byte spostati sono quelli davvero presenti) e poi inserimento esclusivo di
    staged; fra i due passi il target manca, come già previsto dal recovery (intento durevole nel journal).

    Fallimenti possono lasciare il nome originale assente: il journal mantiene
    intento, staged e backup; non tentare rollback impliciti che perdano dati.
    """
    if os.name != 'nt':
        os.rename(target, backup)
        _fsync_directory(Path(backup).parent)  # il backup deve essere durevole prima che il nome originale si possa perdere
        _move_new(staged, target)
        return
    library = ctypes.WinDLL('kernel32', use_last_error=True)
    function = library.ReplaceFileW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                         ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
    function.restype = ctypes.c_int
    if not function(str(target), str(staged), str(backup), 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def _load(root, relative, digest):
    snapshot = capture_snapshot(resolve_path(root, relative))
    if snapshot.digest != digest:
        raise ContractError('snapshot_corrupt', 'Snapshot non corrispondente al journal')
    return snapshot


def _candidate(snapshot, proposal, selected):
    values = {entry.path: entry.data for entry in snapshot.files}
    suggestions = {item['migration_id']: item for item in proposal['migration_suggestions']}
    if len(set(selected)) != len(selected) or set(selected) - suggestions.keys():
        raise ContractError('invalid_migrations', 'Selezione migrazioni duplicata o sconosciuta')
    values['Wiki reference.md'] = html.unescape(proposal['candidate_schema']).encode('utf-8')
    for identifier in selected:
        item = suggestions[identifier]
        if not item['deterministic']:
            raise ContractError('migration_manual', 'Migrazione non deterministica: correggere manualmente e creare nuova preview')
        values[item['page']] = migrate(values[item['page']], item)
    candidate = Snapshot(tuple(SnapshotFile(path, data) for path, data in sorted(values.items())))
    parsed = _parser().parse_documents({path: data.decode('utf-8') for path, data in values.items()
        if path in ('Wiki reference.md', 'index.md', 'log.md') or (path.startswith('wiki/') and path.count('/') == 1 and path.endswith('.md'))})
    if parsed['problem_details']:
        error = ContractError('migration_invalid', 'Il candidato completo non supera la validazione')
        error.details = list(parsed['problem_details'][:200])
        raise error
    if proposal['shared_records']:
        raise ContractError('shared_mapping_unavailable', 'Mapping eventi condivisi del passo 5 richiesto; nessun apply')
    return candidate


def _path(root, relative):
    path = resolve_path(root, relative)
    cursor = root
    for part in Path(relative).parts:
        cursor /= part
        _no_link(cursor)
    return path


def _write_stage(root, relative, data):
    cursor = root
    for component in Path(relative).parent.parts:
        cursor /= component
        _no_link(cursor)
        cursor.mkdir(exist_ok=True)
    path = _path(root, relative)
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _check_live(root, record, base, candidate):
    live = capture_snapshot(root, allow_missing_schema=True)
    before, after = base.hashes, candidate.hashes
    changes = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    if set(live.hashes) - (set(before) | set(after)):
        raise ContractError('recovery_conflict', 'Nuovi file estranei: nessuna sovrascrittura')
    for path in before.keys() | after.keys():
        digest = live.hashes.get(path)
        allowed = {before.get(path), after.get(path)} if path in changes else {before[path]}
        # A missing owned file is recoverable only when a durable replace intent exists.
        if digest is None and path in changes and any(item['path'] == path for item in record.get('attempts', [])):
            continue
        if digest not in allowed:
            raise ContractError('recovery_conflict', 'Contenuto estraneo da preservare: ' + path)
    for attempt in record.get('attempts', []):
        backup = _path(root, attempt['backup'])
        if backup.exists() and file_hash(backup) != attempt['expected']:
            raise ContractError('recovery_conflict', 'Backup contiene una modifica esterna: conservarlo e risolvere manualmente')
    return live


def execute(journal, identifier, action='finish'):
    """Lock già detenuto, nessun replay automatico. Anche il rollback è esplicito."""
    record = journal.get(identifier)
    root = journal.lock.root
    base = _load(root, record['snapshot_path'], record['base_content_digest'])
    checkpoint = record['checkpoint']
    candidate = _load(root, checkpoint['candidate_path'], checkpoint['candidate_digest'])
    desired = candidate if action == 'finish' else base
    from .graph_service import rebuild
    isolated = checkpoint['candidate_path'] if action == 'finish' else record['snapshot_path']
    rebuild(resolve_path(root, isolated))
    live = _check_live(root, record, base, candidate)
    record.update(state='applying', error=None, recovery_action=action)
    journal.save_ontology(record)
    desired_files = {entry.path: entry.data for entry in desired.files}
    changed = [path for path in base.hashes.keys() | candidate.hashes.keys() if base.hashes.get(path) != candidate.hashes.get(path)]
    for path in sorted(changed, key=lambda path: (path.startswith('.teseo/shared/events/'), path == 'Wiki reference.md', path)):
        if live.hashes.get(path) == desired.hashes.get(path):
            continue
        live = _check_live(root, record, base, candidate)
        target = _path(root, path)
        attempt_id = str(uuid4())
        prefix = '.teseo/local/transactions/' + identifier + '/' + attempt_id
        removing = path not in desired_files
        staged = _write_stage(root, prefix + '/candidate', desired_files.get(path,b''))
        backup = prefix + '/displaced'
        attempt = {'path': path, 'backup': backup, 'expected': live.hashes.get(path), 'after': desired.hashes.get(path)}
        record.setdefault('attempts', []).append(attempt)
        journal.save_ontology(record)  # Durable intent before replacement; crash can infer state from hashes.
        _check_live(root, record, base, candidate)
        if removing:
            os.rename(target, _path(root, backup))  # Preserve actual removed bytes; verify below before continuing.
        elif target.exists():
            _replace(target, staged, _path(root, backup))
        else:
            _move_new(staged, target)  # fallisce se uno scrittore esterno ha ricreato il target
        _check_live(root, record, base, candidate)
        live = capture_snapshot(root)
    if capture_snapshot(root).digest != desired.digest:
        raise ContractError('recovery_conflict', 'Digest finale diverso dal candidato')
    reference = rebuild(root, lock=journal.lock, operation_id=identifier)
    record.update(state='succeeded' if action == 'finish' else 'rolled_back', error=None)
    record['checkpoint'].update(content_revision=reference.content_revision, graph_generation=reference.generation,
                                changed_files=changed, mode='manual_paused', external_exclusion=False)
    if record['kind'] not in ('ontology_apply', 'graph_edit') and action=='finish':
        journal.complete_skill(record)
    else:
        journal.save_ontology(record)
    # Projection is a replayable cache after the logical file checkpoint, never its authority.
    from .shared_state import rebuild_projection, snapshot_events
    try:
        projection=root/'.teseo/local/shared-state.sqlite'
        for suffix in ('','-journal','-wal','-shm'): _no_link(Path(str(projection)+suffix))
        rebuild_projection(projection,snapshot_events(desired,record['vault_id']),record['vault_id'])
    except Exception as error:
        _log_unexpected(error)  # Cache non autorevole: import/rebuild esplicito la riallinea; eventi e checkpoint restano la fonte.
    return record


class ApplyService:
    def __init__(self, registry, previews, edits=None, publisher=None):
        self.registry, self.previews, self.edits, self.publisher = registry, previews, edits, publisher
        self._publications = {}
        self._publishers = {}
        self._mutex = threading.RLock()
        self._workers = {}
        self._requests = {}
        self._stop = False

    def active(self, vault_id):
        with self._mutex:
            value = self._workers.get(vault_id)
            return value[0] if value else None

    def submit(self, vault_id, body, if_match):
        _fields(body, ('preview_id', 'proposal_hash', 'selected_migrations', 'idempotency_key',
                       'mode', 'external_writers_paused', 'semantic_reviewed'))
        _confirmed(body)
        if (not isinstance(body['preview_id'], str) or not isinstance(body['proposal_hash'], str)
                or not re.fullmatch('[0-9a-f]{64}', body['proposal_hash'])
                or not isinstance(body['idempotency_key'], str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}', body['idempotency_key'])
                or not isinstance(body['selected_migrations'], list) or len(body['selected_migrations']) > 1000
                or any(not isinstance(item, str) for item in body['selected_migrations'])):
            raise ContractError('invalid_payload', 'Richiesti preview, hash, selezione e chiave idempotente validi')
        payload = dict(body, base_content_digest=self._base(if_match))

        def candidate(snapshot):
            proposal = self.previews.proposal(vault_id, body['preview_id'], body['proposal_hash'])
            if proposal['base_content_digest'] != snapshot.digest:
                raise ContractError('preview_stale', 'Contenuti cambiati: creare nuova preview')
            return _candidate(snapshot, proposal, body['selected_migrations'])
        return self._submit(vault_id, 'ontology_apply', payload, body['idempotency_key'], candidate)

    def submit_edit(self, vault_id, node_id, body, if_match):
        """Apply di una modifica del grafo (graph_edit): stesso journal, lock, rebuild e recovery dell'ontologia."""
        _fields(body, ('preview_id', 'proposal_hash', 'idempotency_key', 'mode', 'external_writers_paused', 'semantic_reviewed'))
        _confirmed(body)
        if (self.edits is None or not isinstance(body['preview_id'], str) or not isinstance(body['proposal_hash'], str)
                or not re.fullmatch('[0-9a-f]{64}', body['proposal_hash'])
                or not isinstance(body['idempotency_key'], str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}', body['idempotency_key'])):
            raise ContractError('invalid_payload', 'Richiesti preview, hash e chiave idempotente validi')
        payload = dict(body, base_content_digest=self._base(if_match), node=node_id)

        def candidate(snapshot):
            record, data = self.edits.proposal(vault_id, body['preview_id'], body['proposal_hash'])
            if record['base_content_digest'] != snapshot.digest or record['page'] != node_id:
                raise ContractError('preview_stale', 'Contenuti o pagina cambiati: creare nuova preview')
            if not record['valid']:
                raise ContractError('migration_invalid', 'La proposta non supera la validazione del grafo')
            values = {entry.path: entry.data for entry in snapshot.files}
            values[record['path']] = data
            return Snapshot(tuple(SnapshotFile(path, content) for path, content in sorted(values.items())))
        return self._submit(vault_id, 'graph_edit', payload, body['idempotency_key'], candidate)

    @staticmethod
    def _base(if_match):
        if not isinstance(if_match, str) or not re.fullmatch('"[0-9a-f]{64}"', if_match):
            raise ContractError('precondition_required', 'If-Match deve contenere il digest base tra virgolette')
        return if_match[1:-1]

    def _submit(self, vault_id, kind, payload, idempotency_key, candidate_of):
        with self._mutex:
            key = (vault_id, idempotency_key)
            if key in self._requests:
                digest, record = self._requests[key]
                if digest != content_hash(payload):
                    raise ContractError('idempotency_conflict', 'Chiave già usata con payload diverso')
                return _public(record)
            self._available(vault_id)
            root = self.registry.operation_root(vault_id)
            _local_volume(root)
            check_path_budget(root)
            with VaultLock(root, recovery=True) as lock, Journal(lock) as journal:
                previous = journal.find_request(kind, payload, idempotency_key)
                if previous:
                    return _public(previous)
                journal.assert_notes_idle()
                snapshot = capture_snapshot(root)
                if snapshot.digest != payload['base_content_digest']:
                    raise ContractError('preview_stale', 'Contenuti cambiati: creare nuova preview')
                candidate = candidate_of(snapshot)
                record = journal.create(kind, payload, idempotency_key, snapshot)
                identifier = record['operation_id']
                try:
                    journal.transition(identifier, 'waiting_lock')
                    journal.transition(identifier, 'running')
                    journal.transition(identifier, 'validating')
                    record = journal.prepare(identifier, candidate)
                    # Build and validate SQLite in the isolated candidate before touching live Markdown.
                    from .graph_service import rebuild
                    rebuild(resolve_path(root, record['checkpoint']['candidate_path']))
                except Exception:
                    journal.transition(identifier, 'failed', error={'code': 'prepare_failed', 'message': 'Preparazione non completata; nessuna nota applicata'})
                    raise
            self._requests[key] = (content_hash(payload), record)
            self._launch(vault_id, identifier, 'finish')
            return _public(record)

    def _available(self, vault_id):
        if self._stop:
            raise ContractError('service_stopping', 'Servizio in arresto')
        if vault_id in self._workers:
            raise ContractError('vault_busy', 'Operazione note già attiva')
        if len(self._workers) >= 2:
            raise ContractError('job_limit', 'Due apply già attivi')

    def _launch(self, vault_id, identifier, action):
        worker = threading.Thread(target=self._run, args=(vault_id, identifier, action), daemon=False)
        self._workers[vault_id] = (identifier, worker)
        try:
            worker.start()
        except BaseException:
            del self._workers[vault_id]
            raise

    def recover(self, vault_id, identifier, body, if_match):
        _fields(body, ('action', 'mode', 'external_writers_paused', 'semantic_reviewed'))
        _confirmed(body)
        if body['action'] not in ('finish', 'rollback'):
            raise ContractError('invalid_payload', 'Recovery richiede finish o rollback')
        with self._mutex:
            self._available(vault_id)
            root = self.registry.operation_root(vault_id)
            _local_volume(root)
            with VaultLock(root, recovery=True) as lock, Journal(lock) as journal:
                record = journal.get(identifier)
                if record['kind'] not in NOTE_KINDS:
                    raise ContractError('operation_missing', 'Operazione ontologia non trovata')
                terminal = 'succeeded' if body['action'] == 'finish' else 'rolled_back'
                if record['state'] == terminal:
                    return _public(record)
                if record['state'] in FINAL or not (record.get('checkpoint') or {}).get('candidate_path'):
                    raise ContractError('recovery_conflict', 'Operazione non recuperabile in questa modalità')
                if if_match != '"' + capture_snapshot(root, allow_missing_schema=True).digest + '"':
                    raise ContractError('preview_stale', 'Digest recovery cambiato; rileggere lo stato')
                journal.assert_notes_idle(identifier)
                record.update(state='recovery_required')
                journal.save_ontology(record)
            self._launch(vault_id, identifier, body['action'])
            return _public(record)

    def apply_skill(self, vault_id, identifier, body, if_match):
        from .operations import KINDS
        from .operations import _fields
        _fields(body,('mode','external_writers_paused','semantic_reviewed'))
        _confirmed(body)
        with self._mutex:
            self._available(vault_id)
            root=self.registry.operation_root(vault_id)
            _local_volume(root)
            with VaultLock(root) as lock,Journal(lock) as journal:
                record=journal.get(identifier)
                if record['kind'] not in KINDS:
                    raise ContractError('operation_missing','Ciclo skill non trovato')
                if record['state']=='succeeded':
                    return _public(record)
                if record['state']!='prepared' or not record.get('validation'):
                    raise ContractError('recovery_conflict','Richiesto candidato preparato e validato')
                if if_match!='"'+record['base_content_digest']+'"' or capture_snapshot(root).digest!=record['base_content_digest']:
                    raise ContractError('blocked_external_change','Base modificata dopo il ciclo; nessuna sovrascrittura')
                journal.assert_notes_idle(identifier)
            self._launch(vault_id,identifier,'finish')
            return _public(record)

    def publication(self, identifier):
        with self._mutex:
            return self._publications.get(identifier)

    def _publish(self, vault_id, identifier, root):
        """Pubblicazione automatica dopo una modifica del grafo: in un thread proprio, a lock e slot rilasciati, così una
        rete lenta non blocca altri apply. Esito mai bloccante per la modifica; poi il grafo si ricostruisce, perché il
        commit appena fatto cambia gli autori."""
        try:
            result = dict(self.publisher(root))
        except Exception as error:
            _log_unexpected(error)
            result = {'state': 'failed', 'message': 'Pubblicazione non completata: usare Pubblicazione Git nella dashboard'}
        if result.get('state') == 'published':
            try:
                from .graph_service import rebuild
                rebuild(root)
            except Exception as error:  # altra operazione sulle note in corso o lock occupato: il push è comunque avvenuto
                _log_unexpected(error)
                result['rebuild'] = 'failed'
                result['message'] = (result.get('message') or '') + ' · Grafo da ricostruire (Ricostruisci grafo) per aggiornare gli autori'
        with self._mutex:
            self._publications[identifier] = result
            self._publishers.pop(identifier, None)

    def _start_publication(self, vault_id, identifier, root):
        with self._mutex:
            self._publications[identifier] = {'state': 'pending', 'message': 'Pubblicazione in corso'}
            while len(self._publications) > 64:
                del self._publications[next(iter(self._publications))]
            thread = threading.Thread(target=self._publish, args=(vault_id, identifier, root), daemon=False)
            self._publishers[identifier] = thread
        thread.start()

    def _run(self, vault_id, identifier, action):
        done = None
        root = None
        try:
            root = self.registry.operation_root(vault_id)
            with VaultLock(root, timeout=5, recovery=True) as lock, Journal(lock) as journal:
                try:
                    record = journal.get(identifier)
                    if self._stop:
                        raise ContractError('service_stopping', 'Servizio in arresto: recovery esplicito richiesto')
                    result = execute(journal, identifier, action)
                except Exception as error:
                    if not isinstance(error, ContractError): _log_unexpected(error)
                    record = journal.get(identifier)
                    record.update(state='recovery_required', error={
                        'code': error.code if isinstance(error, ContractError) else 'apply_interrupted',
                        'message': str(error)[:500] if isinstance(error, ContractError) else 'Applicazione interrotta: verificare snapshot, backup e stato dei file'})
                    journal.save_ontology(record)
                else:
                    done = result
            if done is not None and not (done['kind'] == 'graph_edit' and done['state'] == 'succeeded' and action == 'finish' and self.publisher):
                done = None
        except Exception as error:
            # Lock/identity/storage failure leaves a durable record for explicit recovery; la causa va almeno loggata.
            done = None
            _log_unexpected(error)
        finally:
            with self._mutex:
                self._workers.pop(vault_id, None)
                self._requests = {key: value for key, value in self._requests.items()
                                  if value[1]['operation_id'] != identifier}
        if done is not None:
            self._start_publication(vault_id, identifier, root)

    def request_stop(self):
        with self._mutex:
            self._stop = True

    def close(self):
        self.request_stop()
        with self._mutex:
            workers = list(self._workers.values())
        for _, worker in workers:
            worker.join()
        with self._mutex:
            publishers = list(self._publishers.values())  # i worker hanno già avviato le pubblicazioni: si attendono come i rebuild
        for publisher in publishers:
            publisher.join()

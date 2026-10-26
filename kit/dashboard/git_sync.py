"""Conservative Git primitives for *data* repositories, never the kit checkout.

Callers own the vault lock and must explicitly pause external writers before
checkpoint/adoption. Git locks and hash preconditions detect, not exclude, editors.
No credentials or raw subprocess output are persisted or returned on failures.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
from uuid import UUID, uuid4

from .contracts import (ContractError, PathKind, classify_path, is_junction, parse_manifest,
                        portable_path, resolve_path, validate_paths)
from .storage import _no_link, capture_snapshot

_OID = re.compile(r'^[0-9a-f]{40}(?:[0-9a-f]{24})?$')
_TEXT_RAW = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml', '.xml', '.html', '.htm', '.rst', '.tsv', '.log'}
MAX_FILE = 8 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
_SECRET = re.compile(rb'(?:-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'
                     rb'|\bgh[pousr]_[A-Za-z0-9_]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}'
                     rb'|\bsk-proj-[A-Za-z0-9_-]{20,})')


def _executable(name):
    # Windows CreateProcess and shutil.which may otherwise search cwd first.
    # Vault files must never supply a git.exe/ssh.exe used by the coordinator.
    for directory in os.environ.get('PATH', '').split(os.pathsep):
        if not directory or not Path(directory).is_absolute():
            continue
        found = shutil.which(str(Path(directory) / name))
        if found:
            return str(Path(found).resolve(strict=True))
    return None


def _oid(value):
    if not isinstance(value, str) or not _OID.fullmatch(value):
        raise ContractError('git_invalid_oid', 'OID Git non valido')
    return value


def _branch(value):
    if (not isinstance(value, str) or not value or len(value) > 200
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', value)
            or any(x in value for x in ('..', '//', '@{'))
            or any(p.startswith('.') or p.endswith(('.', '.lock')) for p in value.split('/'))
            or value.endswith('/')):
        raise ContractError('git_invalid_branch', 'Branch Git non valido')
    return value


def validate_remote(value, *, allow_local_remote=False):
    """No credentials, arbitrary hosts, helpers, option injection or URL queries."""
    if not isinstance(value, str) or len(value) > 1024:
        raise ContractError('git_invalid_remote', 'Remote Git non valido')
    component = r'[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?'
    if re.fullmatch(rf'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/){component}/{component}(?:\.git)?', value):
        if '/..' not in value and '/.' not in value and not value.endswith('/.git'):
            return value
    if allow_local_remote and not value.startswith('-') and '\x00' not in value:
        target = Path(value)
        if target.is_absolute() and target.is_dir():
            return str(target.resolve(strict=True))
    raise ContractError('git_invalid_remote', 'Consentiti solo repository GitHub HTTPS/SSH senza credenziali nell’URL')


def github_repository_url(remote):
    try:
        validate_remote(remote)
    except ContractError:
        return None
    path = remote.split('github.com', 1)[1].lstrip('/:').removesuffix('.git')
    return 'https://github.com/' + path


def _env():
    # Drop all inherited GIT_*, shell-startup, pager and helper overrides.
    keys = ('PATH', 'SystemRoot', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
            'HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'SSH_AUTH_SOCK', 'APPDATA', 'LOCALAPPDATA')
    env = {k: os.environ[k] for k in keys if k in os.environ}
    # Voci PATH vuote o relative farebbero cercare sotto-comandi git-* nella cwd.
    env['PATH'] = os.pathsep.join(d for d in env.get('PATH', '').split(os.pathsep) if d and os.path.isabs(d))
    ssh = _executable('ssh')
    ssh_command = (shlex.quote(ssh.replace('\\', '/')) if ssh else
                   shlex.quote(sys.executable.replace('\\', '/')) + " -c 'raise SystemExit(1)'")
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', GIT_PAGER='cat',
               GIT_SSH_COMMAND=ssh_command + ' -oBatchMode=yes -oStrictHostKeyChecking=yes', GIT_SSH_VARIANT='ssh',
               GIT_NO_REPLACE_OBJECTS='1', LC_ALL='C', LANG='C')
    return env


def _invoke(root, args, *, input=None, env_extra=None, file_transport=False, check=True, credential_helper=None):
    env = _env()
    env.update(env_extra or {})
    executable = _executable('git')
    if not executable:
        raise ContractError('git_unavailable', 'Git non disponibile')
    command = [str(Path(executable).resolve()), '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false',
               '-c', 'core.autocrlf=false', '-c', 'core.attributesFile=' + os.devnull,
               '-c', 'core.quotePath=false', '-c', 'commit.gpgSign=false', '-c', 'tag.gpgSign=false',
               '-c', 'protocol.ext.allow=never', '-c', 'protocol.file.allow=' + ('always' if file_transport else 'never'),
               '-c', 'http.sslVerify=true', '-c', 'fetch.fsckObjects=true',
               '-c', 'submodule.recurse=false', '-c', 'fetch.recurseSubmodules=false',
               '-c', 'credential.helper=', '-c', 'credential.interactive=false',
               *(['-c', 'credential.helper=' + credential_helper] if credential_helper in ('manager', 'manager-core') else []),
               *args]
    try:
        result = subprocess.run(command, cwd=root, input=input, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, shell=False, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise ContractError('git_timeout', 'Git non ha confermato il risultato entro il timeout; verificare prima di ritentare') from error
    except OSError as error:
        raise ContractError('git_unavailable', 'Git non disponibile') from error
    if len(result.stdout) > MAX_TREE:
        raise ContractError('git_output_limit', 'Output Git oltre il limite')
    if check and result.returncode:
        # --porcelain push writes per-ref rejections to stdout on some Git
        # versions; classify both streams without exposing either to clients.
        stderr = (result.stderr + b'\n' + result.stdout).lower()
        code = 'git_failed'
        if b'non-fast-forward' in stderr or b'fetch first' in stderr or b'[rejected]' in stderr:
            code = 'git_push_rejected'
        elif any(x in stderr for x in (b'authentication failed', b'permission denied', b'could not read username')):
            code = 'git_auth'
        elif any(x in stderr for x in (b'could not resolve', b'unable to access', b'connection timed out', b'connection refused')):
            code = 'git_network'
        elif any(x in stderr for x in (b'remote rejected', b'protected branch', b'pre-receive hook declined', b'repository rule')):
            code = 'git_policy'
        raise ContractError(code, 'Comando Git non completato; nessuna cancellazione o riscrittura automatica')
    return result


class GitRepository:
    def __init__(self, root, *, allow_local_remote=False):
        self.root = Path(root).resolve(strict=True)
        self.allow_local_remote = allow_local_remote
        self.credential_helper = None
        self.global_author = {}
        self._entry_cache, self._blob_cache, self._blob_cache_bytes = {}, {}, 0
        _no_link(self.root / '.git')
        if not (self.root / '.git').is_dir():
            raise ContractError('git_repository_required', 'Richiesto un clone dati con directory .git propria')
        top = self.run('rev-parse', '--show-toplevel').strip()
        if Path(top).resolve() != self.root:
            raise ContractError('git_wrong_root', 'La radice del repository non coincide con il vault')
        self._safe_config()
        # Read only scalar values from the user's own config, with includes off.
        # Never inherit arbitrary !shell helpers or repository credential config.
        global_config = Path.home() / '.gitconfig'
        if global_config.is_file() and global_config.stat().st_size <= 1024 * 1024:
            for key in ('user.name', 'user.email', 'credential.helper'):
                result = _invoke(self.root, ['config', '--file', str(global_config), '--no-includes', '--get-all', key], check=False)
                values = result.stdout.decode('utf-8').strip().splitlines()
                if not result.returncode and len(values) == 1:
                    value = values[0]
                    if key == 'credential.helper':
                        self.credential_helper = value if value in ('manager', 'manager-core') else None
                    elif value and len(value) <= 256 and not any(ord(c) < 32 for c in value):
                        local_value = _invoke(self.root, ['config', '--local', '--get', key], check=False)
                        if local_value.returncode:
                            self.global_author[key.removeprefix('user.')] = value

    def _bytes(self, *args, input=None, env=None, file_transport=False, check=True):
        identity_env = {}
        for field, value in self.global_author.items():
            for role in ('AUTHOR', 'COMMITTER'):
                identity_env['GIT_' + role + '_' + ('NAME' if field == 'name' else 'EMAIL')] = value
        identity_env.update(env or {})
        return _invoke(self.root, args, input=input, env_extra=identity_env,
                       file_transport=file_transport, check=check, credential_helper=self.credential_helper)

    def run(self, *args, input=None):
        if input is not None and isinstance(input, str):
            input = input.encode('utf-8')
        try:
            return self._bytes(*args, input=input).stdout.decode('utf-8')
        except UnicodeError as error:
            raise ContractError('git_invalid_utf8', 'Git ha restituito dati non UTF-8') from error

    def _safe_config(self):
        # Object/ref/index writes must stay inside this clone, not redirected
        # through a linked .git child or alternate object store.
        for directory, dirs, names in os.walk(self.root / '.git', followlinks=False):
            for name in (*dirs, *names):
                _no_link(Path(directory) / name)
        data = self.run('config', '--local', '--null', '--list')
        for pair in data.split('\x00'):
            key = pair.partition('\n')[0].lower()
            if (key.startswith(('filter.', 'include.', 'includeif.', 'extensions.', 'credential.', 'url.', 'http.', 'https.',
                                'gpg.', 'pager.', 'alias.', 'submodule.', 'maintenance.', 'fsck.'))
                    or (key.startswith('diff.') and key.rsplit('.', 1)[-1] in ('textconv', 'command'))
                    or key in ('core.askpass', 'core.editor', 'core.pager', 'core.hookspath', 'core.protectntfs',
                               'sequence.editor', 'uploadpack.packobjectshook')
                    or (key.startswith('merge.') and key.endswith('.driver'))
                    or key == 'diff.external'
                    or key in ('core.worktree', 'core.sshcommand', 'core.fsmonitor', 'core.attributesfile',
                               'core.gitproxy', 'core.alternateRefsCommand'.lower())
                    or (key.startswith('remote.') and key.rsplit('.', 1)[-1] in
                        ('uploadpack', 'receivepack', 'proxy', 'vcs', 'pushurl'))):
                raise ContractError('git_unsafe_config', 'Configurazione Git eseguibile o ambigua; rivederla esplicitamente')
        for relative in ('.git/objects/info/alternates', '.git/info/attributes', '.git/info/grafts'):
            path = self.root / relative
            _no_link(path)
            if path.exists() and path.read_bytes().strip():
                raise ContractError('git_unsafe_config', 'Attributi o object alternates richiedono revisione esplicita')

    def head(self):
        return _oid(self.run('rev-parse', '--verify', 'HEAD').strip())

    def branch(self):
        value = self.run('symbolic-ref', '--quiet', '--short', 'HEAD').strip()
        return _branch(value)

    def clean(self):
        return not self.run('status', '--porcelain=v1', '-z', '--untracked-files=all')

    def remote_url(self, remote='origin'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', remote):
            raise ContractError('git_invalid_remote', 'Nome remote non valido')
        result = self._bytes('config', '--get', 'remote.' + remote + '.url', check=False)
        if result.returncode:
            return None
        value = result.stdout.decode('utf-8').strip()
        return validate_remote(value, allow_local_remote=self.allow_local_remote)

    def _manifest(self):
        path = self.root / '.teseo/project.json'
        _no_link(self.root / '.teseo')
        _no_link(path)
        if not path.is_file() or path.stat().st_size > 65536:
            raise ContractError('git_manifest_required', 'Richiesto manifest dati compatibile')
        return parse_manifest(path.read_bytes())

    @staticmethod
    def _allowed(path, manifest, data=None):
        portable_path(path)
        kind = classify_path(path)
        scope = path == '.teseo/project.json' or any(
            path.startswith(p) if p.endswith('/') else path == p for p in manifest['shared_paths'])
        if not scope or kind not in (PathKind.MANIFEST, PathKind.MARKDOWN, PathKind.RAW, PathKind.EVENT):
            return False
        if kind == PathKind.RAW and Path(path).suffix.lower() not in _TEXT_RAW:
            return False
        if data is not None:
            if len(data) > MAX_FILE or b'\x00' in data or _SECRET.search(data):
                return False
            try:
                data.decode('utf-8')
            except UnicodeError:
                return False
        return True

    def _entries(self, oid):
        oid = _oid(oid)
        if oid in self._entry_cache:
            return dict(self._entry_cache[oid])
        data = self._bytes('ls-tree', '-rz', '--full-tree', oid).stdout
        entries = {}
        for record in data.split(b'\x00'):
            if not record:
                continue
            header, path = record.split(b'\t', 1)
            mode, kind, object_id = header.decode('ascii').split()
            try:
                path = path.decode('utf-8')
            except UnicodeError as error:
                raise ContractError('git_unsafe_path', 'Percorso Git non UTF-8') from error
            portable_path(path)
            if kind != 'blob' or mode not in ('100644',):
                raise ContractError('git_unsafe_tree', 'Symlink, eseguibili o submodule vietati', path)
            entries[path] = object_id
        validate_paths(entries)
        if len(entries) > 10000:
            raise ContractError('git_tree_limit', 'Troppi file nel repository dati')
        if len(self._entry_cache) >= 256:
            self._entry_cache.clear()
        self._entry_cache[oid] = dict(entries)
        return entries

    def _blob(self, oid):
        oid = _oid(oid)
        if oid in self._blob_cache:
            return self._blob_cache[oid]
        size = int(self.run('cat-file', '-s', oid).strip())
        if size > MAX_FILE:
            raise ContractError('git_file_limit', 'File Git oltre 8 MiB')
        data = self._bytes('cat-file', 'blob', oid).stdout
        if self._blob_cache_bytes + len(data) > MAX_TREE:
            self._blob_cache.clear()
            self._blob_cache_bytes = 0
        self._blob_cache[oid] = data
        self._blob_cache_bytes += len(data)
        return data

    def tree(self, oid):
        """Validated data tree bytes, bounded; also used by semantic validators."""
        entries = self._entries(oid)
        if '.teseo/project.json' not in entries:
            raise ContractError('git_manifest_required', 'Il tree remoto non contiene il manifest dati')
        manifest = parse_manifest(self._blob(entries['.teseo/project.json']))
        result, total = {}, 0
        for path, object_id in entries.items():
            data = self._blob(object_id)
            total += len(data)
            if total > MAX_TREE:
                raise ContractError('git_tree_limit', 'Tree dati oltre 64 MiB')
            if not self._allowed(path, manifest, data):
                raise ContractError('git_tracked_policy', 'File tracked fuori policy dati', path)
            result[path] = data
        return result

    def inspect(self):
        self._safe_config()
        manifest = self._manifest()
        violations = []
        try:
            entries = self._entries(self.head())
            for path, object_id in entries.items():
                if not self._allowed(path, manifest, self._blob(object_id)):
                    violations.append(path)
        except ContractError as error:
            if error.path:
                violations.append(error.path)
            else:
                raise
        author = {}
        for field in ('name', 'email'):
            result = self._bytes('config', '--get', 'user.' + field, check=False)
            author[field] = result.stdout.decode('utf-8').strip() if not result.returncode else self.global_author.get(field, '')
        return {'branch': self.branch(), 'head': self.head(), 'remote_url': self.remote_url(),
                'tracked_violations': sorted(violations), 'author': author,
                'clean': self.clean(), 'history_audited': False}

    def preview(self, selection=None):
        result = self._preview_files(selection)
        info = self.inspect()
        return {**result, 'tracked_violations': info['tracked_violations'],
                'head': info['head'], 'branch': info['branch']}

    def _preview_files(self, selection=None):
        manifest = self._manifest()
        if selection is None:
            selection = []
        if not isinstance(selection, list) or len(selection) > 10000 or any(not isinstance(p, str) for p in selection):
            raise ContractError('git_invalid_selection', 'Selezione di percorsi richiesta')
        validate_paths(selection)
        files, excluded, total = [], [], 0
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            parent = Path(directory)
            dirs[:] = [d for d in dirs if d != '.git' and not (parent / d).is_symlink()
                       and not is_junction(parent / d)
                       and (parent / d) != self.root / '.teseo/local']
            for name in names:
                path = parent / name
                relative = path.relative_to(self.root).as_posix()
                _no_link(path)
                if not self._allowed(relative, manifest) or path.stat().st_size > MAX_FILE:
                    excluded.append(relative)
                    continue
                data = path.read_bytes()
                if not self._allowed(relative, manifest, data) or (relative.startswith('raw/') and relative not in selection):
                    excluded.append(relative)
                    continue
                total += len(data)
                if total > MAX_TREE or len(files) >= 10000:
                    raise ContractError('git_tree_limit', 'Preview dati oltre i limiti')
                files.append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)})
        selected = {entry['path'] for entry in files}
        if not set(selection) <= selected:
            raise ContractError('git_invalid_selection', 'Fonte selezionata assente o fuori policy')
        return {'files': sorted(files, key=lambda f: f['path']), 'excluded': sorted(excluded)}

    def _changes(self):
        records = self.run('status', '--porcelain=v1', '-z', '--untracked-files=all').split('\x00')
        changes = set()
        for record in records:
            if not record:
                continue
            status, path = record[:2], record[3:]
            if status != '??' and status[0] != ' ':
                raise ContractError('git_index_not_empty', 'Index non vuoto: nessuna modifica estranea viene committata')
            portable_path(path)
            changes.add(path)
        return changes

    def _check_files(self, files, base):
        if not isinstance(files, dict) or len(files) > 10000:
            raise ContractError('git_invalid_selection', 'Richiesta mappa esplicita percorso/hash')
        validate_paths(files)
        manifest = self._manifest()
        old = self._entries(base)
        for path, digest in files.items():
            if not self._allowed(path, manifest):
                raise ContractError('git_tracked_policy', 'Percorso fuori policy dati', path)
            target = resolve_path(self.root, path)
            for ancestor in (self.root / path, *(self.root / path).parents):
                if ancestor == self.root:
                    break
                _no_link(ancestor)
            if digest is None:
                if target.exists() or path not in old or path.startswith(('raw/', '.teseo/shared/events/')):
                    raise ContractError('git_hash_changed', 'Eliminazione non valida o contenuto immutabile', path)
                continue
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or not target.is_file():
                raise ContractError('git_hash_changed', 'Hash o file attribuito non valido', path)
            data = target.read_bytes()
            if not self._allowed(path, manifest, data) or hashlib.sha256(data).hexdigest() != digest:
                raise ContractError('git_hash_changed', 'Contenuto attribuito cambiato', path)
            if path.startswith(('raw/', '.teseo/shared/events/')) and path in old and self._blob(old[path]) != data:
                raise ContractError('git_immutable_changed', 'Fonte o evento preesistente modificato', path)

    def checkpoint(self, operation_id, expected_head, files, message='Teseo: checkpoint validato'):
        try:
            if str(UUID(operation_id)) != operation_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as error:
            raise ContractError('git_invalid_operation', 'Operation UUID non valido') from error
        _oid(expected_head)
        info = self.inspect()
        if info['tracked_violations']:
            raise ContractError('git_tracked_policy', 'File tracked vietati: pulizia esplicita richiesta')
        existing = self.find_checkpoint(operation_id, expected_head, files)
        if existing and self.head() == existing:
            if not self.clean():
                # Crash fra update-ref e read-tree: il commit esiste, l'indice è ancora quello vecchio.
                # read-tree senza -u riallinea solo l'indice e non tocca i file di lavoro.
                self.run('read-tree', existing)
                if not self.clean():
                    raise ContractError('git_post_commit_change', 'Checkpoint conservato; scritture esterne bloccano la pubblicazione')
            return existing
        if self.head() != expected_head:
            raise ContractError('git_head_changed', 'HEAD è cambiato; checkpoint conservati')
        self._check_files(files, expected_head)
        if not self._changes() <= set(files):
            raise ContractError('git_foreign_changes', 'Modifiche estranee all’operazione: pubblicazione sospesa')
        if not self._changes():
            return expected_head
        if not info['author']['name'] or not info['author']['email']:
            raise ContractError('git_author_required', 'Configurare identità autore Git locale')
        if not isinstance(message, str) or len(message) > 500 or any(ord(c) < 32 for c in message):
            raise ContractError('git_invalid_message', 'Messaggio commit non valido')
        local = self.root / '.teseo/local'
        _no_link(local)
        local.mkdir(exist_ok=True)
        ignore = local / '.gitignore'
        _no_link(ignore)
        if not ignore.exists():
            ignore.write_bytes(b'*\n')
        index = local / ('git-index-' + str(uuid4()))
        env = {'GIT_INDEX_FILE': str(index)}
        try:
            self._bytes('read-tree', expected_head, env=env)
            updates = []
            for path, digest in sorted(files.items()):
                if digest is None:
                    updates.append(('0 ' + '0' * len(expected_head) + '\t' + path + '\x00').encode('utf-8'))
                else:
                    oid = self._bytes('hash-object', '-w', '--stdin', '--no-filters', input=(self.root / path).read_bytes()).stdout.decode().strip()
                    updates.append(('100644 ' + oid + '\t' + path + '\x00').encode('utf-8'))
            self._bytes('update-index', '-z', '--index-info', input=b''.join(updates), env=env)
            tree = self._bytes('write-tree', env=env).stdout.decode().strip()
            self._check_files(files, expected_head)
            if self.head() != expected_head or not self._changes() <= set(files):
                raise ContractError('git_foreign_changes', 'File o HEAD cambiati prima del checkpoint')
            body = f'{message}\n\nTeseo-Operation: {operation_id}\nTeseo-Base: {expected_head}\n'
            oid = self.run('commit-tree', tree, '-p', expected_head, input=body).strip()
            ref = 'refs/heads/' + info['branch']
            self.run('update-ref', ref, oid, expected_head)
            self.run('read-tree', tree)
            if self.head() != oid or not self.clean():
                raise ContractError('git_post_commit_change', 'Checkpoint conservato; scritture esterne bloccano la pubblicazione')
            return oid
        finally:
            index.unlink(missing_ok=True)
            Path(str(index) + '.lock').unlink(missing_ok=True)

    def find_checkpoint(self, operation_id, expected_base, files):
        _oid(expected_base)
        # Recovery only recognizes the exact current commit with verified parent,
        # trailers AND attributed tree delta; old unrelated history is not scanned.
        head = self.head()
        parents = self.run('show', '-s', '--format=%P', head).strip().split()
        body = self.run('show', '-s', '--format=%B', head)
        if parents != [expected_base] or f'Teseo-Operation: {operation_id}\n' not in body or f'Teseo-Base: {expected_base}\n' not in body:
            return None
        current, old = self._entries(head), self._entries(expected_base)
        changed = {p for p in set(current) | set(old) if current.get(p) != old.get(p)}
        if not changed <= set(files):
            return None
        for path, digest in files.items():
            actual = hashlib.sha256(self._blob(current[path])).hexdigest() if path in current else None
            if actual != digest:
                return None
        return head

    def fetch(self, remote, branch):
        remote = validate_remote(remote, allow_local_remote=self.allow_local_remote)
        branch = _branch(branch)
        self._safe_config()
        ref = 'refs/teseo/fetch/' + str(uuid4())
        self._bytes('fetch', '--no-tags', '--no-recurse-submodules', remote, branch + ':' + ref,
                    file_transport=self.allow_local_remote)
        oid = _oid(self.run('rev-parse', '--verify', ref).strip())
        # Un riferimento per fetch si accumulerebbe senza fine: conservo solo l'ultimo. Gli oggetti restano
        # nel database Git (Git non li elimina prima della sua finestra di grazia).
        for old in self.run('for-each-ref', '--format=%(refname)', 'refs/teseo/fetch/').split():
            if old != ref:
                self._bytes('update-ref', '-d', old, check=False)
        return oid

    def merge_base(self, local, remote):
        result = self._bytes('merge-base', _oid(local), _oid(remote), check=False)
        if result.returncode:
            raise ContractError('git_unrelated_history', 'Cronologie dati estranee: nessuna integrazione automatica')
        return _oid(result.stdout.decode().strip())

    def is_ancestor(self, ancestor, descendant):
        result = self._bytes('merge-base', '--is-ancestor', _oid(ancestor), _oid(descendant), check=False)
        if result.returncode not in (0, 1):
            raise ContractError('git_failed', 'Impossibile verificare ancestry Git')
        return result.returncode == 0

    def _stage(self, oid):
        self.tree(oid)  # Reject scripts, links, binaries and config before checkout.
        base = self.root / '.teseo/local/git-candidates'
        for path in (self.root / '.teseo', self.root / '.teseo/local', base):
            _no_link(path)
            path.mkdir(exist_ok=True)
        ignore = self.root / '.teseo/local/.gitignore'
        _no_link(ignore)
        if not ignore.exists():
            ignore.write_bytes(b'*\n')
        stage = base / str(uuid4())
        stage.mkdir()
        _invoke(stage, ['init', '--quiet'])
        _invoke(stage, ['fetch', '--quiet', '--no-tags', str(self.root), oid], file_transport=True)
        _invoke(stage, ['checkout', '--quiet', '--detach', oid])
        return stage

    def snapshot(self, oid):
        oid = _oid(oid)
        stage = self._stage(oid)
        return {'oid': oid, 'root': str(stage)}

    def integrate(self, local_oid, remote_oid):
        local_oid, remote_oid = _oid(local_oid), _oid(remote_oid)
        self.merge_base(local_oid, remote_oid)
        left, right = self.tree(local_oid), self.tree(remote_oid)
        a, b = parse_manifest(left['.teseo/project.json']), parse_manifest(right['.teseo/project.json'])
        if a != b:
            raise ContractError('git_manifest_conflict', 'Manifest diversi: selezione o identità richiedono revisione')
        stage = self._stage(local_oid)
        _invoke(stage, ['fetch', '--quiet', '--no-tags', str(self.root), remote_oid], file_transport=True)
        if self.is_ancestor(remote_oid, local_oid):
            return {'oid': local_oid, 'root': str(stage)}
        if self.is_ancestor(local_oid, remote_oid):
            _invoke(stage, ['checkout', '--quiet', '--detach', remote_oid])
            oid = remote_oid
        else:
            result = _invoke(stage, ['-c', 'user.name=Teseo', '-c', 'user.email=teseo@localhost',
                                    'merge', '--no-commit', '--no-ff', '--no-edit', remote_oid], check=False)
            if result.returncode:
                raise ContractError('git_conflict', 'Conflitto conservato nel candidato isolato', str(stage))
            tree = _invoke(stage, ['write-tree']).stdout.decode().strip()
            oid = _invoke(stage, ['-c', 'user.name=Teseo', '-c', 'user.email=teseo@localhost',
                                  'commit-tree', tree, '-p', local_oid, '-p', remote_oid],
                          input=b'Teseo: integrazione dati isolata\n').stdout.decode().strip()
            _invoke(stage, ['checkout', '--quiet', '--detach', oid])
        # Import only objects, not a live ref/worktree update.
        self._bytes('fetch', '--quiet', '--no-tags', '--no-write-fetch-head', str(stage), oid, file_transport=True)
        candidate = self.tree(oid)
        for parent in (left, right):
            for path, data in parent.items():
                if path.startswith(('raw/', '.teseo/shared/events/')) and candidate.get(path) != data:
                    raise ContractError('git_immutable_changed', 'Fonte o evento immutabile alterato dal merge', path)
        return {'oid': oid, 'root': str(stage)}

    def push(self, oid, remote, branch):
        remote = validate_remote(remote, allow_local_remote=self.allow_local_remote)
        branch = _branch(branch)
        self._safe_config()
        self.tree(_oid(oid))
        self.audit_history(oid)
        self._bytes('push', '--porcelain', '--no-verify', remote, oid + ':refs/heads/' + branch,
                    file_transport=self.allow_local_remote)

    def audit_history(self, oid):
        """Bounded reachable-history scan before sending *any* objects.

        Deleting a private file from HEAD does not delete its historic bytes.
        Never rewrite history: require an explicitly reviewed clean data repo
        when historic policy or these conservative audit limits block a push.
        """
        commits = self.run('rev-list', '--max-count=129', _oid(oid)).splitlines()
        if len(commits) > 128:
            raise ContractError('git_history_limit', 'Oltre 128 commit raggiungibili: revisione manuale della storia richiesta')
        blobs, total = set(), 0
        vault_id = None
        try:
            for commit in commits:
                entries = self._entries(commit)
                if '.teseo/project.json' not in entries:
                    raise ContractError('git_history_policy', 'Storia priva del manifest dati: revisione esplicita richiesta')
                manifest = parse_manifest(self._blob(entries['.teseo/project.json']))
                if vault_id is None:
                    vault_id = manifest['vault_id']
                if manifest['vault_id'] != vault_id:
                    raise ContractError('git_history_policy', 'Identità vault cambiata nella storia Git')
                for path, object_id in entries.items():
                    data = self._blob(object_id)
                    if object_id not in blobs:
                        total += len(data)
                        blobs.add(object_id)
                    if total > MAX_TREE:
                        raise ContractError('git_history_limit', 'Blob storici unici oltre 64 MiB: revisione manuale richiesta')
                    if not self._allowed(path, manifest, data):
                        raise ContractError('git_history_policy', 'Storia con file o contenuti vietati; nessun push eseguito', path)
        except ContractError as error:
            if error.code in ('git_history_limit', 'git_history_policy'):
                raise
            raise ContractError('git_history_policy', 'Storia non conforme alla policy dati; nessun push eseguito', error.path) from error
        return {'history_audited': True, 'commits': len(commits), 'unique_blobs': len(blobs), 'bytes': total}

    def _candidate_root(self, path):
        base = self.root / '.teseo/local/git-candidates'
        _no_link(base)
        target = Path(path)
        _no_link(target)
        target = target.resolve(strict=True)
        if target.parent != base.resolve(strict=True):
            raise ContractError('git_candidate_path', 'Candidato non appartenente allo staging')
        try:
            if str(UUID(target.name)) != target.name:
                raise ValueError()
        except (ValueError, AttributeError) as error:
            raise ContractError('git_candidate_path', 'Identità candidato non valida') from error
        return target

    def resolve_candidate(self, candidate_path, local_oid, remote_oid, expected_digest):
        """Commit a reviewed isolated tree, never edits from an arbitrary upload.

        This proves Git/policy integrity only. The caller must validate note/event
        structure and semantic reconciliation before publication.
        """
        local_oid, remote_oid = _oid(local_oid), _oid(remote_oid)
        if not isinstance(expected_digest, str) or not re.fullmatch('[0-9a-f]{64}', expected_digest):
            raise ContractError('git_candidate_changed', 'Digest candidato richiesto')
        stage = self._candidate_root(candidate_path)
        staging = GitRepository(stage, allow_local_remote=True)
        if staging.head() != local_oid:
            raise ContractError('git_candidate_changed', 'HEAD del candidato non corrisponde al checkpoint locale')
        merge_head = stage / '.git/MERGE_HEAD'
        _no_link(merge_head)
        if not merge_head.is_file() or merge_head.read_text(encoding='ascii').strip() != remote_oid:
            raise ContractError('git_candidate_changed', 'Il candidato non appartiene all’integrazione richiesta')
        candidate = capture_snapshot(stage)
        if candidate.digest != expected_digest:
            raise ContractError('git_candidate_changed', 'Il candidato è cambiato dopo la revisione')
        before = [self.tree(local_oid), self.tree(remote_oid)]
        data = {entry.path: entry.data for entry in candidate.files}
        manifest = parse_manifest(data['.teseo/project.json'])
        for parent in before:
            if parse_manifest(parent['.teseo/project.json']) != manifest:
                raise ContractError('git_manifest_conflict', 'Manifest del candidato diverso dai parent')
            for path, content in parent.items():
                if path.startswith(('raw/', '.teseo/shared/events/')) and data.get(path) != content:
                    raise ContractError('git_immutable_changed', 'Fonte o evento immutabile alterato nella risoluzione', path)
        for path, content in data.items():
            if not self._allowed(path, manifest, content):
                raise ContractError('git_tracked_policy', 'File fuori policy nel candidato', path)
            if path.endswith('.md') and any(line.startswith((b'<<<<<<<', b'=======', b'>>>>>>>')) for line in content.splitlines()):
                raise ContractError('git_conflict', 'Marker di conflitto ancora presenti nel candidato', path)
        # Files outside the snapshot must not be smuggled into the resolved tree;
        # they are rejected rather than silently treated as part of the review.
        preview = staging._preview_files([p for p in data if p.startswith('raw/')])
        if preview['excluded']:
            raise ContractError('git_tracked_policy', 'File aggiuntivi non dati nel candidato')
        index = self.root / '.teseo/local' / ('git-index-' + str(uuid4()))
        env = {'GIT_INDEX_FILE': str(index)}
        try:
            staging._bytes('read-tree', '--empty', env=env)
            updates = []
            for path, content in sorted(data.items()):
                oid = staging._bytes('hash-object', '-w', '--no-filters', '--stdin', input=content).stdout.decode().strip()
                updates.append(('100644 ' + oid + '\t' + path + '\x00').encode('utf-8'))
            staging._bytes('update-index', '-z', '--index-info', input=b''.join(updates), env=env)
            tree = staging._bytes('write-tree', env=env).stdout.decode().strip()
            candidate.assert_unchanged(stage)
            oid = staging.run('-c', 'user.name=Teseo', '-c', 'user.email=teseo@localhost',
                              'commit-tree', tree, '-p', local_oid, '-p', remote_oid,
                              input='Teseo: risoluzione dati revisionata\n').strip()
            self._bytes('fetch', '--quiet', '--no-tags', '--no-write-fetch-head', str(stage), oid, file_transport=True)
            self.tree(oid)
            return {'oid': oid, 'root': str(stage)}
        finally:
            index.unlink(missing_ok=True)
            Path(str(index) + '.lock').unlink(missing_ok=True)

    def adopt(self, expected_local, candidate):
        _oid(expected_local)
        oid = _oid(candidate['oid'])
        self._safe_config()
        if self.head() != expected_local or not self.clean():
            raise ContractError('git_adoption_blocked', 'Pubblicato; adozione locale sospesa per modifiche esterne')
        if not self.is_ancestor(expected_local, oid):
            raise ContractError('git_adoption_blocked', 'Il candidato non è fast-forward del checkpoint locale')
        self.tree(oid)
        self.run('merge', '--ff-only', '--no-edit', oid)
        if self.head() != oid or not self.clean():
            raise ContractError('git_adoption_blocked', 'Verifica finale non convergente; candidato conservato')

    def resume_adoption(self, expected_local: str, candidate: dict) -> bool:
        """Completa un fast-forward interrotto; False se c'è qualunque modifica non attribuibile ad esso.

        Git rifiuta di ripetere il merge su file già portati al contenuto del candidato. Qui ogni file
        della differenza L->C deve contenere esattamente la versione L o la versione C: altrimenti è
        una modifica esterna e non si scrive nulla.
        """
        _oid(expected_local)
        oid = _oid(candidate['oid'])
        self._safe_config()
        if self.head() != expected_local or not self.is_ancestor(expected_local, oid):
            return False
        self.tree(oid)
        old, new = self._entries(expected_local), self._entries(oid)
        delta = {p for p in set(old) | set(new) if old.get(p) != new.get(p)}
        try:
            dirty = self._changes()
        except ContractError:
            return False
        if not dirty or not dirty <= delta:
            return False
        versions = {}
        for path in delta:
            target = resolve_path(self.root, path)
            _no_link(target)
            actual = target.read_bytes() if target.is_file() else None
            if target.exists() and not target.is_file():
                return False
            allowed = [self._blob(entry) if entry else None for entry in (old.get(path), new.get(path))]
            if actual not in allowed:
                return False
            versions[path] = allowed[1]
        for path, data in versions.items():
            target = resolve_path(self.root, path)
            if data is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Atomico: un secondo crash non deve lasciare un file né L né C, che bloccherebbe ogni resume.
                temporary = target.with_name('.' + target.name + '.' + uuid4().hex[:8] + '.tmp')
                temporary.write_bytes(data)
                os.replace(temporary, target)
        self.run('update-ref', 'refs/heads/' + self.inspect()['branch'], oid, expected_local)
        self.run('read-tree', oid)
        return self.head() == oid and self.clean()

    def cleanup_candidate(self, candidate):
        target = self._candidate_root(candidate['root'])
        shutil.rmtree(target)


def preview_data_repository(root, selection=None):
    """Read-only onboarding preview, including a vault not yet under Git."""
    root = Path(root).resolve(strict=True)
    # Reuse exactly the initialized-repository policy without fabricating .git.
    reader = object.__new__(GitRepository)
    reader.root = root
    return reader._preview_files(selection)


_INIT_PENDING = 'teseo-init-pending'


def _remove_tree(folder: Path) -> None:
    def writable(function, path, error):
        if not isinstance(error[1], PermissionError):
            raise error[1]
        os.chmod(path, 0o600)
        function(path)
    shutil.rmtree(folder, onerror=writable)


def _discard_interrupted_init(root: Path) -> None:
    """Rimuove solo una .git creata da una inizializzazione Teseo interrotta prima del commit iniziale."""
    git = root / '.git'
    _no_link(git)
    marker = git / _INIT_PENDING
    empty = git.is_dir() and not any(git.iterdir())  # crash fra mkdir e marker: nessun dato da conservare
    if not empty and (not marker.is_file() or any(f.is_file() for f in (git / 'refs/heads').rglob('*'))):
        return
    packed = git / 'packed-refs'
    if packed.exists() and any(line and not line.startswith(('#', '^')) for line in packed.read_text(encoding='utf-8').splitlines()):
        return
    _remove_tree(git)


def initialize_data_repository(root, branch, remote_url, selection, *, author,
                               share_confirmed, expected_files=None):
    """Initialize an explicitly approved data selection; never create/push a remote.

    Excluded existing files remain visible as untracked changes: initialization
    does not hide private files with blanket ignores or certify a clean tree.
    On failure any created Git checkpoint is retained for explicit recovery.
    """
    root = Path(root).resolve(strict=True)
    branch, remote_url = _branch(branch), validate_remote(remote_url)
    if share_confirmed is not True:
        raise ContractError('git_share_confirmation', 'Confermare esplicitamente i dati da pubblicare')
    if (not isinstance(author, dict) or set(author) != {'name', 'email'}
            or any(not isinstance(v, str) or not v or len(v) > 256 or any(ord(c) < 32 for c in v)
                   for v in author.values()) or '@' not in author['email']):
        raise ContractError('git_author_required', 'Nome ed email autore Git richiesti')
    preview = preview_data_repository(root, selection)
    hashes = {f['path']: f['sha256'] for f in preview['files']}
    if expected_files is None or hashes != expected_files:
        raise ContractError('git_preview_changed', 'Confermare gli hash della preview attuale prima di inizializzare Git')
    # A parent kit/data repository must never be implicitly adopted or nested.
    if (root / '.git').exists():
        _discard_interrupted_init(root)
    if (root / '.git').exists():
        raise ContractError('git_repository_exists', 'La cartella appartiene già a un repository Git')
    (root / '.git').mkdir(exist_ok=False)
    (root / '.git' / _INIT_PENDING).write_bytes(b'')
    try:
        return _initialize(root, branch, remote_url, selection, author, hashes, preview)
    except BaseException:
        # Prima del commit iniziale non c'è nulla da conservare: il retry deve poter ripartire.
        try:
            _discard_interrupted_init(root)
        except Exception:
            pass  # l'errore originale è più utile del fallimento della pulizia
        raise


def _initialize(root, branch, remote_url, selection, author, hashes, preview):
    _invoke(root, ['init', '--quiet', '-b', branch])
    for field, value in author.items():
        _invoke(root, ['config', '--local', 'user.' + field, value])
    _invoke(root, ['remote', 'add', 'origin', remote_url])
    updates = []
    for path, digest in sorted(hashes.items()):
        target = resolve_path(root, path)
        _no_link(target)
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ContractError('git_preview_changed', 'File cambiato dopo la preview', path)
        oid = _invoke(root, ['hash-object', '-w', '--no-filters', '--stdin'], input=data).stdout.decode().strip()
        updates.append(('100644 ' + oid + '\t' + path + '\x00').encode('utf-8'))
    _invoke(root, ['update-index', '-z', '--index-info'], input=b''.join(updates))
    tree = _invoke(root, ['write-tree']).stdout.decode().strip()
    if hashes != {f['path']: f['sha256'] for f in preview_data_repository(root, selection)['files']}:
        raise ContractError('git_preview_changed', 'Preview cambiata prima del commit iniziale')
    oid = _invoke(root, ['commit-tree', tree], input=b'Teseo: selezione dati iniziale approvata\n').stdout.decode().strip()
    _invoke(root, ['update-ref', 'refs/heads/' + branch, oid, '0' * len(oid)])
    (root / '.git' / _INIT_PENDING).unlink(missing_ok=True)
    repo = GitRepository(root)
    repo.tree(oid)
    return {'head': oid, 'branch': branch, 'remote_url': remote_url,
            'clean': repo.clean(), 'files': preview['files'], 'excluded': preview['excluded'],
            'published': False}

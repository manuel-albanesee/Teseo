"""ECC TDD: publication primitives exercise real temporary Git repositories."""
import _shortpath  # noqa: F401
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4
from unittest import mock

from kit.dashboard.contracts import ContractError, DEFAULT_SHARED_PATHS, canonical_json
from kit.dashboard.storage import capture_snapshot
from kit.dashboard.git_sync import (GitRepository, validate_remote, initialize_data_repository,
                                    preview_data_repository, github_repository_url, read_local_excludes,
                                    write_local_excludes,
                                    _invoke, _oid, _branch)


NL = chr(10)


def _remove_fixture(folder):
    """Bound retries, including Git's read-only objects, without tempfile recursion."""
    folder = Path(folder).resolve()
    if folder.parent != Path.cwd().resolve() or not folder.name.startswith('teseo-git-'):
        raise ValueError('Unexpected Git fixture cleanup path')

    def read_only(function, path, error):
        failure = error[1]
        if not isinstance(failure, PermissionError) or os.stat(path).st_mode & stat.S_IWRITE:
            raise failure
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        function(path)

    for attempt in range(21):
        if not folder.exists():
            return
        try:
            shutil.rmtree(folder, onerror=read_only)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(.25)


class GitFixtureCleanup(unittest.TestCase):
    def test_transient_scanner_lock_is_retried_without_hiding_failure(self):
        with tempfile.TemporaryDirectory(prefix='teseo-git-', dir=Path.cwd()) as folder:
            with mock.patch('shutil.rmtree', side_effect=[PermissionError('scanner lock'), None]) as remove, \
                 mock.patch('time.sleep') as sleep:
                _remove_fixture(folder)
            self.assertEqual(remove.call_count, 2)
            sleep.assert_called_once_with(.25)

    def test_permanent_lock_stops_after_bounded_retries_and_preserves_fixture(self):
        with tempfile.TemporaryDirectory(prefix='teseo-git-', dir=Path.cwd()) as folder:
            failure = PermissionError('persistent lock')
            with mock.patch('shutil.rmtree', side_effect=failure) as remove, mock.patch('time.sleep') as sleep:
                with self.assertRaises(PermissionError) as raised:
                    _remove_fixture(folder)
            self.assertIs(raised.exception, failure)
            self.assertEqual(remove.call_count, 21)
            self.assertEqual(sleep.call_count, 20)
            self.assertTrue(Path(folder).exists())


class GitPolicy(unittest.TestCase):
    def test_history_audit_limits_and_missing_manifest_require_explicit_review(self):
        repo = object.__new__(GitRepository)
        repo.run = mock.Mock(return_value=('a' * 40 + '\n') * 129)
        with self.assertRaises(ContractError) as raised:
            repo.audit_history('a' * 40)
        self.assertEqual(raised.exception.code, 'git_history_limit')
        repo.run.return_value = 'a' * 40 + '\n'
        repo._entries = mock.Mock(return_value={'wiki/A.md': '2' * 40})
        with self.assertRaises(ContractError) as raised:
            repo.audit_history('a' * 40)
        self.assertEqual(raised.exception.code, 'git_history_policy')
        manifest = canonical_json(dict(format_version=1, schema_version=1, event_version=1,
                                       minimum_kit_version='1.0.0', vault_id=str(uuid4()),
                                       shared_paths=list(DEFAULT_SHARED_PATHS)))
        repo._entries.return_value = {'.teseo/project.json': '1' * 40, 'wiki/A.md': '2' * 40}
        repo._blob = lambda oid: manifest if oid == '1' * 40 else b'x' * 100
        with mock.patch('kit.dashboard.git_sync.MAX_TREE', len(manifest) + 10):
            with self.assertRaises(ContractError) as raised:
                repo.audit_history('a' * 40)
            self.assertEqual(raised.exception.code, 'git_history_limit')

    def test_repository_http_tls_and_proxy_overrides_are_blocked(self):
        with tempfile.TemporaryDirectory(prefix='teseo-git-policy-', dir=Path.cwd()) as folder:
            repo = object.__new__(GitRepository)
            repo.root = Path(folder)
            for setting in ('http.sslverify\nfalse\x00', 'http.proxy\nhttp://proxy.invalid\x00',
                            'https.proxy\nhttp://proxy.invalid\x00', 'core.askpass\nevil.exe\x00',
                            'core.editor\nevil.exe\x00', 'diff.x.textconv\nevil.exe\x00',
                            'gpg.program\nevil.exe\x00', 'alias.st\n!evil\x00'):
                repo.run = mock.Mock(return_value=setting)
                with self.subTest(setting=setting.split('\n')[0]):
                    with self.assertRaises(ContractError) as raised:
                        repo._safe_config()
                    self.assertEqual(raised.exception.code, 'git_unsafe_config')

    def test_high_confidence_secrets_are_rejected_even_inside_markdown(self):
        manifest = {'shared_paths': list(DEFAULT_SHARED_PATHS)}
        for secret in (b'-----BEGIN OPENSSH PRIVATE KEY-----', b'ghp_' + b'a' * 30,
                       b'github_pat_' + b'a' * 40, b'sk-proj-' + b'a' * 30):
            with self.subTest(prefix=secret[:10]):
                self.assertFalse(GitRepository._allowed('wiki/secret.md', manifest, b'# Note\n' + secret + b'\n'))
        self.assertTrue(GitRepository._allowed('wiki/safe.md', manifest, b'# Public reference\n'))

    def test_common_cloud_and_provider_tokens_are_rejected_without_flagging_ordinary_text(self):
        manifest = {'shared_paths': list(DEFAULT_SHARED_PATHS)}
        for secret in (b'AKIA' + b'ABCDEFGHIJKLMNOP', b'ASIA' + b'ABCDEFGHIJKLMNOP', b'sk-ant-' + b'a' * 30,
                       b'xoxb-' + b'1234567890-abcdef', b'AIza' + b'A' * 35,
                       b'eyJ' + b'a' * 12 + b'.' + b'b' * 12 + b'.' + b'c' * 12):
            with self.subTest(prefix=secret[:6]):
                self.assertFalse(GitRepository._allowed('wiki/secret.md', manifest, b'# Note\n' + secret + b'\n'))
        for text in (b'# Mappa\nAKIA e ASIA sono prefissi.\n', b'# Sigle\nxox, sk-ant e AIza nominati.\n',
                     b'# Token\neyJ non basta senza due punti.\n'):
            with self.subTest(text=text[:12]):
                self.assertTrue(GitRepository._allowed('wiki/safe.md', manifest, text))

    def test_transport_errors_are_classified_without_leaking_output(self):
        for stderr, code in ((b'Authentication failed secret', 'git_auth'),
                             (b'Permission denied secret', 'git_auth'),
                             (b'Could not resolve secret', 'git_network'),
                             (b'non-fast-forward secret', 'git_push_rejected'),
                             (b'protected branch secret', 'git_policy'),
                             (b'unknown secret', 'git_failed')):
            result = subprocess.CompletedProcess([], 1, b'', stderr)
            with self.subTest(code=code), mock.patch('kit.dashboard.git_sync.subprocess.run', return_value=result):
                with self.assertRaises(ContractError) as raised:
                    _invoke(Path.cwd(), ['status'])
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn('secret', str(raised.exception))
        for error, code in ((subprocess.TimeoutExpired('git', 60), 'git_timeout'),
                            (OSError('secret'), 'git_unavailable')):
            with mock.patch('kit.dashboard.git_sync.subprocess.run', side_effect=error):
                with self.assertRaises(ContractError) as raised:
                    _invoke(Path.cwd(), ['status'])
                self.assertEqual(raised.exception.code, code)
        result = subprocess.CompletedProcess([], 0, b'1234', b'')
        with mock.patch('kit.dashboard.git_sync.MAX_TREE', 3), mock.patch('kit.dashboard.git_sync.subprocess.run', return_value=result):
            with self.assertRaises(ContractError) as raised:
                _invoke(Path.cwd(), ['status'])
            self.assertEqual(raised.exception.code, 'git_output_limit')

    def test_runner_uses_absolute_binary_shell_false_and_drops_inherited_git_environment(self):
        result = subprocess.CompletedProcess([], 0, b'', b'')
        with mock.patch.dict('os.environ', {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'filter.bad.clean',
                                          'GIT_CONFIG_VALUE_0': 'bad', 'GIT_SSH_COMMAND': 'bad'}), \
             mock.patch('kit.dashboard.git_sync.subprocess.run', return_value=result) as run:
            _invoke(Path.cwd(), ['status'])
        args, kwargs = run.call_args
        self.assertTrue(Path(args[0][0]).is_absolute())
        self.assertFalse(kwargs['shell'])
        self.assertNotIn('GIT_CONFIG_COUNT', kwargs['env'])
        self.assertNotEqual(kwargs['env']['GIT_SSH_COMMAND'], 'bad')
        self.assertEqual(kwargs['env']['GIT_NO_REPLACE_OBJECTS'], '1')

    def test_oid_branch_and_compare_url_validation(self):
        for value in ('HEAD', '--x', 'a' * 39, None):
            with self.assertRaises(ContractError):
                _oid(value)
        for value in ('--x', '../x', 'a//b', 'a.lock', 'a/', '', None):
            with self.assertRaises(ContractError):
                _branch(value)
        self.assertEqual(github_repository_url('git@github.com:owner/repo.git'), 'https://github.com/owner/repo')
        self.assertEqual(github_repository_url('ssh://git@github.com/owner/repo.git'), 'https://github.com/owner/repo')
        self.assertIsNone(github_repository_url('/local/fixture'))
        with self.assertRaises(ContractError):
            validate_remote(None)


class GitSync(unittest.TestCase):
    def setUp(self):
        self.fixture = Path(tempfile.mkdtemp(prefix='teseo-git-', dir=Path.cwd()))
        self.addCleanup(self.cleanup_fixture)
        self.root = self.fixture / 'vault'
        self.root.mkdir()
        self.git('init', '-b', 'shared')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / '.teseo').mkdir()
        (self.root / 'wiki').mkdir()
        (self.root / 'raw').mkdir()
        self.manifest = dict(format_version=1, schema_version=1, event_version=1,
                             minimum_kit_version='1.0.0', vault_id=str(uuid4()),
                             shared_paths=list(DEFAULT_SHARED_PATHS))
        (self.root / '.teseo/project.json').write_bytes(canonical_json(self.manifest))
        (self.root / 'Wiki reference.md').write_text('# Schema\n', encoding='utf-8')
        (self.root / 'wiki/A.md').write_text('# A\n', encoding='utf-8')
        (self.root / 'raw/source.txt').write_text('source\n', encoding='utf-8')
        self.git('add', '--', '.teseo/project.json', 'Wiki reference.md', 'wiki/A.md', 'raw/source.txt')
        self.git('commit', '-m', 'base')
        self.repo = GitRepository(self.root, allow_local_remote=True)

    def cleanup_fixture(self):
        _remove_fixture(self.fixture)

    def git(self, *args, cwd=None):
        result = subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd or self.root,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return result.stdout.decode('utf-8').strip()

    def hashes(self, *paths):
        return {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in paths}

    def test_preview_excludes_private_and_raw_binary_and_requires_selection(self):
        (self.root / '.graph').mkdir()
        (self.root / '.graph/domande.sqlite').write_bytes(b'private')
        (self.root / 'raw/image.png').write_bytes(b'\x89PNG\0')
        preview = self.repo.preview()
        self.assertNotIn('raw/source.txt', [f['path'] for f in preview['files']])
        selected = self.repo.preview(['raw/source.txt'])
        self.assertIn('raw/source.txt', [f['path'] for f in selected['files']])
        self.assertIn('.graph/domande.sqlite', selected['excluded'])
        self.assertIn('raw/image.png', selected['excluded'])

    def test_checkpoint_exact_files_operation_recovery_and_noop(self):
        base = self.repo.head()
        (self.root / 'wiki/A.md').write_text('# A\nchanged\n', encoding='utf-8')
        operation = str(uuid4())
        files = self.hashes('wiki/A.md')
        oid = self.repo.checkpoint(operation, base, files)
        self.assertNotEqual(oid, base)
        self.assertEqual(self.repo.find_checkpoint(operation, base, files), oid)
        self.assertTrue(self.repo.clean())
        self.assertEqual(self.repo.checkpoint(str(uuid4()), oid, files), oid)

    def test_checkpoint_crash_between_update_ref_and_read_tree_is_recovered_by_retry(self):
        base = self.repo.head()
        (self.root / 'wiki/A.md').write_text('# A\nchanged\n', encoding='utf-8')
        operation = str(uuid4())
        files = self.hashes('wiki/A.md')
        real_run = self.repo.run
        def crash_after_ref(*args, **kwargs):
            if args and args[0] == 'read-tree' and len(args) == 2:
                raise OSError('simulated crash')
            return real_run(*args, **kwargs)
        with mock.patch.object(self.repo, 'run', side_effect=crash_after_ref):
            with self.assertRaises(OSError):
                self.repo.checkpoint(operation, base, files)
        crashed = self.repo.head()
        self.assertNotEqual(crashed, base)
        self.assertFalse(self.repo.clean())
        self.assertEqual(self.repo.checkpoint(operation, base, files), crashed)
        self.assertTrue(self.repo.clean())
        self.assertEqual((self.root / 'wiki/A.md').read_text(encoding='utf-8'), '# A\nchanged\n')

    def _partial_adoption_fixture(self):
        base = self.repo.head()
        path = self.root / 'wiki/A.md'
        path.write_text('# A' + NL + 'changed' + NL, encoding='utf-8')
        candidate = self.repo.checkpoint(str(uuid4()), base, self.hashes('wiki/A.md'))
        self.repo.run('reset', '--hard', base)
        path.write_text('# A' + NL + 'changed' + NL, encoding='utf-8')  # il merge interrotto aveva già scritto C
        self.assertFalse(self.repo.clean())
        return base, candidate, path

    def test_interrupted_fast_forward_adoption_is_completed_without_external_edits(self):
        base, candidate, _ = self._partial_adoption_fixture()
        self.assertTrue(self.repo.resume_adoption(base, {'oid': candidate}))
        self.assertEqual(self.repo.head(), candidate)
        self.assertTrue(self.repo.clean())

    def test_interrupted_adoption_with_foreign_bytes_is_refused_and_preserved(self):
        base, candidate, path = self._partial_adoption_fixture()
        path.write_text('# A' + NL + 'foreign edit' + NL, encoding='utf-8')
        self.assertFalse(self.repo.resume_adoption(base, {'oid': candidate}))
        self.assertEqual(self.repo.head(), base)
        self.assertEqual(path.read_text(encoding='utf-8'), '# A' + NL + 'foreign edit' + NL)

    def test_checkpoint_foreign_file_staged_file_and_hash_drift_blocked(self):
        base = self.repo.head()
        (self.root / 'wiki/A.md').write_text('changed\n', encoding='utf-8')
        (self.root / 'foreign.txt').write_text('foreign\n', encoding='utf-8')
        with self.assertRaises(ContractError):
            self.repo.checkpoint(str(uuid4()), base, self.hashes('wiki/A.md'))
        (self.root / 'foreign.txt').unlink()
        self.git('add', '--', 'wiki/A.md')
        with self.assertRaises(ContractError):
            self.repo.checkpoint(str(uuid4()), base, self.hashes('wiki/A.md'))
        self.git('reset', '--', 'wiki/A.md')
        with self.assertRaises(ContractError):
            self.repo.checkpoint(str(uuid4()), base, {'wiki/A.md': '0' * 64})
        self.assertEqual(self.repo.head(), base)

    def test_tracked_private_and_mutated_raw_blocked(self):
        (self.root / '.graph').mkdir()
        (self.root / '.graph/domande.sqlite').write_bytes(b'private')
        self.git('add', '--', '.graph/domande.sqlite')
        self.git('commit', '-m', 'private fixture')
        self.assertIn('.graph/domande.sqlite', self.repo.inspect()['tracked_violations'])
        with self.assertRaises(ContractError):
            self.repo.checkpoint(str(uuid4()), self.repo.head(), {})
        self.git('rm', '--', '.graph/domande.sqlite')
        self.git('commit', '-m', 'remove fixture')
        (self.root / 'raw/source.txt').write_text('changed source\n', encoding='utf-8')
        with self.assertRaises(ContractError):
            self.repo.checkpoint(str(uuid4()), self.repo.head(), self.hashes('raw/source.txt'))

    def test_deleted_private_history_is_not_pushed(self):
        (self.root / '.graph').mkdir()
        (self.root / '.graph/domande.sqlite').write_bytes(b'private history')
        self.git('add', '--', '.graph/domande.sqlite')
        self.git('commit', '-m', 'past private data')
        self.git('rm', '--', '.graph/domande.sqlite')
        self.git('commit', '-m', 'removed from current tree')
        self.assertFalse(self.repo.inspect()['tracked_violations'])
        bare = self.fixture / 'remote.git'
        self.git('init', '--bare', str(bare), cwd=self.fixture)
        with self.assertRaises(ContractError) as raised:
            self.repo.push(self.repo.head(), str(bare), 'shared')
        self.assertEqual(raised.exception.code, 'git_history_policy')
        self.assertEqual(self.git('for-each-ref', '--format=%(refname)', cwd=bare), '')

    def test_remote_option_injection_credentials_and_transport_policy(self):
        for value in ('--upload-pack=evil', 'https://user:secret@github.com/a/b.git',
                      'https://evil.invalid/a/b', 'ext::anything', '/tmp/remote',
                      'git@github.com:a/../b.git'):
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate_remote(value)
        self.assertEqual(validate_remote('https://github.com/a/b.git'), 'https://github.com/a/b.git')
        self.assertEqual(validate_remote('git@github.com:a/b.git'), 'git@github.com:a/b.git')

    def test_filters_and_hooks_are_not_executed(self):
        marker = self.root / 'executed'
        hook = self.root / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\necho bad > executed\n', encoding='utf-8')
        hook.chmod(0o755)
        (self.root / 'wiki/A.md').write_text('safe\n', encoding='utf-8')
        self.repo.checkpoint(str(uuid4()), self.repo.head(), self.hashes('wiki/A.md'))
        self.assertFalse(marker.exists())
        self.git('config', 'filter.attack.clean', 'echo unsafe')
        with self.assertRaises(ContractError):
            self.repo.inspect()

    def test_only_vetted_global_credential_helper_and_author_are_inherited(self):
        home = self.fixture / 'home'
        home.mkdir()
        (home / '.gitconfig').write_text('[user]\n name = Global User\n email = global@example.invalid\n'
                                       '[credential]\n helper = manager\n', encoding='utf-8')
        self.git('config', '--unset', 'user.name')
        self.git('config', '--unset', 'user.email')
        with mock.patch('kit.dashboard.git_sync.Path.home', return_value=home):
            repo = GitRepository(self.root, allow_local_remote=True)
        self.assertEqual(repo.inspect()['author']['name'], 'Global User')
        self.assertEqual(repo.credential_helper, 'manager')
        (home / '.gitconfig').write_text('[credential]\n helper = !echo unsafe\n', encoding='utf-8')
        with mock.patch('kit.dashboard.git_sync.Path.home', return_value=home):
            repo = GitRepository(self.root, allow_local_remote=True)
        self.assertIsNone(repo.credential_helper)

    def test_initialization_is_explicit_and_only_previewed_data_is_committed(self):
        target = self.fixture / 'fresh'
        target.mkdir()
        (target / '.teseo').mkdir()
        (target / '.teseo/project.json').write_bytes(canonical_json(self.manifest))
        (target / 'wiki').mkdir()
        (target / 'wiki/A.md').write_text('A\n', encoding='utf-8')
        (target / 'raw').mkdir()
        (target / 'raw/source.txt').write_text('source\n', encoding='utf-8')
        (target / 'private.sqlite').write_bytes(b'private')
        author = {'name': 'User', 'email': 'user@example.invalid'}
        preview = preview_data_repository(target, ['raw/source.txt'])
        self.assertFalse((target / '.git').exists())
        with self.assertRaises(ContractError):
            initialize_data_repository(target, 'shared', 'https://github.com/a/b.git', ['raw/source.txt'],
                                       author=author, share_confirmed=False)
        self.assertFalse((target / '.git').exists())
        result = initialize_data_repository(target, 'shared', 'https://github.com/a/b.git', ['raw/source.txt'],
                                            author=author, share_confirmed=True,
                                            expected_files={f['path']: f['sha256'] for f in preview['files']})
        repo = GitRepository(target)
        self.assertEqual(result['head'], repo.head())
        self.assertNotIn('private.sqlite', repo.tree(repo.head()))
        self.assertIn('raw/source.txt', repo.tree(repo.head()))
        self.assertTrue((target / 'private.sqlite').exists())
        self.assertFalse(repo.clean())  # Existing excluded content is not silently hidden.

    def test_interrupted_initialization_is_discarded_and_retry_succeeds(self):
        target = self.fixture / 'interrupted'
        target.mkdir()
        (target / '.teseo').mkdir()
        (target / '.teseo/project.json').write_bytes(canonical_json(self.manifest))
        (target / 'raw').mkdir()
        (target / 'raw/source.txt').write_text('source\n', encoding='utf-8')
        author = {'name': 'User', 'email': 'user@example.invalid'}
        expected = {f['path']: f['sha256'] for f in preview_data_repository(target, ['raw/source.txt'])['files']}
        arguments = (target, 'shared', 'https://github.com/a/b.git', ['raw/source.txt'])
        options = dict(author=author, share_confirmed=True, expected_files=expected)
        with mock.patch('kit.dashboard.git_sync._invoke', side_effect=ContractError('git_failed', 'injected')):
            with self.assertRaises(ContractError):
                initialize_data_repository(*arguments, **options)
        self.assertFalse((target / '.git').exists())
        # Crash del processo: nessuna eccezione gestita, .git parziale con marker.
        (target / '.git').mkdir()
        (target / '.git' / 'teseo-init-pending').write_bytes(b'')
        result = initialize_data_repository(*arguments, **options)
        self.assertEqual(result['head'], GitRepository(target).head())
        self.assertFalse((target / '.git/teseo-init-pending').exists())
        with self.assertRaises(ContractError) as raised:
            initialize_data_repository(*arguments, **options)
        self.assertEqual(raised.exception.code, 'git_repository_exists')

    def test_isolated_merge_push_and_fast_forward_adoption(self):
        base = self.repo.head()
        (self.root / 'wiki/A.md').write_text('local\n', encoding='utf-8')
        local = self.repo.checkpoint(str(uuid4()), base, self.hashes('wiki/A.md'))
        other = self.fixture / 'other'
        self.git('clone', str(self.root), str(other), cwd=self.fixture)
        self.git('config', 'user.name', 'Other', cwd=other)
        self.git('config', 'user.email', 'other@example.invalid', cwd=other)
        self.git('checkout', '--detach', base, cwd=other)
        (other / 'wiki/B.md').write_text('remote\n', encoding='utf-8')
        self.git('add', '--', 'wiki/B.md', cwd=other)
        self.git('commit', '-m', 'remote', cwd=other)
        remote = self.git('rev-parse', 'HEAD', cwd=other)
        self.repo.fetch(str(other), 'HEAD')
        candidate = self.repo.integrate(local, remote)
        self.assertEqual(self.repo.head(), local)
        self.assertFalse((self.root / 'wiki/B.md').exists())
        self.assertTrue((Path(candidate['root']) / 'wiki/B.md').is_file())
        self.assertTrue(self.repo.is_ancestor(local, candidate['oid']))
        self.assertTrue(self.repo.is_ancestor(remote, candidate['oid']))
        bare = self.fixture / 'remote.git'
        self.git('init', '--bare', str(bare), cwd=self.fixture)
        self.repo.push(candidate['oid'], str(bare), 'shared')
        self.repo.adopt(local, candidate)
        self.assertEqual(self.repo.head(), candidate['oid'])
        self.assertTrue(self.repo.clean())
        (self.root / 'wiki/A.md').write_text('external editor\n', encoding='utf-8')
        with self.assertRaises(ContractError) as raised:
            self.repo.adopt(candidate['oid'], candidate)
        self.assertEqual(raised.exception.code, 'git_adoption_blocked')
        self.assertEqual((self.root / 'wiki/A.md').read_text(), 'external editor\n')

    def test_remote_raw_mutation_and_non_fast_forward_push_are_preserved(self):
        base = self.repo.head()
        other = self.fixture / 'other'
        self.git('clone', str(self.root), str(other), cwd=self.fixture)
        self.git('config', 'user.name', 'Other', cwd=other)
        self.git('config', 'user.email', 'other@example.invalid', cwd=other)
        (other / 'raw/source.txt').write_text('remote raw mutation\n', encoding='utf-8')
        self.git('add', '--', 'raw/source.txt', cwd=other)
        self.git('commit', '-m', 'bad raw change', cwd=other)
        remote = self.repo.fetch(str(other), 'HEAD')
        with self.assertRaises(ContractError) as raised:
            self.repo.integrate(base, remote)
        self.assertEqual(raised.exception.code, 'git_immutable_changed')
        self.assertEqual(self.repo.head(), base)
        bare = self.fixture / 'remote.git'
        self.git('init', '--bare', str(bare), cwd=self.fixture)
        self.git('push', str(bare), 'HEAD:refs/heads/shared', cwd=other)
        (self.root / 'wiki/A.md').write_text('local\n', encoding='utf-8')
        local = self.repo.checkpoint(str(uuid4()), base, self.hashes('wiki/A.md'))
        with self.assertRaises(ContractError) as raised:
            self.repo.push(local, str(bare), 'shared')
        self.assertEqual(raised.exception.code, 'git_push_rejected')
        self.assertEqual(self.repo.head(), local)
        self.assertEqual(self.git('rev-parse', 'refs/heads/shared', cwd=bare), remote)

    def test_same_note_conflict_preserves_live_checkout(self):
        base = self.repo.head()
        (self.root / 'wiki/A.md').write_text('local\n', encoding='utf-8')
        local = self.repo.checkpoint(str(uuid4()), base, self.hashes('wiki/A.md'))
        other = self.fixture / 'other'
        self.git('clone', str(self.root), str(other), cwd=self.fixture)
        self.git('config', 'user.name', 'Other', cwd=other)
        self.git('config', 'user.email', 'other@example.invalid', cwd=other)
        self.git('checkout', '--detach', base, cwd=other)
        (other / 'wiki/A.md').write_text('remote\n', encoding='utf-8')
        self.git('add', '--', 'wiki/A.md', cwd=other)
        self.git('commit', '-m', 'remote', cwd=other)
        remote = self.repo.fetch(str(other), 'HEAD')
        with self.assertRaises(ContractError) as raised:
            self.repo.integrate(local, remote)
        self.assertEqual(raised.exception.code, 'git_conflict')
        self.assertEqual(self.repo.head(), local)
        self.assertEqual((self.root / 'wiki/A.md').read_text(), 'local\n')
        stage = Path(raised.exception.path)
        (stage / 'wiki/A.md').write_text('reviewed resolution\n', encoding='utf-8')
        digest = capture_snapshot(stage).digest
        with self.assertRaises(ContractError):
            self.repo.resolve_candidate(stage, local, remote, '0' * 64)
        candidate = self.repo.resolve_candidate(stage, local, remote, digest)
        self.assertEqual(self.repo.head(), local)
        self.assertEqual((Path(candidate['root']) / 'wiki/A.md').read_text(), 'reviewed resolution\n')
        self.assertTrue(self.repo.is_ancestor(local, candidate['oid']))
        self.assertTrue(self.repo.is_ancestor(remote, candidate['oid']))

    def test_checkpoint_trailers_are_recorded_validated_and_do_not_break_recovery(self):
        base = self.repo.head()
        (self.root / 'wiki/A.md').write_text('# A\nchanged\n', encoding='utf-8')
        operation = str(uuid4())
        files = self.hashes('wiki/A.md')
        oid = self.repo.checkpoint(operation, base, files, trailers={'Teseo-Skill': 'ingest', 'Teseo-Agent': 'claude'})
        body = self.git('show', '-s', '--format=%B', oid)
        self.assertIn(f'Teseo-Operation: {operation}', body)
        self.assertIn('Teseo-Agent: claude\nTeseo-Skill: ingest', body)
        self.assertEqual(self.git('show', '-s', '--format=%(trailers:key=Teseo-Agent,valueonly)', oid).strip(), 'claude')
        self.assertEqual(self.repo.find_checkpoint(operation, base, files), oid)

    def test_invalid_trailers_are_rejected_before_any_commit(self):
        base = self.repo.head()
        (self.root / 'wiki/A.md').write_text('# A\nchanged\n', encoding='utf-8')
        files = self.hashes('wiki/A.md')
        for bad in ({'Co-Authored-By': 'x'}, {'Teseo-Agent': 'Claude'}, {'Teseo-Agent': 'a\nTeseo-Skill: b'},
                    {'Teseo-Skill': ''}, {'Teseo-Skill': 'x' * 40}, ['Teseo-Agent']):
            with self.assertRaises(ContractError) as raised:
                self.repo.checkpoint(str(uuid4()), base, files, trailers=bad)
            self.assertEqual(raised.exception.code, 'git_invalid_message')
        self.assertEqual(self.repo.head(), base)

    def test_incremental_audit_counts_only_unpublished_commits(self):
        published = self.repo.head()
        for index in range(129):
            self.git('commit', '--allow-empty', '-m', f'c{index}')
        head = self.repo.head()
        with self.assertRaises(ContractError) as raised:
            self.repo.audit_history(head)
        self.assertEqual(raised.exception.code, 'git_history_limit')
        with self.assertRaises(ContractError) as raised:
            self.repo.audit_history(head, published)
        self.assertEqual(raised.exception.code, 'git_history_limit')
        recent = self.git('rev-parse', 'HEAD~2')
        result = self.repo.audit_history(head, recent)
        self.assertEqual(result['commits'], 2)
        self.assertTrue(result['history_audited'])

    def test_incremental_audit_still_rejects_new_forbidden_content_and_unrelated_published(self):
        published = self.repo.head()
        (self.root / '.graph').mkdir()
        (self.root / '.graph/domande.sqlite').write_bytes(b'private')
        self.git('add', '--', '.graph/domande.sqlite')
        self.git('commit', '-m', 'private')
        with self.assertRaises(ContractError) as raised:
            self.repo.audit_history(self.repo.head(), published)
        self.assertEqual(raised.exception.code, 'git_history_policy')
        # Un "published" non antenato non riduce l'audit: ricade su quello completo.
        self.git('checkout', '-q', '-b', 'side', published)
        self.git('commit', '--allow-empty', '-m', 'side')
        side = self.repo.head()
        self.git('checkout', '-q', 'shared')
        with self.assertRaises(ContractError) as raised:
            self.repo.audit_history(self.repo.head(), side)
        self.assertEqual(raised.exception.code, 'git_history_policy')

    def _diverged_with_logs(self, note_conflict=False, logs=None):
        """Base con log.md/index.md; locale e remoto aggiungono righe diverse ai due file.

        logs=(base, locale, remoto) sostituisce i testi di log.md."""
        base_log, local_log, remote_log = logs or ('# Log\n', '# Log\n## [2026-10-27] ingest | locale\n',
                                                   '# Log\n## [2026-10-27] lint | remoto\n')
        (self.root / 'log.md').write_text(base_log, encoding='utf-8')
        (self.root / 'index.md').write_text('# Indice\n', encoding='utf-8')
        self.git('add', '--', 'log.md', 'index.md')
        self.git('commit', '-m', 'schema files')
        base = self.repo.head()
        other = self.fixture / 'other'
        self.git('clone', str(self.root), str(other), cwd=self.fixture)
        self.git('config', 'user.name', 'Other', cwd=other)
        self.git('config', 'user.email', 'other@example.invalid', cwd=other)
        self.git('checkout', '--detach', base, cwd=other)
        (self.root / 'log.md').write_text(local_log, encoding='utf-8')
        (self.root / 'index.md').write_text('# Indice\n- [[Locale]]\n', encoding='utf-8')
        (self.root / 'wiki/A.md').write_text('# A\nlocal\n', encoding='utf-8')
        local = self.repo.checkpoint(str(uuid4()), base, self.hashes('log.md', 'index.md', 'wiki/A.md'))
        (other / 'log.md').write_text(remote_log, encoding='utf-8')
        (other / 'index.md').write_text('# Indice\n- [[Remoto]]\n', encoding='utf-8')
        (other / 'wiki/A.md' if note_conflict else other / 'wiki/B.md').write_text('# X\nremote\n', encoding='utf-8')
        self.git('add', '--', 'log.md', 'index.md', 'wiki', cwd=other)
        self.git('commit', '-m', 'remote', cwd=other)
        return local, self.repo.fetch(str(other), 'HEAD')

    def test_log_and_index_concurrent_appends_are_unioned_in_the_isolated_candidate(self):
        local, remote = self._diverged_with_logs()
        candidate = self.repo.integrate(local, remote)
        stage = Path(candidate['root'])
        log = (stage / 'log.md').read_text(encoding='utf-8')
        index = (stage / 'index.md').read_text(encoding='utf-8')
        for text, lines in ((log, ('locale', 'remoto')), (index, ('[[Locale]]', '[[Remoto]]'))):
            for line in lines:
                self.assertIn(line, text)
            self.assertNotIn('<<<<<<<', text)
        self.assertTrue((stage / 'wiki/B.md').is_file())
        self.assertTrue(self.repo.is_ancestor(local, candidate['oid']))
        self.assertTrue(self.repo.is_ancestor(remote, candidate['oid']))
        self.assertEqual(self.repo.head(), local)
        self.assertNotIn('remoto', (self.root / 'log.md').read_text(encoding='utf-8'))
        self.assertFalse((stage / '.git/teseo-union').exists())
        self.assertEqual(self.git('status', '--porcelain', cwd=stage), '')

    def test_union_never_hides_a_conflict_on_a_real_note(self):
        local, remote = self._diverged_with_logs(note_conflict=True)
        with self.assertRaises(ContractError) as raised:
            self.repo.integrate(local, remote)
        self.assertEqual(raised.exception.code, 'git_conflict')
        stage = Path(raised.exception.path)
        self.assertIn('<<<<<<<', (stage / 'wiki/A.md').read_text(encoding='utf-8'))
        self.assertIn('<<<<<<<', (stage / 'log.md').read_text(encoding='utf-8'))
        self.assertEqual(self.repo.head(), local)
        self.assertEqual((self.root / 'wiki/A.md').read_text(encoding='utf-8'), '# A\nlocal\n')

    def test_local_excludes_replace_only_the_teseo_block_and_reject_unsafe_patterns(self):
        exclude = self.root / '.git/info/exclude'
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text('# mio\nnotes-privati/\n', encoding='utf-8')
        self.assertEqual(write_local_excludes(self.root, ['.graph/', 'CLAUDE.md', '.graph/']), ['.graph/', 'CLAUDE.md'])
        first = exclude.read_text(encoding='utf-8')
        self.assertEqual(first, '# mio\nnotes-privati/\n# teseo:begin\n.graph/\nCLAUDE.md\n# teseo:end\n')
        write_local_excludes(self.root, ['.graph/', 'CLAUDE.md'])
        self.assertEqual(exclude.read_text(encoding='utf-8'), first)
        write_local_excludes(self.root, ['.obsidian/'])
        self.assertEqual(exclude.read_text(encoding='utf-8'), '# mio\nnotes-privati/\n# teseo:begin\n.obsidian/\n# teseo:end\n')
        (self.root / '.graph').mkdir()
        (self.root / '.obsidian').mkdir()
        (self.root / '.obsidian/app.json').write_text('{}', encoding='utf-8')
        self.assertNotIn('.obsidian', self.git('status', '--porcelain', '--untracked-files=all'))
        for bad in ('../x', '/abs', 'a\\b', ''):
            with self.assertRaises(ContractError):
                write_local_excludes(self.root, [bad])
        write_local_excludes(self.root, [])
        self.assertEqual(exclude.read_text(encoding='utf-8'), '# mio\nnotes-privati/\n')

    def test_union_is_refused_when_a_side_deleted_lines_that_the_merge_would_silently_drop(self):
        logs = ('# Log\nA\nB\n', '# Log\nB\nC\n', '# Log\nA\nB\nD\n')
        local, remote = self._diverged_with_logs(logs=logs)
        with self.assertRaises(ContractError) as raised:
            self.repo.integrate(local, remote)
        self.assertEqual(raised.exception.code, 'git_conflict')
        self.assertEqual(self.repo.head(), local)

    def test_local_excludes_are_literal_for_names_git_would_read_as_globs_or_comments(self):
        names = ['raw/[v2].pdf', 'raw/#nota.pdf', 'raw/!urgente.pdf', 'raw/normale.pdf']
        for name in names:
            (self.root / name).write_bytes(b'%PDF\x00')
        self.assertEqual(len([line for line in self.git('status', '--porcelain', '--untracked-files=all').splitlines()
                              if line.startswith('??')]), 4)
        write_local_excludes(self.root, names)
        self.assertEqual(self.git('status', '--porcelain', '--untracked-files=all'), '')
        self.assertEqual(read_local_excludes(self.root), sorted(names))
        write_local_excludes(self.root, [*read_local_excludes(self.root), 'raw/altro.pdf'])
        self.assertEqual(read_local_excludes(self.root), sorted([*names, 'raw/altro.pdf']))

    def test_local_excludes_refuse_an_unclosed_block_without_writing(self):
        exclude = self.root / '.git/info/exclude'
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text('# teseo:begin\n.graph/\n', encoding='utf-8')
        with self.assertRaises(ContractError) as raised:
            write_local_excludes(self.root, ['x/'])
        self.assertEqual(raised.exception.code, 'git_unsafe_config')
        self.assertEqual(exclude.read_text(encoding='utf-8'), '# teseo:begin\n.graph/\n')


if __name__ == '__main__':
    unittest.main()


class ExecutableSearch(unittest.TestCase):
    """_executable: solo voci assolute di PATH, estensioni provate a mano (Python 3.10 su Windows non le prova)."""

    def test_extensions_are_tried_in_order_and_relative_path_entries_are_ignored(self):
        import tempfile
        from unittest import mock
        from kit.dashboard import git_sync
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            (folder / 'git.EXE').write_bytes(b'x')
            (folder / 'git.EXE').chmod(0o755)
            with mock.patch.object(git_sync, '_pathext', return_value=['.CMD', '.EXE']), \
                    mock.patch.dict('os.environ', {'PATH': os.pathsep.join(['relativa', '', str(folder)])}):
                self.assertEqual(git_sync._executable('git'), str(folder / 'git.EXE'))
                self.assertIsNone(git_sync._executable('inesistente'))

    def test_a_relative_path_entry_is_never_searched_even_if_it_holds_the_binary(self):
        import tempfile
        from unittest import mock
        from kit.dashboard import git_sync
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'git').write_bytes(b'x')
            (Path(temp) / 'git').chmod(0o755)
            with mock.patch.object(git_sync, '_pathext', return_value=['']), mock.patch.dict('os.environ', {'PATH': '.'}):
                cwd = os.getcwd()
                os.chdir(temp)
                try:
                    self.assertIsNone(git_sync._executable('git'))
                finally:
                    os.chdir(cwd)

    def test_pathext_is_empty_extension_on_posix_and_dotted_on_windows(self):
        from unittest import mock
        from kit.dashboard import git_sync
        if os.name == 'nt':
            with mock.patch.dict('os.environ', {'PATHEXT': '.EXE;.CMD;;bad'}):
                self.assertEqual(git_sync._pathext(), ['.EXE', '.CMD'])
        else:
            self.assertEqual(git_sync._pathext(), [''])

"""ECC TDD: publication primitives exercise real temporary Git repositories."""
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
                                    preview_data_repository, github_repository_url, _invoke, _oid, _branch)


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
                            'https.proxy\nhttp://proxy.invalid\x00'):
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


if __name__ == '__main__':
    unittest.main()

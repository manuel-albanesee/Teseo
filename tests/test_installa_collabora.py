"""installa.py --collabora: repository dati creato, clonato o agganciato, con autosync attivo (remoto bare locale)."""
import _shortpath  # noqa: F401
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import installa
from kit.dashboard.autosync import Autosync

ROOT = Path(__file__).resolve().parents[1]
ALICE = {'name': 'Alice', 'email': 'alice@example.invalid'}


def git(cwd, *args):
    done = subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True)
    return done.stdout.decode('utf-8').strip()


class CollaboraInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='teseo-publisher-', dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.remote = self.home / 'remote.git'
        git(self.home, 'init', '--bare', '-b', 'main', str(self.remote))

    def options(self, **extra):
        return dict(dict(url=str(self.remote), branch='main', visibilita='private', crea_remote=False, si=True,
                         locale=True), **extra)

    def install(self, vault, *, author=ALICE, **extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch('kit.dashboard.git_sync.global_author', return_value=author):
            installa.installa(vault, skill='no', client='claude', collabora=self.options(**extra))
        return output.getvalue()

    def seed(self, vault):
        (vault / 'raw').mkdir(parents=True)
        (vault / 'raw/rapporto.pdf').write_bytes(b'%PDF-1.4\x00binary')
        (vault / 'raw/appunti.md').write_text('# Appunti\n', encoding='utf-8')
        (vault / 'CLAUDE.md').write_text('istruzioni locali\n', encoding='utf-8')

    def remote_files(self):
        """File del branch condiviso; [] se il remoto è ancora vuoto (nulla è stato pubblicato)."""
        if not git(self.remote, 'for-each-ref', 'refs/heads/main'):
            return []
        return git(self.remote, 'ls-tree', '-r', '--name-only', 'main').splitlines()

    def test_new_vault_creates_the_data_repository_publishes_only_the_approved_selection_and_enables_autosync(self):
        vault = self.home / 'vault'
        self.seed(vault)
        report = self.install(vault)
        tree = self.remote_files()
        self.assertIn('.teseo/project.json', tree)
        self.assertIn('raw/appunti.md', tree)
        self.assertIn('Wiki reference.md', tree)
        for private in ('raw/rapporto.pdf', 'CLAUDE.md'):
            self.assertNotIn(private, tree)
        self.assertFalse([p for p in tree if p.startswith(('.graph/', '.claude/', '.teseo/local/'))])
        self.assertEqual(git(self.remote, 'show', '-s', '--format=%an <%ae>', 'main'), 'Alice <alice@example.invalid>')
        self.assertEqual(git(vault, 'status', '--porcelain'), '')
        self.assertTrue((vault / 'raw/rapporto.pdf').is_file())
        self.assertTrue(Autosync(vault, allow_local_remote=True).enabled())
        self.assertIn('autosync', report)
        self.assertIn('raw/appunti.md', report)

    def test_lavorazioni_non_sporcano_il_repository_dati_ne_bloccano_la_sincronizzazione(self):
        # Un file non tracciato fermerebbe `pre` (autosync_unpublished): le lavorazioni sono personali.
        vault = self.home / 'vault'
        self.seed(vault)
        self.install(vault)
        (vault / 'lavorazioni/prova/esecuzioni/2026-10-30-1').mkdir(parents=True)
        (vault / 'lavorazioni/prova/config.md').write_text('---\nselezione: {}\n---\n', encoding='utf-8')
        (vault / 'lavorazioni/prova/esecuzioni/2026-10-30-1/esecuzione.json').write_text('{}\n', encoding='utf-8')
        self.assertEqual(git(vault, 'status', '--porcelain'), '')
        head = git(self.remote, 'rev-parse', 'main')
        result = Autosync(vault, allow_local_remote=True).pre('ingest', 'claude')
        self.assertEqual((result['exit'], result['state']), (0, result['state']), result['message'])
        self.assertNotEqual(result['state'], 'blocked')
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), head)
        self.assertNotIn('lavorazioni/prova/config.md', self.remote_files())

    def test_rerunning_the_same_command_is_idempotent_after_a_complete_install(self):
        vault = self.home / 'vault'
        self.seed(vault)
        self.install(vault)
        head = git(self.remote, 'rev-parse', 'main')
        self.install(vault)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), head)
        self.assertTrue(Autosync(vault, allow_local_remote=True).enabled())

    def test_empty_folder_clones_a_populated_data_repository(self):
        first = self.home / 'first'
        self.seed(first)
        self.install(first)
        second = self.home / 'second'
        report = self.install(second, author={})
        self.assertIn('clonato', report)
        self.assertEqual(git(second, 'rev-parse', 'HEAD'), git(self.remote, 'rev-parse', 'main'))
        self.assertTrue((second / '.graph/teseo_git.py').is_file())
        self.assertTrue((second / 'raw/appunti.md').is_file())
        self.assertFalse((second / 'raw/rapporto.pdf').exists())
        self.assertEqual(git(second, 'status', '--porcelain'), '')
        self.assertTrue(Autosync(second, allow_local_remote=True).enabled())

    def test_a_populated_remote_is_never_overwritten_by_a_non_empty_vault(self):
        first = self.home / 'first'
        self.seed(first)
        self.install(first)
        head = git(self.remote, 'rev-parse', 'main')
        other = self.home / 'other'
        self.seed(other)
        with self.assertRaises(ValueError) as raised:
            self.install(other)
        self.assertIn('già contenuti', str(raised.exception))
        self.assertFalse((other / '.git').exists())
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), head)

    def test_missing_git_identity_stops_before_creating_anything(self):
        vault = self.home / 'vault'
        self.seed(vault)
        with self.assertRaises(ValueError) as raised:
            self.install(vault, author={})
        self.assertIn('user.name', str(raised.exception))
        self.assertFalse((vault / '.git').exists())
        self.assertEqual(self.remote_files(), [])

    def test_unreachable_remote_points_to_the_create_flag(self):
        missing = str(self.home / 'assente')
        for name in ('nuovo', 'esistente'):
            vault = self.home / name
            if name == 'esistente':
                self.seed(vault)
            with self.assertRaises(ValueError) as raised:
                self.install(vault, url=missing)
            self.assertIn('--crea-remote', str(raised.exception))
            self.assertFalse((vault / '.git').exists())

    def test_remote_creation_needs_github_gh_authentication_and_confirmation(self):
        quiet = io.StringIO()
        with self.assertRaises(ValueError) as raised:
            installa._crea_remoto(str(self.remote), 'private', True, installa.Rapporto())
        self.assertIn('github.com', str(raised.exception))
        with mock.patch('installa.shutil.which', return_value=None), self.assertRaises(ValueError) as raised:
            installa._crea_remoto('https://github.com/o/r.git', 'private', True, installa.Rapporto())
        self.assertIn('gh', str(raised.exception))
        denied = subprocess.CompletedProcess([], 1, b'', b'')
        with mock.patch('installa.shutil.which', return_value='gh'), mock.patch('installa.subprocess.run', return_value=denied), \
                self.assertRaises(ValueError) as raised:
            installa._crea_remoto('https://github.com/o/r.git', 'private', True, installa.Rapporto())
        self.assertIn('autenticato', str(raised.exception))
        with mock.patch('installa.shutil.which', return_value='gh'), \
                mock.patch('installa.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run, \
                contextlib.redirect_stdout(quiet):
            installa._crea_remoto('https://github.com/o/r.git', 'private', True, installa.Rapporto())
        self.assertEqual(run.call_args_list[-1].args[0], ['gh', 'repo', 'create', 'o/r', '--private'])
        self.assertNotIn('shell', run.call_args_list[-1].kwargs)
        with mock.patch('installa.sys.stdin.isatty', return_value=False), self.assertRaises(ValueError) as raised:
            installa._conferma('Procedere?', False)
        self.assertIn('--si', str(raised.exception))
        with mock.patch('installa.sys.stdin.isatty', return_value=True), mock.patch('builtins.input', return_value='no'):
            self.assertFalse(installa._conferma('Procedere?', False))
        with mock.patch('installa.sys.stdin.isatty', return_value=True), mock.patch('builtins.input', return_value='s'):
            self.assertTrue(installa._conferma('Procedere?', False))

    def test_declining_the_confirmation_publishes_nothing(self):
        vault = self.home / 'vault'
        self.seed(vault)
        with mock.patch('installa._conferma', return_value=False), self.assertRaises(ValueError) as raised:
            self.install(vault, si=False)
        self.assertIn('annullata', str(raised.exception))
        self.assertFalse((vault / '.git').exists())
        self.assertEqual(self.remote_files(), [])

    def test_an_existing_repository_with_another_remote_is_refused(self):
        vault = self.home / 'vault'
        self.seed(vault)
        git(self.home, 'init', '-b', 'main', str(vault))
        git(self.home, 'init', '--bare', str(self.home / 'altro.git'))
        git(vault, 'remote', 'add', 'origin', str(self.home / 'altro.git'))
        with self.assertRaises(ValueError) as raised:
            self.install(vault)
        self.assertIn('remote diverso', str(raised.exception))
        self.assertEqual(self.remote_files(), [])

    def test_command_line_rejects_incompatible_options(self):
        target = str(self.home / 'x')
        for args in (['--collabora', 'https://github.com/o/r.git', '--solo-integrazione'],
                     ['--collabora', 'https://github.com/o/r.git', '--prova'], ['--crea-remote'], ['--si']):
            done = subprocess.run([sys.executable, '-B', str(ROOT / 'installa.py'), target, *args], capture_output=True)
            self.assertEqual(done.returncode, 2, (args, done.stderr.decode('utf-8', 'replace')))
        self.assertFalse((self.home / 'x').exists())


if __name__ == '__main__':
    unittest.main()

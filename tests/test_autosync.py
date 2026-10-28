"""Autosync end-to-end: due copie del vault, remoto bare locale, kit installato davvero (nessuna rete)."""
import _shortpath  # noqa: F401
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import installa
from kit.dashboard.autosync import Autosync
from kit.dashboard.contracts import ContractError
from kit.dashboard.git_sync import GitRepository, read_local_excludes, write_local_excludes

LOCAL = ['.graph/', '.graph_backup/', '.claude/', '.codex/', '.agents/', '.github/', '.obsidian/', '.trash/',
         'CLAUDE.md', 'AGENTS.md']
NL = chr(10)
CLI = Path(__file__).resolve().parents[1] / 'kit/graph/teseo_git.py'


def git(cwd, *args):
    done = subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True)
    return done.stdout.decode('utf-8').strip()


class AutosyncFlow(unittest.TestCase):
    """Fixture costruito una volta (ogni sottoprocesso Git costa ~75 ms su Windows) e ripristinato per ogni test."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='teseo-publisher-', dir=Path.cwd())
        cls.home = Path(cls.tmp.name)
        template = cls.home / 't'
        with contextlib.redirect_stdout(io.StringIO()):
            installa.installa(template, skill='no', esempio=True, client='claude', dashboard=True)
        cls.remote, cls.a, cls.b = (cls.home / n for n in ('remote.git', 'a', 'b'))
        git(cls.home, 'init', '--bare', '-b', 'main', str(cls.remote))
        shutil.copytree(template, cls.a)
        git(cls.a, 'init', '-b', 'main')
        cls.identity(cls.a, 'Alice')
        write_local_excludes(cls.a, LOCAL)
        git(cls.a, 'add', '-A')
        git(cls.a, 'commit', '-m', 'base')
        git(cls.a, 'remote', 'add', 'origin', str(cls.remote))
        git(cls.a, 'push', '-u', 'origin', 'main')
        Autosync(cls.a, allow_local_remote=True).enable()
        git(cls.home, 'clone', '--branch', 'main', str(cls.remote), str(cls.b))
        shutil.copytree(template / '.graph', cls.b / '.graph')
        cls.identity(cls.b, 'Bob')
        write_local_excludes(cls.b, LOCAL)
        Autosync(cls.b, allow_local_remote=True).enable()
        cls.golden = {root: cls.snapshot(root) for root in (cls.a, cls.b)}
        cls.golden_head = git(cls.remote, 'rev-parse', 'main')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def snapshot(root):
        return dict(head=git(root, 'rev-parse', 'HEAD'), sync=(root / '.teseo/local/sync.sqlite').read_bytes(),
                    exclude=(root / '.git/info/exclude').read_bytes())

    @staticmethod
    def restore(root, saved):
        git(root, 'reset', '--hard', saved['head'])
        git(root, 'clean', '-fd')
        for relative in ('raw/rapporto.pdf', '.teseo/local/autosync.sqlite'):
            (root / relative).unlink(missing_ok=True)
        (root / '.teseo/local/sync.sqlite').write_bytes(saved['sync'])
        (root / '.git/info/exclude').write_bytes(saved['exclude'])

    def setUp(self):
        git(self.remote, 'update-ref', 'refs/heads/main', self.golden_head)
        for root, saved in self.golden.items():
            self.restore(root, saved)
        self.sync_a = Autosync(self.a, allow_local_remote=True)
        self.sync_b = Autosync(self.b, allow_local_remote=True)

    @staticmethod
    def identity(root, name):
        git(root, 'config', 'user.name', name)
        git(root, 'config', 'user.email', name.lower() + '@example.invalid')

    @staticmethod
    def append(root, relative, text):
        with (root / relative).open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(text)

    def remote_text(self, path):
        return git(self.remote, 'show', 'main:' + path)

    def remote_head_message(self):
        return git(self.remote, 'show', '-s', '--format=%an|%B', 'main')

    def test_pre_when_aligned_opens_a_session_without_receiving(self):
        result = self.sync_a.pre('ingest', 'claude')
        self.assertEqual((result['state'], result['exit'], result['received']), ('ready', 0, 0), result)
        self.assertEqual([s['state'] for s in self.sync_a._sessions()], ['open'])

    def test_post_publishes_with_person_agent_and_skill_attribution(self):
        self.sync_a.pre('ingest', 'claude')
        self.append(self.a, 'wiki/Gestionale.md', '\nNota di Alice.\n')
        self.append(self.a, 'log.md', '\n## [2026-10-27] ingest | alice\n')
        result = self.sync_a.post('ingest', 'claude')
        self.assertEqual((result['state'], result['exit']), ('published', 0), result)
        self.assertEqual(result['graph'], 'ok')
        message = self.remote_head_message()
        self.assertTrue(message.startswith('Alice|Teseo: ingest (claude)'), message)
        self.assertIn('Teseo-Agent: claude\nTeseo-Skill: ingest', message)
        self.assertIn('Nota di Alice.', self.remote_text('wiki/Gestionale.md'))
        self.assertEqual(git(self.a, 'rev-parse', 'HEAD'), git(self.remote, 'rev-parse', 'main'))
        self.assertEqual(git(self.a, 'status', '--porcelain'), '')

    def test_pre_receives_what_another_user_published(self):
        self.sync_a.pre('ingest', 'claude')
        self.append(self.a, 'wiki/Gestionale.md', '\nNota di Alice.\n')
        self.assertEqual(self.sync_a.post('ingest', 'claude')['state'], 'published')
        result = self.sync_b.pre('lint', 'codex')
        self.assertEqual((result['state'], result['received'], result['exit']), ('ready', 1, 0), result)
        self.assertIn('Nota di Alice.', (self.b / 'wiki/Gestionale.md').read_text(encoding='utf-8'))
        self.assertEqual(git(self.b, 'rev-parse', 'HEAD'), git(self.remote, 'rev-parse', 'main'))
        self.assertEqual(self.sync_b.pre('lint', 'codex')['received'], 0)

    @staticmethod
    def new_note(root, name, body=''):
        text = NL.join(['---', 'tipo: concetto', '---', '', '# ' + name, '', body, ''])
        (root / 'wiki' / (name + '.md')).write_text(text, encoding='utf-8', newline=NL)

    def test_unrelated_notes_and_concurrent_log_entries_are_integrated_without_a_decision(self):
        self.sync_a.pre('ingest', 'claude')
        self.sync_b.pre('lint', 'codex')
        self.new_note(self.a, 'Nota di Alice', 'Testo di Alice.')
        self.append(self.a, 'log.md', NL + '## [2026-10-27] ingest | voce di alice' + NL)
        self.new_note(self.b, 'Nota di Bob', 'Testo di Bob.')
        self.append(self.b, 'log.md', NL + '## [2026-10-27] lint | voce di bob' + NL)
        self.assertEqual(self.sync_a.post('ingest', 'claude')['state'], 'published')
        result = self.sync_b.post('lint', 'codex')
        self.assertEqual((result['state'], result['exit']), ('published', 0), result)
        log = self.remote_text('log.md')
        self.assertIn('voce di alice', log)
        self.assertIn('voce di bob', log)
        self.assertNotIn('<<<<<<<', log)
        self.assertIn('Testo di Alice.', self.remote_text('wiki/Nota di Alice.md'))
        self.assertIn('Testo di Bob.', self.remote_text('wiki/Nota di Bob.md'))
        self.assertEqual(git(self.b, 'status', '--porcelain'), '')
        self.assertEqual(git(self.b, 'rev-parse', 'HEAD'), git(self.remote, 'rev-parse', 'main'))
        self.assertTrue((self.b / 'wiki/Nota di Alice.md').is_file())

    def test_linked_notes_changed_concurrently_wait_for_a_decision_in_the_dashboard(self):
        self.sync_a.pre('ingest', 'claude')
        self.sync_b.pre('lint', 'codex')
        self.new_note(self.a, 'Nota di Alice', 'Vedi [[Gestionale]].')
        self.append(self.b, 'wiki/Gestionale.md', NL + 'Aggiunta di Bob.' + NL)
        self.assertEqual(self.sync_a.post('ingest', 'claude')['state'], 'published')
        result = self.sync_b.post('lint', 'codex')
        self.assertEqual((result['state'], result['exit'], result['job_state']), ('blocked', 2, 'needs_decision'), result)
        self.assertIn('Aggiunta di Bob.', (self.b / 'wiki/Gestionale.md').read_text(encoding='utf-8'))
        self.assertNotIn('Aggiunta di Bob.', self.remote_text('wiki/Gestionale.md'))
        self.assertFalse((self.b / 'wiki/Nota di Alice.md').exists())

    def test_same_note_conflict_blocks_without_touching_the_live_vault(self):
        self.sync_a.pre('ingest', 'claude')
        self.sync_b.pre('lint', 'codex')
        self.append(self.a, 'wiki/Gestionale.md', '\nVersione di Alice.\n')
        self.append(self.b, 'wiki/Gestionale.md', '\nVersione di Bob.\n')
        self.assertEqual(self.sync_a.post('ingest', 'claude')['state'], 'published')
        result = self.sync_b.post('lint', 'codex')
        self.assertEqual((result['state'], result['exit']), ('blocked', 2), result)
        self.assertEqual(result['error']['code'], 'git_conflict')
        live = (self.b / 'wiki/Gestionale.md').read_text(encoding='utf-8')
        self.assertIn('Versione di Bob.', live)
        self.assertNotIn('Versione di Alice.', live)
        self.assertNotIn('<<<<<<<', live)
        self.assertNotIn('Versione di Bob.', self.remote_text('wiki/Gestionale.md'))
        again = self.sync_b.pre('lint', 'codex')
        self.assertEqual((again['state'], again['exit']), ('blocked', 2), again)

    def test_manual_edits_publish_without_a_prior_pre(self):
        self.append(self.a, 'wiki/Gestionale.md', '\nModifica fatta in Obsidian.\n')
        result = self.sync_a.post('manuale', 'umano')
        self.assertEqual((result['state'], result['exit']), ('published', 0), result)
        self.assertIn('Teseo-Agent: umano\nTeseo-Skill: manuale', self.remote_head_message())

    def test_post_without_a_session_is_refused_for_regular_skills(self):
        self.append(self.a, 'wiki/Gestionale.md', '\nTesto.\n')
        result = self.sync_a.post('ingest', 'claude')
        self.assertEqual((result['state'], result['exit']), ('blocked', 2))
        self.assertEqual(result['error']['code'], 'autosync_no_session')

    def test_pre_refuses_unpublished_changes_and_names_the_command(self):
        self.append(self.a, 'wiki/Gestionale.md', '\nDimenticata.\n')
        result = self.sync_a.pre('lint', 'claude')
        self.assertEqual((result['state'], result['exit']), ('blocked', 2))
        self.assertEqual(result['error']['code'], 'autosync_unpublished')
        self.assertIn('post --skill manuale', result['message'])

    def test_a_second_pre_abandons_a_clean_stale_session(self):
        first = self.sync_a.pre('ingest', 'claude')['session']
        second = self.sync_a.pre('lint', 'claude')
        self.assertEqual(second['state'], 'ready')
        states = {s['id']: s['state'] for s in self.sync_a._sessions()}
        self.assertEqual((states[first], states[second['session']]), ('abandoned', 'open'))

    def test_invalid_graph_blocks_publication_and_keeps_the_session_open(self):
        self.sync_a.pre('ingest', 'claude')
        head = git(self.a, 'rev-parse', 'HEAD')
        self.append(self.a, 'wiki/Gestionale.md', '\nVedi [[Pagina che non esiste]].\n')
        result = self.sync_a.post('ingest', 'claude')
        self.assertEqual((result['state'], result['exit']), ('blocked', 2))
        self.assertEqual(result['error']['code'], 'autosync_graph_check')
        self.assertEqual(git(self.a, 'rev-parse', 'HEAD'), head)
        self.assertEqual([s['state'] for s in self.sync_a._sessions()], ['open'])
        (self.a / 'wiki/Gestionale.md').write_text(git(self.a, 'show', 'HEAD:wiki/Gestionale.md') + '\n', encoding='utf-8')
        self.append(self.a, 'wiki/Gestionale.md', '\nCorretta.\n')
        self.assertEqual(self.sync_a.post('ingest', 'claude')['state'], 'published')

    def test_network_failure_keeps_the_commit_and_resumes_when_online(self):
        self.sync_a.pre('ingest', 'claude')
        self.append(self.a, 'wiki/Gestionale.md', '\nScritta offline.\n')
        offline = ContractError('git_network', 'fixture')
        with mock.patch.object(GitRepository, 'fetch', side_effect=offline):
            result = self.sync_a.post('ingest', 'claude')
        self.assertEqual((result['state'], result['exit']), ('waiting', 3), result)
        self.assertNotEqual(git(self.a, 'rev-parse', 'HEAD'), git(self.remote, 'rev-parse', 'main'))
        self.assertEqual(git(self.a, 'status', '--porcelain'), '')
        with mock.patch.object(GitRepository, 'fetch', side_effect=offline):
            blocked = self.sync_a.pre('lint', 'claude')
        self.assertEqual((blocked['state'], blocked['exit']), ('blocked', 2), blocked)
        resumed = self.sync_a.resume()
        self.assertEqual((resumed['state'], resumed['exit']), ('published', 0), resumed)
        self.assertEqual(git(self.a, 'rev-parse', 'HEAD'), git(self.remote, 'rev-parse', 'main'))
        self.assertEqual(self.sync_a.resume()['state'], 'noop')

    def test_pre_offline_proceeds_with_a_warning_and_publishes_later(self):
        offline = ContractError('git_network', 'fixture')
        with mock.patch.object(GitRepository, 'fetch', side_effect=offline):
            result = self.sync_a.pre('ingest', 'claude')
        self.assertEqual((result['state'], result['exit'], result['offline']), ('ready', 0, True), result)
        self.assertIn('offline', result['message'])
        self.append(self.a, 'wiki/Gestionale.md', '\nDopo il ritorno online.\n')
        self.assertEqual(self.sync_a.post('ingest', 'claude')['state'], 'published')

    def test_binary_sources_stay_local_and_do_not_block_publication(self):
        self.sync_a.pre('ingest', 'claude')
        (self.a / 'raw/rapporto.pdf').write_bytes(b'%PDF-1.4\x00\x01binary')
        (self.a / 'raw/appunti.md').write_text('# Appunti\n', encoding='utf-8')
        self.append(self.a, 'wiki/Gestionale.md', '\nDa un PDF.\n')
        result = self.sync_a.post('ingest', 'claude')
        self.assertEqual((result['state'], result['local_only']), ('published', ['raw/rapporto.pdf']), result)
        tree = git(self.remote, 'ls-tree', '-r', '--name-only', 'main').splitlines()
        self.assertIn('raw/appunti.md', tree)
        self.assertNotIn('raw/rapporto.pdf', tree)
        self.assertIn('raw/rapporto.pdf', read_local_excludes(self.a))
        self.assertTrue((self.a / 'raw/rapporto.pdf').is_file())
        self.sync_a.pre('lint', 'claude')
        self.append(self.a, 'wiki/Gestionale.md', '\nSecondo giro.\n')
        self.assertEqual(self.sync_a.post('lint', 'claude')['state'], 'published')

    def test_files_outside_the_shared_policy_are_never_committed(self):
        self.sync_a.pre('ingest', 'claude')
        (self.a / 'appunti-privati.txt').write_text('privato\n', encoding='utf-8')
        result = self.sync_a.post('ingest', 'claude')
        self.assertEqual((result['state'], result['error']['code']), ('blocked', 'autosync_out_of_policy'), result)
        self.assertEqual(result['error']['path'], 'appunti-privati.txt')
        (self.a / 'appunti-privati.txt').unlink()
        token = 'ghp_' + 'A1b2C3d4' * 4
        self.append(self.a, 'wiki/Gestionale.md', '\nchiave ' + token + '\n')
        result = self.sync_a.post('ingest', 'claude')
        self.assertEqual(result['error']['code'], 'autosync_out_of_policy', result)
        self.assertNotIn(token, git(self.remote, 'log', '--all', '-p'))

    def test_nothing_changed_is_a_noop_and_creates_no_commit(self):
        self.sync_a.pre('ingest', 'claude')
        before = git(self.remote, 'rev-parse', 'main')
        result = self.sync_a.post('ingest', 'claude')
        self.assertEqual((result['state'], result['exit']), ('noop', 0), result)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), before)

    def test_vaults_without_consent_or_manifest_are_left_alone(self):
        self.sync_a.service.disable_automatic(self.sync_a.vault_id)
        self.append(self.a, 'wiki/Gestionale.md', '\nTesto.\n')
        for call in (lambda: self.sync_a.pre('ingest', 'claude'), lambda: self.sync_a.post('ingest', 'claude')):
            self.assertEqual((call()['state'], call()['exit']), ('disabled', 0))
        plain = self.home / 'plain'
        plain.mkdir(exist_ok=True)
        result = Autosync(plain).pre('ingest', 'claude')
        self.assertEqual((result['state'], result['exit']), ('disabled', 0))
        self.assertFalse((plain / '.teseo').exists())

    def test_invalid_skill_or_agent_is_rejected(self):
        for skill, agent in (('rm', 'claude'), ('ingest', 'gpt')):
            result = self.sync_a.pre(skill, agent)
            self.assertEqual((result['state'], result['error']['code']), ('blocked', 'autosync_request'))

    def run_cli(self, root, *args):
        done = subprocess.run([sys.executable, str(CLI), '--vault', str(root), *args], capture_output=True, cwd=root)
        return done.returncode, done.stdout.decode('utf-8'), done.stderr.decode('utf-8')

    def test_cli_exit_codes_and_json_contract(self):
        # Il CLI di produzione accetta solo remoti GitHub: qui restano fuori i percorsi che toccano il remoto.
        code, out, _ = self.run_cli(self.a, 'stato')
        self.assertEqual((code, json.loads(out)['state']), (0, 'enabled'))
        (self.a / 'appunti-privati.txt').write_text('x\n', encoding='utf-8')
        code, out, err = self.run_cli(self.a, 'post', '--skill', 'manuale', '--agente', 'umano')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['error']['code'], 'autosync_out_of_policy')
        self.assertIn('policy', err)
        (self.a / 'appunti-privati.txt').unlink()
        code, out, _ = self.run_cli(self.a, 'post', '--skill', 'manuale', '--agente', 'umano')
        self.assertEqual((code, json.loads(out)['state']), (0, 'noop'))
        plain = self.home / 'plain'
        plain.mkdir(exist_ok=True)
        code, out, _ = self.run_cli(plain, 'pre', '--skill', 'ingest', '--agente', 'claude')
        self.assertEqual((code, json.loads(out)['state']), (0, 'disabled'))
        code, _, err = self.run_cli(self.a, 'pre')
        self.assertEqual(code, 2)
        self.assertIn('--skill', err)


if __name__ == '__main__':
    unittest.main()

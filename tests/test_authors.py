"""Autori dalla storia Git: raccolta, rinomine, merge esclusi e API di consultazione."""
import _shortpath  # noqa: F401
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote

import test_dashboard_queries as queries
from kit.dashboard.authors import collect, history_head
from kit.dashboard.graph_service import rebuild


def git(root, *args, author=None, date=None, **env):
    environment = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', **env}
    if author:
        environment.update(GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL=author.lower() + '@example.org',
                           GIT_COMMITTER_NAME=author, GIT_COMMITTER_EMAIL=author.lower() + '@example.org')
    if date:
        environment.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    done = subprocess.run(['git', *args], cwd=root, env=environment, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout


def commit(root, message, author, date, **files):
    for name, text in files.items():
        path = Path(root) / 'wiki' / (name + '.md')
        path.write_text(text, encoding='utf-8')
    git(root, 'add', '-A', 'wiki')
    git(root, 'commit', '-q', '-m', message, author=author, date=date)


class Collect(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'wiki').mkdir()
        git(self.root, 'init', '-q', '-b', 'main')

    def test_without_history_or_repository_the_list_is_empty(self):
        self.assertEqual(collect(self.root, {'Anna'}), [])
        with tempfile.TemporaryDirectory() as bare:
            self.assertEqual((history_head(bare), collect(bare, {'Anna'})), (None, []))

    def test_creator_is_the_first_commit_and_modifier_the_latest_with_agent_trailer(self):
        commit(self.root, 'uno', 'Ada', '2026-10-01T10:00:00+00:00', Anna='a')
        commit(self.root, 'due\n\nTeseo-Skill: ingest\nTeseo-Agent: codex', 'Bruno', '2026-10-02T10:00:00+00:00', Anna='b')
        commit(self.root, 'tre', 'Carla', '2026-10-03T10:00:00+00:00', Anna='c', Bruno='x')
        rows = {row[0]: row for row in collect(self.root, {'Anna', 'Bruno'})}
        self.assertEqual(rows['Anna'], ('Anna', 'Ada', '2026-10-01T10:00:00+00:00', 'Carla', '2026-10-03T10:00:00+00:00', None, 3))
        self.assertEqual(rows['Bruno'][1:4:2], ('Carla', 'Carla'))

    def test_agent_comes_from_the_latest_commit_that_touched_the_page(self):
        commit(self.root, 'uno\n\nTeseo-Agent: claude', 'Ada', '2026-10-01T10:00:00+00:00', Anna='a')
        self.assertEqual(collect(self.root, {'Anna'})[0][5], 'claude')
        commit(self.root, 'due', 'Bruno', '2026-10-02T10:00:00+00:00', Anna='b')
        self.assertIsNone(collect(self.root, {'Anna'})[0][5])

    def test_renames_are_followed_back_to_the_creator(self):
        commit(self.root, 'uno', 'Ada', '2026-10-01T10:00:00+00:00', Vecchia='contenuto abbastanza lungo da essere riconosciuto come rinomina\n' * 5)
        git(self.root, 'mv', 'wiki/Vecchia.md', 'wiki/Nuova.md')
        git(self.root, 'commit', '-q', '-m', 'rinomina', author='Bruno', date='2026-10-02T10:00:00+00:00')
        row = collect(self.root, {'Nuova'})[0]
        self.assertEqual((row[0], row[1], row[3], row[6]), ('Nuova', 'Ada', 'Bruno', 2))

    def test_merge_commits_do_not_count_as_authors(self):
        commit(self.root, 'base', 'Ada', '2026-10-01T10:00:00+00:00', Anna='a', Bruno='b')
        git(self.root, 'checkout', '-q', '-b', 'altro')
        commit(self.root, 'ramo', 'Bruno', '2026-10-02T10:00:00+00:00', Bruno='b2')
        git(self.root, 'checkout', '-q', 'main')
        commit(self.root, 'main', 'Ada', '2026-10-03T10:00:00+00:00', Anna='a2')
        git(self.root, 'merge', '-q', '--no-ff', '-m', 'merge', 'altro', author='Teseo')
        rows = {row[0]: row for row in collect(self.root, {'Anna', 'Bruno'})}
        self.assertEqual((rows['Anna'][3], rows['Bruno'][3], rows['Bruno'][6]), ('Ada', 'Bruno', 2))

    def test_a_copy_is_a_birth_for_the_destination_and_leaves_the_source_history_alone(self):
        log = ('\x1e' + '\x1f'.join(['c2', 'Bruno', '2026-10-02T10:00:00+00:00', 'copia', '']) + '\nC100\twiki/Sorgente.md\twiki/Copia.md\n'
               '\x1e' + '\x1f'.join(['c1', 'Ada', '2026-10-01T10:00:00+00:00', 'inizio', '']) + '\nA\twiki/Sorgente.md\n')
        with mock.patch('kit.dashboard.authors.history_head', return_value='0' * 40), mock.patch('kit.dashboard.authors._git', return_value=log):
            rows = {row[0]: row for row in collect(self.root, {'Sorgente', 'Copia'})}
        self.assertEqual((rows['Copia'][1], rows['Copia'][6]), ('Bruno', 1))
        self.assertEqual((rows['Sorgente'][1], rows['Sorgente'][3], rows['Sorgente'][6]), ('Ada', 'Ada', 1))

    def test_deleted_pages_and_pages_outside_the_set_are_ignored(self):
        commit(self.root, 'uno', 'Ada', '2026-10-01T10:00:00+00:00', Anna='a', Morta='m')
        git(self.root, 'rm', '-q', 'wiki/Morta.md')
        git(self.root, 'commit', '-q', '-m', 'via', author='Bruno', date='2026-10-02T10:00:00+00:00')
        self.assertEqual([row[0] for row in collect(self.root, {'Anna'})], ['Anna'])


class AuthorsAPI(unittest.TestCase):
    stop = queries.Queries.stop
    request = queries.Queries.request
    manifest = queries.Queries.manifest
    hashes = queries.Queries.hashes
    attach = queries.Queries.attach
    get = queries.Queries.get

    def setUp(self):
        queries.Queries.setUp(self)
        git(self.root, 'init', '-q', '-b', 'main')
        git(self.root, 'add', 'wiki')
        git(self.root, 'commit', '-q', '-m', 'inizio', author='Ada', date='2026-10-01T10:00:00+00:00')
        self.before = self.reference
        self.reference = rebuild(self.root)

    def test_a_new_commit_is_a_new_generation_and_nodes_expose_their_authors(self):
        self.assertNotEqual(self.before.generation, self.reference.generation)
        status, _, body = self.get('nodes/' + quote('Anna Rossi', safe=''))
        self.assertEqual(status, 200, body)
        self.assertEqual((body['authors']['created_by'], body['authors']['modified_by'], body['authors']['changes']), ('Ada', 'Ada', 1))
        self.assertNotIn('@', str(body['authors']))

    def test_a_commit_without_content_changes_makes_the_view_stale_until_the_next_rebuild(self):
        self.assertFalse(self.get('status')[2]['stale'])
        git(self.root, 'commit', '-q', '--allow-empty', '-m', 'vuoto', author='Carla', date='2026-10-05T10:00:00+00:00')
        self.assertTrue(self.get('status')[2]['stale'])
        rebuild(self.root)
        self.assertFalse(self.get('status')[2]['stale'])

    def test_authors_endpoint_and_graph_filter(self):
        status, _, body = self.get('authors')
        self.assertEqual((status, body['available'], [a['name'] for a in body['authors']]), (200, True, ['Ada']))
        status, _, body = self.get('graph', {'author': 'Ada'})
        self.assertEqual(status, 200, body)
        self.assertEqual({node['id'] for node in body['nodes']}, {'Anna Rossi', 'Bruno', 'Équipe'})
        status, _, body = self.get('graph', {'author': 'Nessuno'})
        self.assertEqual((status, body['nodes'], body['edges']), (200, [], []))

    def test_vault_without_history_has_an_empty_authors_table(self):
        self.assertEqual(len(rebuild(self.root).generation), 64)
        import shutil
        import stat

        def writable(function, path, _error):  # su Windows gli oggetti Git sono di sola lettura
            os.chmod(path, stat.S_IWRITE)
            function(path)
        shutil.rmtree(self.root / '.git', onerror=writable)
        rebuild(self.root)
        status, _, body = self.get('authors')
        self.assertEqual((status, body['authors']), (200, []))


if __name__ == '__main__':
    unittest.main()

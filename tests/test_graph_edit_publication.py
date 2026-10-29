"""Modifica del grafo dalla dashboard con autosync attivo: apply, rebuild e push attribuito a `dashboard`."""
import _shortpath  # noqa: F401
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import installa
import test_autosync as autosync_tests
import test_dashboard_readonly as http_tests
from kit.dashboard.autosync import Autosync
from kit.dashboard.git_sync import write_local_excludes
from kit.dashboard.server import DashboardServer
from kit.dashboard.storage import capture_snapshot

git = autosync_tests.git


class EditPublication(unittest.TestCase):
    request = http_tests.ReadonlyHTTP.request

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='teseo-publisher-', dir=Path.cwd())
        home = Path(cls.tmp.name)
        template = home / 't'
        with contextlib.redirect_stdout(io.StringIO()):
            installa.installa(template, skill='no', esempio=True, client='claude', dashboard=True)
        cls.remote, cls.root = home / 'remote.git', home / 'a'
        git(home, 'init', '--bare', '-b', 'main', str(cls.remote))
        shutil.copytree(template, cls.root)
        git(cls.root, 'init', '-b', 'main')
        git(cls.root, 'config', 'user.name', 'Alice')
        git(cls.root, 'config', 'user.email', 'alice@example.invalid')
        write_local_excludes(cls.root, autosync_tests.LOCAL)
        git(cls.root, 'add', '-A')
        git(cls.root, 'commit', '-m', 'base')
        git(cls.root, 'remote', 'add', 'origin', str(cls.remote))
        git(cls.root, 'push', '-u', 'origin', 'main')
        Autosync(cls.root, allow_local_remote=True).enable()
        (cls.root / '.graph/build_graph.py').write_text('from pathlib import Path; Path(%r).touch()' % str(home / 'EXECUTED'), encoding='utf-8')  # il servizio non deve eseguirlo

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        publisher = staticmethod(lambda root: Autosync(root, allow_local_remote=True).post('dashboard', 'umano', graph_check=False))
        with mock.patch.object(DashboardServer, '_publish_edit', publisher):
            self.server = DashboardServer()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02})
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_a_dashboard_edit_is_committed_and_pushed_with_the_dashboard_trailers(self):
        status, _, body = self.request('POST', '/api/v1/vaults/attach', {'path': str(self.root)})
        self.assertEqual(status, 200, body)
        base = '/api/v1/vaults/%s/' % json.loads(body)['vault_id']
        status, _, data = self.request('POST', base + 'nodes/Gestionale/edit/preview', {
            'base_content_digest': capture_snapshot(self.root).digest, 'idempotency_key': 'preview_pub_0001',
            'operations': [{'op': 'set_tags', 'tags': ['modificata-da-dashboard']}]})
        self.assertEqual(status, 200, data)
        preview = json.loads(data)
        status, _, data = self.request('POST', base + 'nodes/Gestionale/edit/apply', {
            'preview_id': preview['preview_id'], 'proposal_hash': preview['proposal_hash'], 'idempotency_key': 'apply_pub_0001',
            'mode': 'manual_paused', 'external_writers_paused': True, 'semantic_reviewed': True},
            headers={'If-Match': '"' + preview['base_content_digest'] + '"'})
        self.assertEqual(status, 202, data)
        identifier = json.loads(data)['operation_id']
        for _ in range(600):
            status, _, data = self.request('GET', base + 'operations/' + identifier)
            record = json.loads(data)
            if record['state'] == 'succeeded' and record['publication'] and record['publication']['state'] != 'pending':
                break
            time.sleep(.1)
        self.assertEqual(record['state'], 'succeeded', record)
        self.assertEqual((record['publication']['state'], record['publication']['graph']), ('published', 'skipped'), record['publication'])
        self.assertFalse((self.root.parent / 'EXECUTED').exists())
        message = git(self.remote, 'log', '-1', '--format=%B', 'main')
        self.assertIn('Teseo-Skill: dashboard', message)
        self.assertIn('Teseo-Agent: umano', message)
        self.assertIn('modificata-da-dashboard', git(self.remote, 'show', 'main:wiki/Gestionale.md'))


if __name__ == '__main__':
    unittest.main()

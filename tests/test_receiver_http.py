"""Receiver HTTP: nessuna azione prima dei guard e adozione distinta dal fetch."""
import json
import sqlite3
import unittest
from unittest import mock

import test_dashboard_readonly as fixture
from kit.dashboard.contracts import ContractError


class ReceiverHTTP(unittest.TestCase):
    setUp = fixture.ReadonlyHTTP.setUp
    stop = fixture.ReadonlyHTTP.stop
    request = fixture.ReadonlyHTTP.request
    attach = fixture.ReadonlyHTTP.attach

    def test_status_combines_publisher_and_receiver_without_starting_work(self):
        vault = self.attach()['vault_id']
        self.server.sync = mock.Mock()
        self.server.sync.status.return_value = {'state': 'not_configured', 'head': None}
        receiver = mock.Mock()
        receiver.status.return_value = {'state': 'paused', 'pending_oid': 'a'*40}
        original = self.server.receiver
        self.addCleanup(setattr, self.server, 'receiver', original)
        self.server.receiver = receiver
        status, _, body = self.request('GET', f'/api/v1/vaults/{vault}/sync/status')
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['receiver']['pending_oid'], 'a'*40)
        self.server.sync.status.assert_called_once_with(vault, {})
        receiver.status.assert_called_once_with(vault)
        self.assertEqual(len(receiver.mock_calls), 1)

    def test_receiver_fault_does_not_hide_publication_status(self):
        vault = self.attach()['vault_id']
        self.server.sync = mock.Mock()
        self.server.sync.status.return_value = {'state': 'converged', 'head': 'a'*40}
        original = (self.server.receiver, self.server.receiver_apply)
        self.addCleanup(lambda: setattr(self.server, 'receiver', original[0]))
        self.addCleanup(lambda: setattr(self.server, 'receiver_apply', original[1]))
        self.server.receiver = mock.Mock()
        self.server.receiver.status.side_effect = sqlite3.DatabaseError('corrupt')
        self.server.receiver_apply = mock.Mock()
        self.server.receiver_apply.status.side_effect = ContractError('linked_path', 'Percorso collegato rifiutato')
        status, _, body = self.request('GET', f'/api/v1/vaults/{vault}/sync/status')
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertEqual(data['state'], 'converged')
        self.assertEqual(data['receiver']['error']['code'], 'receiver_storage')
        self.assertEqual(data['receive_transaction']['error']['code'], 'linked_path')
        self.assertNotIn(b'corrupt', body)

    def test_mutations_route_only_to_the_selected_receiver_service(self):
        vault = self.attach()['vault_id']
        original = self.server.receiver
        self.addCleanup(setattr, self.server, 'receiver', original)
        receiver = self.server.receiver = mock.Mock()
        applies = self.server.receiver_apply = mock.Mock()
        for action, service, method in [('check', receiver, 'check'), ('pause', receiver, 'pause'),
                ('resume', receiver, 'resume'), ('receive', applies, 'apply'),
                ('receive-recover', applies, 'recover')]:
            with self.subTest(action=action):
                getattr(service, method).return_value = {'state': 'fixture'}
                payload = {'fixture': action}
                status, _, body = self.request('POST', f'/api/v1/vaults/{vault}/sync/{action}', payload)
                self.assertEqual(status, 200, body)
                getattr(service, method).assert_called_once_with(vault, payload)

    def test_no_receiver_work_before_session_origin_and_csrf_guards(self):
        original = self.server.receiver
        self.addCleanup(setattr, self.server, 'receiver', original)
        receiver = self.server.receiver = mock.Mock()
        applies = self.server.receiver_apply = mock.Mock()
        for action in ('check', 'pause', 'resume', 'receive', 'receive-recover'):
            for kwargs in ({'authenticated': False}, {'csrf': False},
                           {'headers': {'Origin': 'https://other.invalid'}}):
                with self.subTest(action=action, kwargs=kwargs):
                    status, _, body = self.request('POST', '/api/v1/vaults/fixture/sync/'+action, {}, **kwargs)
                    self.assertEqual(status, 403, body)
        self.assertEqual(receiver.mock_calls, [])
        self.assertEqual(applies.mock_calls, [])


if __name__ == '__main__':
    unittest.main()

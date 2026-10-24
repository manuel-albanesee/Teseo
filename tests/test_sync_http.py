"""Publisher HTTP: routing solo dopo sessione, origine e CSRF validi."""
import json
import unittest
from unittest import mock

import test_dashboard_readonly as fixture


class SyncHTTP(unittest.TestCase):
    setUp = fixture.ReadonlyHTTP.setUp
    stop = fixture.ReadonlyHTTP.stop
    request = fixture.ReadonlyHTTP.request
    attach = fixture.ReadonlyHTTP.attach

    def test_read_status_and_mutations_route_to_selected_vault(self):
        vault = self.attach()['vault_id']
        base = f'/api/v1/vaults/{vault}/sync/'
        service = mock.Mock()
        self.server.sync = service
        service.status.return_value = {'state': 'not_configured', 'head': None}
        status, _, body = self.request('GET', base+'status')
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['state'], 'not_configured')
        service.status.assert_called_once_with(vault, {})
        for action in ('preview', 'initialize', 'configure', 'publish', 'resolve'):
            with self.subTest(action=action):
                method = getattr(service, action)
                method.return_value = {'state': 'fixture', 'B': 'a'*40}
                payload = {'fixture': action}
                status, _, body = self.request('POST', base+action, payload)
                self.assertEqual(status, 200, body)
                method.assert_called_once_with(vault, payload)

    def test_no_sync_mutation_before_session_origin_and_csrf_guards(self):
        service = mock.Mock()
        self.server.sync = service
        for action in ('preview', 'initialize', 'configure', 'publish', 'resolve'):
            route = '/api/v1/vaults/fixture/sync/'+action
            for kwargs in ({'authenticated': False}, {'csrf': False},
                           {'headers': {'Origin': 'https://other.invalid'}}):
                with self.subTest(action=action, kwargs=kwargs):
                    status, _, body = self.request('POST', route, {}, **kwargs)
                    self.assertEqual(status, 403, body)
        self.assertEqual(service.mock_calls, [])

    def test_status_still_requires_local_session(self):
        service = mock.Mock()
        self.server.sync = service
        status, _, body = self.request('GET', '/api/v1/vaults/fixture/sync/status',
                                       authenticated=False)
        self.assertEqual(status, 403, body)
        self.assertEqual(service.mock_calls, [])


if __name__ == '__main__':
    unittest.main()

"""Creazione, rinomina ed eliminazione di pagine: preview multi-file validata e apply dal journal."""
import _shortpath  # noqa: F401
from datetime import date
import json
import time
import unittest
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard.contracts import ContractError
from kit.dashboard.graph_service import rebuild
from kit.dashboard.page_ops import _retarget, _without_index_row, build_changes
from kit.dashboard.storage import capture_snapshot

TODAY = date(2026, 10, 29)


def code(documents, operation):
    with unittest.TestCase().assertRaises(ContractError) as caught:
        build_changes(documents, operation, TODAY)
    return caught.exception.code


class Pure(unittest.TestCase):
    def test_retarget_changes_only_the_page_name_and_keeps_section_alias_folder_and_embeds(self):
        text = 'a [[Vecchia]] b [[Vecchia#Sezione|testo]] c ![[Vecchia]] d [[cartella/Vecchia]] e [[Altra]] f [[ Vecchia ]] g [[Vecchia\\|tabella]]'
        self.assertEqual(_retarget(text, 'Vecchia', 'Nuova'),
                         'a [[Nuova]] b [[Nuova#Sezione|testo]] c ![[Nuova]] d [[cartella/Nuova]] e [[Altra]] f [[ Nuova ]] g [[Nuova\\|tabella]]')
        self.assertEqual(_retarget('[[Vecchiaia]] [[Una Vecchia]]', 'Vecchia', 'Nuova'), '[[Vecchiaia]] [[Una Vecchia]]')

    def test_index_row_removal_keeps_every_other_line(self):
        text = '# Indice\n\n| [[A]] | prima |\n| [[B]] | seconda |\n'
        self.assertEqual(_without_index_row(text, 'A'), '# Indice\n\n| [[B]] | seconda |\n')
        self.assertEqual(_without_index_row(text, 'Z'), text)

    def test_names_and_operations_are_validated_with_stable_codes(self):
        docs = {'wiki/A.md': 'a', 'wiki/B.md': 'b'}
        for bad in ('', ' x', 'x ', 'a/b', 'a\\b', 'a:b', 'a|b', 'a#b', 'a[b', 'con.', 'index', 'Log', 'x' * 121, 5):
            self.assertEqual(code(docs, {'op': 'create', 'name': bad, 'tipo': None}), 'edit_invalid', bad)
        self.assertEqual(code(docs, {'op': 'create', 'name': 'a', 'tipo': None}), 'edit_duplicate')  # solo maiuscole
        self.assertEqual(code(docs, {'op': 'rename', 'page': 'A', 'new_name': 'b'}), 'edit_duplicate')
        self.assertEqual(code(docs, {'op': 'rename', 'page': 'A', 'new_name': 'A'}), 'edit_duplicate')
        self.assertEqual(code(docs, {'op': 'rename', 'page': 'Z', 'new_name': 'Q'}), 'node_missing')
        self.assertEqual(code(docs, {'op': 'delete', 'page': 'Z'}), 'node_missing')
        self.assertEqual(code(docs, {'op': 'move'}), 'invalid_payload')
        self.assertEqual(code(docs, {'op': 'delete', 'page': 'A', 'extra': 1}), 'invalid_patch')

    def test_rename_rewrites_links_in_pages_index_and_log_but_not_the_schema(self):
        docs = {'wiki/A.md': '---\ntipo: x\nusa: "[[B]]"\n---\nvedi [[B]]', 'wiki/B.md': '---\ntipo: x\n---\n# B', 'wiki/C.md': 'niente',
                'index.md': '| [[B]] | desc |\n', 'log.md': 'Aggiunta [[B]]', 'Wiki reference.md': 'cita [[B]]'}
        changes = build_changes(docs, {'op': 'rename', 'page': 'B', 'new_name': 'Bis'}, TODAY)
        self.assertEqual(set(changes), {'wiki/B.md', 'wiki/Bis.md', 'wiki/A.md', 'index.md', 'log.md'})
        self.assertIsNone(changes['wiki/B.md'])
        self.assertEqual(changes['wiki/A.md'], '---\ntipo: x\nusa: "[[Bis]]"\n---\nvedi [[Bis]]')
        self.assertEqual(changes['index.md'], '| [[Bis]] | desc |\n')


class Service(unittest.TestCase):
    setUp = fixture.Queries.setUp
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get

    def prepare(self):
        (self.root / 'wiki/Carla.md').write_text('---\ntipo: persona\n---\nCarla vede [[Bruno]]', encoding='utf-8')
        rebuild(self.root)

    def notes(self):
        return {path: digest for path, digest in self.hashes().items() if not path.startswith('.teseo/')}

    def preview(self, operation, expect=200):
        payload = {'base_content_digest': capture_snapshot(self.root).digest, 'idempotency_key': 'preview_' + str(time.time_ns()), 'operation': operation}
        status, _, data = self.request('POST', self.base + 'pages/preview', payload)
        self.assertEqual(status, expect, data)
        return json.loads(data)

    def apply(self, preview, **changes):
        payload = {'preview_id': preview['preview_id'], 'proposal_hash': preview['proposal_hash'], 'idempotency_key': 'pages_request_001',
                   'mode': 'manual_paused', 'external_writers_paused': True, 'semantic_reviewed': True, **changes}
        status, _, data = self.request('POST', self.base + 'pages/apply', payload, headers={'If-Match': '"' + preview['base_content_digest'] + '"'})
        return status, json.loads(data)

    def finish(self, identifier):
        for _ in range(400):
            status, _, body = self.get('operations/' + identifier)
            self.assertEqual(status, 200, body)
            if body['state'] in ('succeeded', 'failed', 'rolled_back', 'recovery_required') and not self.server.applies.active(self.vault_id):
                return body
            time.sleep(.1)
        self.fail('Operazione non terminata')

    def run_operation(self, operation):
        preview = self.preview(operation)
        self.assertTrue(preview['valid'], preview)
        status, record = self.apply(preview)
        self.assertEqual(status, 202, record)
        done = self.finish(record['operation_id'])
        self.assertEqual(done['state'], 'succeeded', done)
        return done

    def test_create_previews_without_writing_then_applies_and_the_page_enters_the_graph(self):
        self.prepare()
        before = self.notes()
        preview = self.preview({'op': 'create', 'name': 'Dario', 'tipo': 'persona'})
        self.assertIn('+tipo: persona', preview['diff'])
        self.assertEqual(preview['paths'], ['wiki/Dario.md'])
        self.assertEqual(self.notes(), before)
        status, record = self.apply(preview)
        self.assertEqual(status, 202, record)
        done = self.finish(record['operation_id'])
        self.assertEqual((done['state'], done['kind']), ('succeeded', 'graph_edit'))
        self.assertEqual(done['checkpoint']['changed_files'], ['wiki/Dario.md'])
        self.assertIn('# Dario', (self.root / 'wiki/Dario.md').read_text(encoding='utf-8'))
        self.assertIn('Dario', [node['id'] for node in self.get('graph')[2]['nodes']])

    def test_rename_moves_the_file_and_retargets_every_link(self):
        self.prepare()
        done = self.run_operation({'op': 'rename', 'page': 'Bruno', 'new_name': 'Bruno Neri'})
        self.assertEqual(sorted(done['checkpoint']['changed_files']), ['wiki/Anna Rossi.md', 'wiki/Bruno Neri.md', 'wiki/Bruno.md', 'wiki/Carla.md'])
        self.assertFalse((self.root / 'wiki/Bruno.md').exists())
        self.assertIn('[[Bruno Neri]]', (self.root / 'wiki/Carla.md').read_text(encoding='utf-8'))
        ids = [node['id'] for node in self.get('graph')[2]['nodes']]
        self.assertIn('Bruno Neri', ids)
        self.assertNotIn('Bruno', ids)

    def test_delete_is_refused_while_other_pages_link_to_it_and_allowed_once_they_do_not(self):
        self.prepare()
        blocked = self.preview({'op': 'delete', 'page': 'Bruno'})
        self.assertFalse(blocked['valid'], blocked)
        self.assertGreater(blocked['new_problems'], 0)
        status, body = self.apply(blocked)
        self.assertEqual((status, body['error']['code']), (422, 'migration_invalid'))
        self.assertTrue((self.root / 'wiki/Bruno.md').exists())
        done = self.run_operation({'op': 'delete', 'page': 'Carla'})
        self.assertEqual(done['checkpoint']['changed_files'], ['wiki/Carla.md'])
        self.assertFalse((self.root / 'wiki/Carla.md').exists())

    def test_the_vault_changing_after_the_preview_refuses_the_apply(self):
        self.prepare()
        preview = self.preview({'op': 'create', 'name': 'Dario', 'tipo': 'persona'})
        (self.root / 'wiki/Carla.md').write_text('---\ntipo: persona\n---\nCambiata', encoding='utf-8')
        status, body = self.apply(preview)
        self.assertEqual((status, body['error']['code']), (409, 'preview_stale'))
        self.assertFalse((self.root / 'wiki/Dario.md').exists())

    def test_apply_requires_explicit_confirmation_and_if_match(self):
        self.prepare()
        preview = self.preview({'op': 'create', 'name': 'Dario', 'tipo': 'persona'})
        status, body = self.apply(preview, external_writers_paused=False)
        self.assertEqual((status, body['error']['code']), (422, 'manual_confirmation_required'))
        payload = {'preview_id': preview['preview_id'], 'proposal_hash': preview['proposal_hash'], 'idempotency_key': 'pages_request_002',
                   'mode': 'manual_paused', 'external_writers_paused': True, 'semantic_reviewed': True}
        status, _, data = self.request('POST', self.base + 'pages/apply', payload)
        self.assertEqual((status, json.loads(data)['error']['code']), (428, 'precondition_required'))


    def test_an_external_writer_during_the_apply_is_never_overwritten(self):
        """Editor non cooperante simulato: crea un file mentre l'apply sta scrivendo. Non si sovrascrive né si dichiara successo."""
        from kit.dashboard import ontology_apply
        self.prepare()
        preview = self.preview({'op': 'create', 'name': 'Dario', 'tipo': 'persona'})
        real = ontology_apply._move_new
        external = self.root / 'wiki/Esterna.md'

        def intruder(staged, target):
            external.write_text('---\ntipo: persona\n---\nscritta da un editor esterno', encoding='utf-8')
            real(staged, target)
        with mock.patch.object(ontology_apply, '_move_new', intruder):
            status, record = self.apply(preview)
            self.assertEqual(status, 202, record)
            done = self.finish(record['operation_id'])
        self.assertNotEqual(done['state'], 'succeeded', done)
        self.assertEqual(external.read_text(encoding='utf-8').splitlines()[-1], 'scritta da un editor esterno')


if __name__ == '__main__':
    unittest.main()

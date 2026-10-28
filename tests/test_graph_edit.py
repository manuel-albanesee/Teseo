"""Editor del grafo: modifiche chirurgiche al frontmatter, preview validata e apply con journal."""
import _shortpath  # noqa: F401
from datetime import date
import json
import time
import unittest

import test_dashboard_queries as fixture
from kit.dashboard.contracts import ContractError
from kit.dashboard.graph_edit import edit_page
from kit.dashboard.graph_service import rebuild
from kit.dashboard.storage import capture_snapshot

TODAY = date(2026, 10, 28)
VOCABULARY = {'usa': (['qualsiasi'], ['qualsiasi']), 'causa': (['qualsiasi'], ['qualsiasi']), 'parte_di': (['qualsiasi'], ['qualsiasi'])}
PAGES = {'A', 'B', 'C'}
BODY = '\n# A\n\nTesto con [[B]] e accenti: è già così.\n'


def page(*lines, newline='\n'):
    return newline.join(['---', *lines, '---']) + BODY.replace('\n', newline)


def edit(text, *operations):
    return edit_page(text, 'A', VOCABULARY, PAGES, list(operations), TODAY)


def code(text, *operations):
    with unittest.TestCase().assertRaises(ContractError) as caught:
        edit(text, *operations)
    return caught.exception.code


class Surgery(unittest.TestCase):
    def test_add_relation_appends_one_line_bumps_the_date_and_keeps_the_body_bytes(self):
        text = page('tipo: processo', 'tags: [uno]', 'aggiornato: 2026-01-02')
        result = edit(text, {'op': 'add_relation', 'relation': 'usa', 'target': 'B'})
        self.assertEqual(result, page('tipo: processo', 'tags: [uno]', 'aggiornato: 2026-10-28', 'usa: "[[B]]"'))
        self.assertTrue(result.endswith(BODY))

    def test_a_second_link_makes_a_list_and_removing_goes_back_to_a_scalar_or_drops_the_key(self):
        text = page('tipo: x', 'usa: "[[B]]"')
        both = edit(text, {'op': 'add_relation', 'relation': 'usa', 'target': 'C'})
        self.assertIn('usa: ["[[B]]", "[[C]]"]', both)
        one = edit(both, {'op': 'remove_relation', 'relation': 'usa', 'target': 'B'})
        self.assertIn('usa: "[[C]]"', one)
        self.assertNotIn('usa', edit(one, {'op': 'remove_relation', 'relation': 'usa', 'target': 'C'}))

    def test_other_lines_comments_and_crlf_are_preserved(self):
        text = page('# commento', 'tipo: x', 'fonti: [k]  # fonte', 'tags: [vecchio]', 'parte_di: "[[C]]"', newline='\r\n')
        result = edit(text, {'op': 'set_tags', 'tags': ['nuovo', 'due parole']})
        self.assertEqual(result, page('# commento', 'tipo: x', 'fonti: [k]  # fonte', 'tags: [nuovo, "due parole"]',
                                      'parte_di: "[[C]]"', newline='\r\n'))

    def test_aliases_tipo_and_empty_aliases(self):
        text = page('tipo: x', 'aliases: ["Vecchio"]')
        self.assertIn('aliases: ["Nuovo", "È già"]', edit(text, {'op': 'set_aliases', 'aliases': ['Nuovo', 'È già']}))
        self.assertNotIn('aliases', edit(text, {'op': 'set_aliases', 'aliases': []}))
        self.assertIn('tipo: "true"', edit(text, {'op': 'set_tipo', 'tipo': 'true'}))
        self.assertIn('tipo: sistema', edit(text, {'op': 'set_tipo', 'tipo': 'sistema'}))

    def test_causal_detail_is_added_updated_and_removed_with_its_arc(self):
        text = page('tipo: x', 'causa: "[[B]]"')
        detailed = edit(text, {'op': 'set_relation_detail', 'target': 'B', 'confidenza': 'alta', 'evidenza': 'Lo dice la fonte'})
        self.assertIn('relazioni_dettaglio:\n  "[[B]]": {confidenza: alta, evidenza: "Lo dice la fonte"}', detailed)
        lowered = edit(detailed, {'op': 'set_relation_detail', 'target': 'B', 'confidenza': 'bassa', 'evidenza': None})
        self.assertIn('{confidenza: bassa}', lowered)
        self.assertNotIn('relazioni_dettaglio', edit(lowered, {'op': 'set_relation_detail', 'target': 'B', 'confidenza': None, 'evidenza': None}))
        self.assertNotIn('relazioni_dettaglio', edit(detailed, {'op': 'remove_relation', 'relation': 'causa', 'target': 'B'}))

    def test_several_operations_apply_in_order_to_one_page(self):
        result = edit(page('tipo: x'), {'op': 'add_relation', 'relation': 'usa', 'target': 'B'},
                      {'op': 'set_tags', 'tags': ['t']}, {'op': 'set_aliases', 'aliases': ['Alias']})
        self.assertEqual(result, page('tipo: x', 'usa: "[[B]]"', 'tags: [t]', 'aliases: ["Alias"]'))

    def test_a_trailing_blank_line_in_the_frontmatter_stays_after_the_new_key(self):
        result = edit(page('tipo: x', ''), {'op': 'add_relation', 'relation': 'usa', 'target': 'B'})
        self.assertEqual(result, page('tipo: x', 'usa: "[[B]]"', ''))


class Refusals(unittest.TestCase):
    def test_semantic_refusals_have_stable_codes(self):
        text = page('tipo: x', 'usa: "[[B]]"', 'causa: "[[B]]"')
        cases = [
            ({'op': 'add_relation', 'relation': 'inventata', 'target': 'C'}, 'edit_unknown_relation'),
            ({'op': 'add_relation', 'relation': 'tags', 'target': 'C'}, 'edit_unknown_relation'),
            ({'op': 'add_relation', 'relation': 'usa', 'target': 'Fantasma'}, 'edit_unknown_target'),
            ({'op': 'add_relation', 'relation': 'usa', 'target': 'A'}, 'edit_unknown_target'),
            ({'op': 'add_relation', 'relation': 'usa', 'target': 'B'}, 'edit_duplicate'),
            ({'op': 'remove_relation', 'relation': 'usa', 'target': 'C'}, 'edit_missing'),
            ({'op': 'set_relation_detail', 'target': 'C', 'confidenza': 'alta', 'evidenza': None}, 'edit_missing'),
            ({'op': 'set_relation_detail', 'target': 'B', 'confidenza': 'certa', 'evidenza': None}, 'edit_invalid'),
            ({'op': 'set_relation_detail', 'target': 'B', 'confidenza': None, 'evidenza': 'a\nb'}, 'edit_invalid'),
            ({'op': 'set_tags', 'tags': ['a', 'a']}, 'edit_invalid'),
            ({'op': 'set_aliases', 'aliases': [' spazio']}, 'edit_invalid'),
            ({'op': 'set_tipo', 'tipo': 'due parole'}, 'edit_invalid'),
            ({'op': 'cancella_tutto'}, 'invalid_patch'),
            ({'op': 'add_relation', 'relation': 'usa'}, 'invalid_patch'),
        ]
        for operation, expected in cases:
            with self.subTest(operation=operation):
                self.assertEqual(code(text, operation), expected)

    def test_noop_and_limits(self):
        self.assertEqual(code(page('tipo: x', 'tags: [a]'), {'op': 'set_tags', 'tags': ['a']}), 'edit_noop')
        self.assertEqual(code(page('tipo: x'), *[{'op': 'set_tipo', 'tipo': 'y'}] * 17), 'invalid_payload')

    def test_ambiguous_yaml_is_left_to_the_author(self):
        for lines in (('tipo: x', 'tipo: y'), ('tipo: &t x', 'base: *t'), ('tipo: x', '"chiave quotata": 1')):
            with self.subTest(lines=lines):
                self.assertEqual(code(page(*lines), {'op': 'set_tags', 'tags': ['t']}), 'edit_manual')
        self.assertEqual(code('senza frontmatter\n', {'op': 'set_tags', 'tags': ['t']}), 'edit_manual')


class Service(unittest.TestCase):
    setUp = fixture.Queries.setUp
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get

    def prepare(self):
        (self.root / 'wiki/Carla.md').write_text('---\ntipo: persona\n---\nCarla', encoding='utf-8')
        rebuild(self.root)

    def notes(self):
        return {path: digest for path, digest in self.hashes().items() if not path.startswith('.teseo/')}

    def preview(self, node, operations, key=None, expect=200):
        payload = {'base_content_digest': capture_snapshot(self.root).digest, 'idempotency_key': key or 'preview_' + str(time.time_ns()),
                   'operations': operations}
        status, _, data = self.request('POST', self.base + 'nodes/' + node.replace(' ', '%20') + '/edit/preview', payload)
        self.assertEqual(status, expect, data)
        return json.loads(data)

    def apply(self, node, preview, **changes):
        payload = {'preview_id': preview['preview_id'], 'proposal_hash': preview['proposal_hash'], 'idempotency_key': 'edit_request_001',
                   'mode': 'manual_paused', 'external_writers_paused': True, 'semantic_reviewed': True, **changes}
        status, _, data = self.request('POST', self.base + 'nodes/' + node.replace(' ', '%20') + '/edit/apply', payload,
                                       headers={'If-Match': '"' + preview['base_content_digest'] + '"'})
        return status, json.loads(data)

    def finish(self, identifier):
        for _ in range(400):
            status, _, body = self.get('operations/' + identifier)
            self.assertEqual(status, 200, body)
            if body['state'] in ('succeeded', 'failed', 'rolled_back', 'recovery_required') and not self.server.applies.active(self.vault_id):
                return body
            time.sleep(.1)
        self.fail('Operazione non terminata')

    def test_preview_shows_the_diff_and_writes_nothing(self):
        self.prepare()
        before = self.notes()
        preview = self.preview('Bruno', [{'op': 'add_relation', 'relation': 'usa', 'target': 'Carla'}])
        self.assertTrue(preview['valid'], preview)
        self.assertIn('+usa: "[[Carla]]"', preview['diff'])
        self.assertIn(['Bruno', 'Carla', 'usa'], preview['relations_after'])
        self.assertEqual(self.notes(), before)

    def test_preview_reports_vocabulary_type_violations_and_blocks_the_apply(self):
        self.prepare()
        preview = self.preview('Bruno', [{'op': 'add_relation', 'relation': 'usa', 'target': 'Équipe'}])
        self.assertFalse(preview['valid'])
        self.assertEqual({item['code'] for item in preview['problems']}, {'relation_types'})
        before = self.notes()
        status, body = self.apply('Bruno', preview)
        self.assertEqual((status, body['error']['code']), (422, 'migration_invalid'))
        self.assertEqual(self.notes(), before)

    def test_preview_idempotency_stale_digest_and_unknown_page(self):
        self.prepare()
        operations = [{'op': 'set_tags', 'tags': ['x']}]
        first = self.preview('Bruno', operations, key='same_key_0001')
        self.assertEqual(self.preview('Bruno', operations, key='same_key_0001')['preview_id'], first['preview_id'])
        other = self.preview('Bruno', [{'op': 'set_tags', 'tags': ['y']}], key='same_key_0001', expect=409)
        self.assertEqual(other['error']['code'], 'idempotency_conflict')
        self.assertEqual(self.preview('Fantasma', operations, expect=404)['error']['code'], 'node_missing')
        status, _, data = self.request('POST', self.base + 'nodes/Bruno/edit/preview',
                                       {'base_content_digest': '0' * 64, 'idempotency_key': 'stale_key_0001', 'operations': operations})
        self.assertEqual((status, json.loads(data)['error']['code']), (409, 'preview_stale'))

    def test_apply_writes_the_page_rebuilds_the_graph_and_reports_the_publication(self):
        self.prepare()
        preview = self.preview('Bruno', [{'op': 'add_relation', 'relation': 'usa', 'target': 'Carla'}])
        status, record = self.apply('Bruno', preview)
        self.assertEqual(status, 202, record)
        done = self.finish(record['operation_id'])
        self.assertEqual(done['state'], 'succeeded', done)
        self.assertEqual(done['kind'], 'graph_edit')
        self.assertEqual(done['checkpoint']['changed_files'], ['wiki/Bruno.md'])
        self.assertIn('usa: "[[Carla]]"', (self.root / 'wiki/Bruno.md').read_text(encoding='utf-8'))
        self.assertEqual(done['publication']['state'], 'disabled')
        status, _, graph = self.get('graph', {'relation': 'usa'})
        self.assertIn({'source_id': 'Bruno', 'target_id': 'Carla', 'type': 'usa'}, graph['edges'])

    def test_apply_is_refused_when_the_vault_changed_after_the_preview(self):
        self.prepare()
        preview = self.preview('Bruno', [{'op': 'set_tags', 'tags': ['x']}])
        (self.root / 'wiki/Carla.md').write_text('---\ntipo: persona\n---\nCarla cambiata', encoding='utf-8')
        status, body = self.apply('Bruno', preview)
        self.assertEqual((status, body['error']['code']), (409, 'preview_stale'))
        self.assertNotIn('tags', (self.root / 'wiki/Bruno.md').read_text(encoding='utf-8'))

    def test_apply_requires_explicit_confirmation_and_if_match(self):
        self.prepare()
        preview = self.preview('Bruno', [{'op': 'set_tags', 'tags': ['x']}])
        status, body = self.apply('Bruno', preview, external_writers_paused=False)
        self.assertEqual((status, body['error']['code']), (422, 'manual_confirmation_required'))
        payload = {'preview_id': preview['preview_id'], 'proposal_hash': preview['proposal_hash'], 'idempotency_key': 'edit_request_002',
                   'mode': 'manual_paused', 'external_writers_paused': True, 'semantic_reviewed': True}
        status, _, data = self.request('POST', self.base + 'nodes/Bruno/edit/apply', payload)
        self.assertEqual((status, json.loads(data)['error']['code']), (428, 'precondition_required'))

    def test_a_replayed_apply_returns_the_same_operation(self):
        self.prepare()
        preview = self.preview('Bruno', [{'op': 'set_tags', 'tags': ['x']}])
        first = self.apply('Bruno', preview)[1]
        self.finish(first['operation_id'])
        self.assertEqual(self.apply('Bruno', preview)[1]['operation_id'], first['operation_id'])


if __name__ == '__main__':
    unittest.main()

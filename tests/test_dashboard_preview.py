"""Preview HTTP su snapshot corrente: impatto completo, conflitti e zero scritture."""
from concurrent.futures import ThreadPoolExecutor
import html
import json
import unittest
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard.storage import capture_snapshot
from kit.dashboard import ontology_preview
from kit.graph.ontology import parse

TYPES = ('## Tipi ammessi\n| Tipo | Descrizione |\n| --- | --- |\n'
         '| `persona` | Persone |\n| `sistema` | Sistemi |\n| `fonte` | Fonti |\n\n')


class Preview(unittest.TestCase):
    setUp = fixture.Queries.setUp
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get

    def canonical(self):
        path = self.root / 'Wiki reference.md'
        path.write_bytes(('\ufeff' + TYPES + self.schema).replace('\n', '\r\n').encode())

    def payload(self, patch, key='preview_0001'):
        return {'base_content_digest': capture_snapshot(self.root).digest,
                'idempotency_key': key, 'patch': patch}

    def post(self, body, **kwargs):
        status, _, data = self.request('POST', self.base + 'ontology/preview', body, **kwargs)
        return status, json.loads(data)

    def preview(self, patch, key='preview_0001'):
        status, body = self.post(self.payload(patch, key))
        self.assertEqual(status, 200, body)
        self.assertTrue(body['analysis_complete'])
        return body

    def test_explicit_adoption_is_preview_only_deterministic_and_idempotent(self):
        before = self.hashes()
        payload = self.payload([{'op': 'adopt_types'}])
        first = self.post(payload)
        self.assertEqual(first[0], 200, first)
        self.assertEqual(self.post(payload), first)
        record = first[1]
        self.assertTrue(parse(html.unescape(record['candidate_schema'])).editable)
        self.assertTrue(record['requires_confirmation'])
        self.assertFalse(record['apply_available'])
        self.assertEqual(record['idempotency_scope'], 'service_session')
        self.assertTrue(record['schema_only_valid'])
        self.assertEqual(self.hashes(), before)
        self.assertNotIn(b'## Tipi ammessi', (self.root / 'Wiki reference.md').read_bytes())
        self.assertFalse((self.root / 'EXECUTED').exists())

    def test_new_relation_has_no_inference_and_preserves_opaque_source(self):
        self.canonical()
        source = (self.root / 'Wiki reference.md').read_bytes()
        record = self.preview([{'op': 'add_relation', 'name': 'approva', 'value': {
            'from_types': ['persona'], 'to_types': ['qualsiasi'], 'meaning': '<script>inert()</script>', 'example': 'A → B'}}])
        self.assertTrue(record['schema_only_valid'])
        self.assertFalse(record['semantic_capabilities']['automatic_inference'])
        self.assertEqual(record['semantic_capabilities']['new_relations'], ['approva'])
        self.assertIn('&lt;script&gt;', record['candidate_schema'])
        base, after = parse(source), parse(html.unescape(record['candidate_schema']))
        self.assertEqual(after.source[after.relations_span.end:], source[base.relations_span.end:])
        self.assertEqual(record['content_revision'], capture_snapshot(self.root).digest)
        self.assertIsNone(record['graph_generation'])

    def test_remove_used_relation_reports_page_property_target_and_counts(self):
        self.canonical()
        before = self.hashes()
        record = self.preview([{'op': 'remove_relation', 'name': 'usa'}])
        violation = next(item for item in record['violations'] if item['code'] == 'unknown_relation')
        self.assertEqual((violation['page'], violation['property'], violation['target']), ('wiki/Anna Rossi.md', 'usa', 'Bruno'))
        self.assertTrue(violation['reason'])
        self.assertFalse(record['schema_only_valid'])
        self.assertEqual(record['usage']['properties']['usa'], 1)
        self.assertEqual(record['usage']['types']['persona'], 2)
        self.assertIn('wiki/Anna Rossi.md', record['impacted_pages'])
        self.assertEqual(self.hashes(), before)

    def test_restriction_same_type_and_wildcard_are_builder_validated(self):
        self.canonical()
        value = {'from_types': ['qualsiasi'], 'to_types': ['stesso tipo']}
        self.assertTrue(self.preview([{'op': 'update_relation', 'name': 'usa', 'value': value}])['schema_only_valid'])
        value['to_types'] = ['sistema']
        record = self.preview([{'op': 'update_relation', 'name': 'usa', 'value': value}], 'preview_0002')
        self.assertTrue(any(item['code'] == 'relation_types' and item['property'] == 'usa' for item in record['violations']))

    def test_rename_relation_suggests_exact_migration_without_modifying_notes(self):
        self.canonical()
        before = self.hashes()
        record = self.preview([{'op': 'rename_relation', 'name': 'usa', 'to': 'utilizza'}])
        suggestion = record['migration_suggestions'][0]
        self.assertEqual((suggestion['page'], suggestion['from'], suggestion['to']), ('wiki/Anna Rossi.md', 'usa', 'utilizza'))
        self.assertTrue(suggestion['deterministic'])
        self.assertTrue(suggestion['requires_confirmation'])
        self.assertTrue(record['requires_migration'])
        self.assertFalse(record['schema_only_valid'])
        self.assertEqual(self.hashes(), before)

    def test_rename_collision_and_complex_yaml_require_manual_work(self):
        self.canonical()
        original = self.page.read_text(encoding='utf-8')
        for replacement in ('usa: "[[Bruno]]"\nutilizza: "[[Bruno]]"', '"usa": "[[Bruno]]"'):
            self.page.write_text(original.replace('usa: "[[Bruno]]"', replacement), encoding='utf-8')
            record = self.preview([{'op': 'rename_relation', 'name': 'usa', 'to': 'utilizza'}], 'rename_' + str(len(replacement)))
            self.assertFalse(record['migration_suggestions'][0]['deterministic'])
            self.assertTrue(any(item['code'] == 'migration_manual' for item in record['violations']))

    def test_type_rename_updates_schema_constraints_but_only_suggests_page_edits(self):
        self.canonical()
        record = self.preview([{'op': 'rename_type', 'name': 'persona', 'to': 'individuo'}])
        self.assertEqual(record['model']['relations'][0]['from_types'], ['individuo'])
        self.assertEqual(len(record['migration_suggestions']), 2)
        self.assertTrue(all(item['property'] == 'tipo' for item in record['migration_suggestions']))
        self.assertTrue(any(item['code'] == 'unknown_page_type' for item in record['violations']))

    def test_references_alias_sources_index_and_shared_are_accounted_for(self):
        self.canonical()
        (self.root / 'index.md').write_text('[[Anna Rossi]]', encoding='utf-8')
        events = self.root / '.teseo/shared/events'
        events.mkdir(parents=True)
        (events / 'old.json').write_text('{"opaque":true}', encoding='utf-8')
        record = self.preview([{'op': 'rename_relation', 'name': 'usa', 'to': 'utilizza'}])
        self.assertEqual({item['kind'] for item in record['references']}, {'frontmatter', 'body', 'document'})
        page = next(item for item in record['usage']['pages'] if item['page'] == 'wiki/Anna Rossi.md')
        self.assertEqual(page['aliases'], ['Anni'])
        self.assertEqual(page['sources'], ['nota-utente'])
        self.assertTrue(any(item['code'] == 'shared_mapping_unavailable' and item['property'] == 'shared_records' for item in record['violations']))

    def test_schema_errors_reserved_inversion_unknown_types_and_duplicates_are_structured(self):
        self.canonical()
        patches = [
            [{'op': 'rename_relation', 'name': 'usa', 'to': 'tipo'}],
            [{'op': 'update_relation', 'name': 'usa', 'value': {'from_types': ['ignoto'], 'to_types': ['persona']}}],
            [{'op': 'update_relation', 'name': 'usa', 'value': {'from_types': ['persona'], 'to_types': ['persona'], 'direction': 'target_to_source'}}],
            [{'op': 'add_type', 'name': 'Persona', 'value': {}}],
        ]
        for patch in patches:
            status, error = self.post(self.payload(patch))
            self.assertEqual(status, 422, error)
            self.assertEqual(error['error']['code'], 'invalid_schema')
            self.assertTrue(all(item['page'] and item['property'] and item['reason'] for item in error['error']['details']))

    def test_bad_payload_duplicate_json_unknown_ops_and_legacy_adoption_are_rejected(self):
        payload = self.payload([{'op': 'add_type', 'name': 'nuovo', 'value': {}}])
        self.assertEqual(self.post(payload)[1]['error']['code'], 'catalog_adoption_required')
        for patch in ([{'op': 'rename_page', 'name': 'Bruno', 'to': '../escape'}], [{'op': 'adopt_types', 'path': '../x'}], []):
            self.assertEqual(self.post(self.payload(patch))[0], 400)
        self.assertEqual(self.post(b'{"patch":[],"patch":[]}')[1]['error']['code'], 'duplicate_key')

    def test_stale_base_and_stale_replay_rejected_without_any_writes(self):
        payload = self.payload([{'op': 'adopt_types'}])
        self.assertEqual(self.post(payload)[0], 200)
        self.page.write_text(self.page.read_text(encoding='utf-8') + '\nExternal edit', encoding='utf-8')
        before = self.hashes()
        status, error = self.post(payload)
        self.assertEqual((status, error['error']['code']), (409, 'preview_stale'))
        self.assertEqual(self.hashes(), before)

    def test_idempotency_conflict_concurrent_retries_capacity_and_expiry(self):
        payload = self.payload([{'op': 'adopt_types'}])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.post, [payload, payload]))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], 200, results)
        conflict = dict(payload, patch=[{'op': 'adopt_types'}, {'op': 'add_type', 'name': 'nuovo', 'value': {}}])
        self.assertEqual(self.post(conflict)[1]['error']['code'], 'idempotency_conflict')
        self.server.previews.capacity = 1
        self.assertEqual(self.post(dict(payload, idempotency_key='another_0001'))[1]['error']['code'], 'preview_limit')
        self.server.previews._cache = {key: (0, value[1], value[2]) for key, value in self.server.previews._cache.items()}
        self.assertEqual(self.post(dict(payload, idempotency_key='another_0001'))[0], 200)

    def test_external_edit_during_analysis_is_conflict_and_not_cached(self):
        payload = self.payload([{'op': 'adopt_types'}])
        real = ontology_preview.analyze
        def changed(*args):
            record = real(*args)
            self.page.write_text('---\ntipo: persona\n---\nChanged', encoding='utf-8')
            return record
        with mock.patch.object(ontology_preview, 'analyze', side_effect=changed):
            status, error = self.post(payload)
        self.assertEqual((status, error['error']['code']), (409, 'blocked_external_change'))
        self.assertEqual(self.server.previews._cache, {})

    def test_auth_origin_csrf_bounds_and_apply_unavailable(self):
        payload = self.payload([{'op': 'adopt_types'}])
        for kwargs in ({'authenticated': False}, {'csrf': False}, {'headers': {'Origin': 'https://hostile.invalid'}}):
            self.assertEqual(self.post(payload, **kwargs)[0], 403)
        self.assertEqual(self.post(b'x' * (16384 + 1))[0], 400)
        status, _, _ = self.request('POST', self.base + 'ontology/apply', {'preview_id': 'fake'})
        self.assertEqual(status, 400)

    def test_limits_parse_failure_and_no_graph_required(self):
        self.page.write_text('---\ntipo: [broken\n---\n', encoding='utf-8')
        self.assertEqual(self.post(self.payload([{'op': 'adopt_types'}]))[1]['error']['code'], 'preview_parse_failed')
        self.page.write_text('---\ntipo: persona\n---\nAnna', encoding='utf-8')
        marker = self.root / '.teseo/local/graph-current.json'
        marker.unlink()
        self.assertEqual(self.post(self.payload([{'op': 'adopt_types'}]))[0], 200)
        with mock.patch.object(ontology_preview, 'MAX_RESPONSE', 1):
            self.assertEqual(self.post(self.payload([{'op': 'adopt_types'}], 'limit_0001'))[1]['error']['code'], 'preview_limit')

    def test_free_text_review_and_type_removal_are_located(self):
        self.canonical()
        self.page.write_text(self.page.read_text(encoding='utf-8') + '\nLa persona usa il sistema.', encoding='utf-8')
        record = self.preview([{'op': 'remove_type', 'name': 'sistema'}])
        self.assertTrue(any(item['page'] == 'wiki/Équipe.md' and item['property'] == 'tipo' for item in record['violations']))
        self.assertTrue(any(item['page'] == 'wiki/Anna Rossi.md' and item['property'] == 'body' for item in record['manual_review']))

    def test_rename_chain_and_incompatible_destination_are_not_deterministic(self):
        self.canonical()
        patch = [{'op': 'update_relation', 'name': 'usa', 'value': {'from_types': ['sistema'], 'to_types': ['sistema']}},
                 {'op': 'rename_relation', 'name': 'usa', 'to': 'utilizza'}]
        self.assertFalse(self.preview(patch)['migration_suggestions'][0]['deterministic'])
        patch = [{'op': 'rename_relation', 'name': 'usa', 'to': 'utilizza'},
                 {'op': 'rename_relation', 'name': 'utilizza', 'to': 'adopera'}]
        self.assertEqual(self.post(self.payload(patch, 'chain_0001'))[0], 400)

    def test_legacy_manifest_absent_is_readonly_and_busy_limit_is_bounded(self):
        self.server.previews._slots.acquire()
        self.server.previews._slots.acquire()
        try:
            self.assertEqual(self.post(self.payload([{'op': 'adopt_types'}]))[0], 429)
        finally:
            self.server.previews._slots.release()
            self.server.previews._slots.release()
        (self.root / '.teseo/project.json').unlink()
        self.vault_id = self.attach()['vault_id']
        self.base = f'/api/v1/vaults/{self.vault_id}/'
        before = self.hashes()
        status, error = self.post({'base_content_digest': 'a' * 64, 'idempotency_key': 'legacy_0001', 'patch': [{'op': 'adopt_types'}]})
        self.assertEqual((status, error['error']['code']), (422, 'vault_readonly'))
        self.assertEqual(self.hashes(), before)


if __name__ == '__main__':
    unittest.main()
